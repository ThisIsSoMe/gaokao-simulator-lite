"""
中国高考模拟器 - Flask版本
精美容器化网页服务
"""

from flask import Flask, render_template, jsonify, request, session
import os
import random
from datetime import datetime
from dotenv import load_dotenv
from ai_service import get_ai_event, is_ai_enabled, get_ai_report

load_dotenv()

app = Flask(__name__)
app.secret_key = 'gaokao-simulator-secret-key-2024'

# AI 动态事件占比（0~1）。默认 0.8，即约 80% 事件由 LLM 生成，其余用静态事件兜底。
def _load_ai_ratio():
    try:
        ratio = float(os.getenv('AI_EVENT_RATIO', '0.8'))
    except (TypeError, ValueError):
        ratio = 0.8
    return max(0.0, min(1.0, ratio))

AI_EVENT_RATIO = _load_ai_ratio()

# 时间锚点里程碑事件：在其特定月份必触发，不被 AI 抽签替换（保证剧情节奏）
# 注意：仅收录“条件确定、到点必发”的剧情锚点；带 random 概率的考试事件（如 final_exam）
# 不属于里程碑，留给静态事件池随机触发，否则会与同月锚点（如 science_vs_arts）抢占。
MILESTONE_EVENT_IDS = {'science_vs_arts', 'midterm_exam', 'gaokao_countdown', 'mock_exam'}

# 结局报告的七个维度。游戏过程中需保证每个维度都至少触发过一次对应事件，
# 这样结局报告（七维度点评）才有真实素材，不会出现“无相关经历”。
TARGET_CATEGORIES = ['学业', '社交', '家庭', '日常', '校园', '同桌', '感情']

# ==================== 游戏数据模型 ====================

class Player:
    def __init__(self, config):
        self.name = config.get('name', '张三')
        self.gender = config.get('gender', '男')
        self.province = config.get('province', '北京市')
        self.start_year = config.get('start_year', 2020)
        self.learning_ability = config.get('learning_ability', 70)
        self.initial_score = config.get('initial_score', 65)
        self.personality = config.get('personality', {
            'introvert': 50,
            'rational': 50,
            'stress_resistance': 60
        })
        self.interests = config.get('interests', ['数学', '篮球'])
        self.subject_preference = config.get('subject_preference', '理科')
        self.initial_friends = config.get('initial_friends', 2)
        self.family_type = config.get('family_type', '普通')

        # 状态值
        self.grade = 1  # 1=高一, 2=高二, 3=高三
        self.month = 9  # 9月入学
        self.mood = 80
        self.stress = 30
        self.health = 90
        self.money = self.get_initial_money()

        # 成绩
        self.subjects = self.generate_subjects()

        # 社交
        self.friends = self.generate_friends()
        self.teacher_relation = 60
        self.deskmate_relation = 70
        # 人物关系槽位：暗恋对象、家人、班主任（teacher.relation 与 teacher_relation 同步）
        # 感情线有两条：crush=你喜欢的人（你主动暗恋），admirer=喜欢你的人（TA主动示好）
        self.crush = self.generate_crush()
        self.admirer = self.generate_admirer()
        self.family = self.generate_family()
        self.teacher = self.generate_teacher()

        # 历史
        self.history = []

        # 当前事件
        self.current_event = None

        # 已触发的事件（防重复，初始为list以支持JSON序列化）
        self.used_events = []

        # 连续危机月份计数：用于“退学”判定，避免单次状态波动就提前结束游戏
        self.danger_streak = 0

    def get_initial_money(self):
        money_map = {
            '完满': 1000,
            '普通': 500,
            '穷困': 100,
            '单亲': 300,
            '特殊': 400
        }
        return money_map.get(self.family_type, 500)

    def generate_subjects(self):
        base = self.initial_score
        return {
            'chinese': max(0, min(150, base + random.uniform(-10, 10))),
            'math': max(0, min(150, base * 1.1 + random.uniform(-10, 10))),
            'english': max(0, min(150, base + random.uniform(-10, 10))),
            'physics': max(0, min(100, base * 0.9 + random.uniform(-10, 10))),
            'chemistry': max(0, min(100, base * 0.85 + random.uniform(-10, 10))),
            'biology': max(0, min(100, base * 0.8 + random.uniform(-10, 10))),
            'history': max(0, min(100, base * 0.75 + random.uniform(-10, 10))),
            'geography': max(0, min(100, base * 0.75 + random.uniform(-10, 10))),
            'politics': max(0, min(100, base * 0.7 + random.uniform(-10, 10)))
        }

    def generate_friends(self):
        names = ['李四', '王五', '赵六', '钱七', '孙八', '周九', '吴十', '郑一', '陈二', '刘三']
        random.shuffle(names)
        return [
            {'name': names[i], 'relation': 60 + random.randint(0, 20)}
            for i in range(min(self.initial_friends, 10))
        ]

    def generate_crush(self):
        # 你喜欢的人：按性别取异性名字作为暗恋对象
        if self.gender == '男':
            names = ['林晚晴', '苏念', '陈小满', '顾微', '夏沫', '江雪']
        else:
            names = ['沈聿', '陆景行', '顾沉舟', '林深', '江屿', '宋知']
        return {
            'name': random.choice(names),
            'relation': 30 + random.randint(0, 15),
            'confessed': False
        }

    def generate_admirer(self):
        # 喜欢你的人：异性名库（与 crush 不重名），TA 对你的好感初始就较高
        crush_name = getattr(self, 'crush', None)
        crush_name = crush_name['name'] if isinstance(crush_name, dict) else None
        if self.gender == '男':
            names = ['白槿', '温绵', '舒窈', '乔雨', '安然', '叶蓁']
        else:
            names = ['程屿', '霍洲', '裴亦', '时安', '宋屿', '陆衍']
        # 修正可能的脏数据，确保候选名干净
        names = [n for n in names if n and n != crush_name]
        return {
            'name': random.choice(names),
            'relation': 45 + random.randint(0, 20),
            'accepted': False
        }

    def generate_family(self):
        members = []
        if self.family_type == '单亲':
            role = random.choice(['母亲', '父亲'])
            members.append({'role': role, 'name': f'{self.name[0]}{role}', 'relation': 70 + random.randint(0, 15)})
        else:
            members.append({'role': '父亲', 'name': f'{self.name[0]}爸', 'relation': 65 + random.randint(0, 20)})
            members.append({'role': '母亲', 'name': f'{self.name[0]}妈', 'relation': 70 + random.randint(0, 20)})
        # 完满/普通家庭有一定概率有兄弟姐妹
        if self.family_type in ('完满', '普通') and random.random() > 0.5:
            sib = random.choice(['弟弟', '妹妹', '哥哥', '姐姐'])
            members.append({'role': sib, 'name': f'{self.name[0]}{sib}', 'relation': 60 + random.randint(0, 25)})
        return members

    def generate_teacher(self):
        names = ['王老师', '李老师', '张老师', '刘老师', '陈老师']
        return {'name': random.choice(names), 'relation': self.teacher_relation}

    def get_school_name(self):
        schools = {
            '北京市': ['北京四中', '人大附中', '清华附中'],
            '上海市': ['上海中学', '复旦附中', '华东师大二附中'],
            '广东省': ['华师附中', '深圳中学', '执信中学'],
            '浙江省': ['杭州二中', '镇海中学', '温州中学'],
            '江苏省': ['南外', '苏州中学', '扬州中学']
        }
        school_list = schools.get(self.province, ['第一中学', '第二中学'])
        return random.choice(school_list)

    def calculate_average_score(self):
        if self.subject_preference == '理科':
            total = (self.subjects['chinese'] + self.subjects['math'] +
                    self.subjects['english'] + self.subjects['physics'] +
                    self.subjects['chemistry'] + self.subjects['biology'])
            return round(total / 6, 1)
        elif self.subject_preference == '文科':
            total = (self.subjects['chinese'] + self.subjects['math'] +
                    self.subjects['english'] + self.subjects['history'] +
                    self.subjects['geography'] + self.subjects['politics'])
            return round(total / 6, 1)
        else:
            total = (self.subjects['chinese'] + self.subjects['math'] + self.subjects['english'])
            return round(total / 3, 1)

    def update_stats(self, effects):
        if effects.get('mood'):
            self.mood = max(0, min(100, self.mood + effects['mood']))
        if effects.get('stress'):
            self.stress = max(0, min(100, self.stress + effects['stress']))
        if effects.get('health'):
            self.health = max(0, min(100, self.health + effects['health']))
        if effects.get('money'):
            self.money = max(0, min(10000, self.money + effects['money']))
        if effects.get('score'):
            delta = effects['score']
            for key in self.subjects:
                self.subjects[key] = max(0, min(150, self.subjects[key] + delta * 0.9 + random.uniform(-2, 2)))
        if effects.get('deskmate_relation'):
            self.deskmate_relation = max(0, min(100, self.deskmate_relation + effects['deskmate_relation']))
        if effects.get('teacher_relation'):
            self.teacher_relation = max(0, min(100, self.teacher_relation + effects['teacher_relation']))
            # 命名老师亲密度与标量同步
            if isinstance(getattr(self, 'teacher', None), dict):
                self.teacher['relation'] = self.teacher_relation
        if effects.get('crush_relation'):
            if isinstance(getattr(self, 'crush', None), dict):
                self.crush['relation'] = max(0, min(100, self.crush['relation'] + effects['crush_relation']))
        if effects.get('admirer_relation'):
            if isinstance(getattr(self, 'admirer', None), dict):
                self.admirer['relation'] = max(0, min(100, self.admirer['relation'] + effects['admirer_relation']))
        if effects.get('friend_relation') and getattr(self, 'friends', None):
            # 事件不指定具体某人，作用于首位朋友
            self.friends[0]['relation'] = max(0, min(100, self.friends[0]['relation'] + effects['friend_relation']))
        if effects.get('family_relation') and getattr(self, 'family', None):
            delta = effects['family_relation']
            for member in self.family:
                member['relation'] = max(0, min(100, member['relation'] + delta))

    def can_continue(self):
        return self.health > 20 and self.stress < 90

    def to_dict(self):
        return {
            'name': self.name,
            'gender': self.gender,
            'province': self.province,
            'school': self.get_school_name(),
            'grade': self.grade,
            'year': self.start_year + self.grade - 1,
            'month': self.month,
            'subject_preference': self.subject_preference,
            'family_type': self.family_type,
            'interests': self.interests,
            'mood': self.mood,
            'stress': self.stress,
            'health': self.health,
            'money': self.money,
            'estimated_score': self.calculate_average_score(),
            'subjects': {k: round(v, 1) for k, v in self.subjects.items()},
            'crush': getattr(self, 'crush', None),
            'admirer': getattr(self, 'admirer', None),
            'family': getattr(self, 'family', []),
            'teacher': getattr(self, 'teacher', None),
            'teacher_relation': getattr(self, 'teacher_relation', 60),
            'deskmate_relation': getattr(self, 'deskmate_relation', 70)
        }


# ==================== 事件系统 ====================

EVENTS = {
    'academic': [
        {
            'id': 'quiz_good',
            'category': '学业',
            'title': '测验成绩优异',
            'description': '今天的数学小测验你考了满分，老师当众表扬了你。',
            'choices': [
                {'text': '保持谦虚，继续努力', 'effects': {'mood': 10, 'stress': -5, 'teacher_relation': 5}},
                {'text': '向同桌炫耀', 'effects': {'mood': 5, 'stress': 0, 'deskmate_relation': -5}}
            ],
            'condition': lambda p: p.subjects['math'] > 120 and random.random() > 0.5
        },
        {
            'id': 'quiz_bad',
            'category': '学业',
            'title': '测验失利',
            'description': '物理测验成绩不理想，看着试卷上的红叉，你感到很失落。',
            'choices': [
                {'text': '认真分析错题，请教老师', 'effects': {'mood': -10, 'stress': 10, 'score': 5, 'teacher_relation': 5}},
                {'text': '和同学讨论，寻找原因', 'effects': {'mood': -5, 'stress': 5, 'score': 2}},
                {'text': '暂且不管，下次再说', 'effects': {'mood': -5, 'stress': -5, 'score': -3}}
            ],
            'condition': lambda p: random.random() > 0.7
        },
        {
            'id': 'midterm_exam',
            'category': '学业',
            'title': '期中考试',
            'description': '期中考试即将到来，大家都进入了紧张的备考状态。',
            'choices': [
                {'text': '制定详细复习计划', 'effects': {'mood': -5, 'stress': 15, 'score': 8}},
                {'text': '和同学一起复习', 'effects': {'mood': 5, 'stress': 10, 'score': 5}},
                {'text': '放松心情，正常发挥', 'effects': {'mood': 10, 'stress': 5, 'score': 3}}
            ],
            'condition': lambda p: p.month == 11
        },
        {
            'id': 'final_exam',
            'category': '学业',
            'title': '期末考试',
            'description': '期末考试即将来临，这是检验本学期学习成果的关键时刻。',
            'choices': [
                {'text': '全力以赴，熬夜复习', 'effects': {'mood': -15, 'stress': 20, 'score': 10, 'health': -10}},
                {'text': '劳逸结合，稳步复习', 'effects': {'mood': -5, 'stress': 10, 'score': 7}},
                {'text': '相信平时的积累', 'effects': {'mood': 5, 'stress': 5, 'score': 3}}
            ],
            'condition': lambda p: p.month == 6 and random.random() > 0.5
        },
        {
            'id': 'pop_quiz',
            'category': '学业',
            'title': '突击小测',
            'description': '老师突然宣布来一场随堂测验，全班一片哀嚎。',
            'choices': [
                {'text': '冷静作答', 'effects': {'mood': 0, 'stress': 5, 'score': 4}},
                {'text': '慌乱中乱写', 'effects': {'mood': -8, 'stress': 10, 'score': -4}}
            ],
            'condition': lambda p: random.random() > 0.75
        },
        {
            'id': 'class_question',
            'category': '学业',
            'title': '课堂提问',
            'description': '老师点名让你回答一道有难度的题目，全班目光都落在你身上。',
            'choices': [
                {'text': '自信作答', 'effects': {'mood': 10, 'stress': 5, 'teacher_relation': 8}},
                {'text': '支支吾吾', 'effects': {'mood': -8, 'stress': 10}},
                {'text': '诚实说不会', 'effects': {'mood': -3, 'teacher_relation': 2}}
            ],
            'condition': lambda p: random.random() > 0.78
        }
    ],
    'social': [
        {
            'id': 'make_friend',
            'category': '社交',
            'title': '结识新朋友',
            'description': '在图书馆看到一个同学也在看自己喜欢的书，要不要打个招呼？',
            'choices': [
                {'text': '主动搭话', 'effects': {'mood': 10, 'stress': 5}},
                {'text': '默默观察', 'effects': {'mood': 0, 'stress': 0}}
            ],
            'condition': lambda p: p.personality['introvert'] < 60 and random.random() > 0.6
        },
        {
            'id': 'birthday_party',
            'category': '社交',
            'title': '同桌生日',
            'description': '今天是你同桌的生日，他邀请全班同学参加生日聚会。',
            'choices': [
                {'text': '参加并送礼物', 'effects': {'mood': 10, 'stress': 5, 'deskmate_relation': 15, 'money': -50}},
                {'text': '参加但不送礼物', 'effects': {'mood': 5, 'stress': 5, 'deskmate_relation': 5}},
                {'text': '以学习为由拒绝', 'effects': {'mood': -5, 'stress': 0, 'deskmate_relation': -10}}
            ],
            'condition': lambda p: random.random() > 0.8
        },
        {
            'id': 'conflict',
            'category': '社交',
            'title': '同学矛盾',
            'description': '你和一位同学发生了争执，事情越闹越大。',
            'choices': [
                {'text': '主动道歉和解', 'effects': {'mood': -5, 'stress': 5, 'teacher_relation': 5}},
                {'text': '找老师调解', 'effects': {'mood': 0, 'stress': 10}},
                {'text': '坚持己见，冷战到底', 'effects': {'mood': -15, 'stress': 15, 'teacher_relation': -10}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'group_study',
            'category': '社交',
            'title': '组队学习',
            'description': '几个同学提议组个学习小组，互相督促进步。',
            'choices': [
                {'text': '加入小组', 'effects': {'mood': 10, 'stress': -3, 'score': 4, 'friend_relation': 8}},
                {'text': '更喜欢独自学习', 'effects': {'mood': 0, 'score': 3, 'friend_relation': -3}}
            ],
            'condition': lambda p: random.random() > 0.78
        },
        {
            'id': 'help_classmate',
            'category': '社交',
            'title': '帮助同学',
            'description': '一位平时不太说话的同学遇到了困难，向你求助。',
            'choices': [
                {'text': '热心帮忙', 'effects': {'mood': 12, 'stress': 3, 'friend_relation': 10}},
                {'text': '婉言推脱', 'effects': {'mood': -5, 'stress': 0, 'friend_relation': -5}}
            ],
            'condition': lambda p: random.random() > 0.8
        },
        {
            'id': 'misunderstanding',
            'category': '社交',
            'title': '被误会',
            'description': '同学们似乎对你产生了一些误会，气氛有点微妙。',
            'choices': [
                {'text': '主动解释清楚', 'effects': {'mood': 3, 'stress': 8}},
                {'text': '不在意，做好自己', 'effects': {'mood': -8, 'stress': 5}}
            ],
            'condition': lambda p: random.random() > 0.82
        },
        {
            'id': 'reunion_invite',
            'category': '社交',
            'title': '老友相约',
            'description': '初中的好朋友约你周末出来聚一聚。',
            'choices': [
                {'text': '赴约叙旧', 'effects': {'mood': 15, 'stress': -10, 'friend_relation': 10}},
                {'text': '在家复习', 'effects': {'mood': -3, 'score': 4, 'friend_relation': -5}}
            ],
            'condition': lambda p: random.random() > 0.83
        }
    ],
    'family': [
        {
            'id': 'family_dinner',
            'category': '家庭',
            'title': '家庭聚餐',
            'description': '今天家人都在，难得的一顿温馨晚餐。',
            'choices': [
                {'text': '和家人多聊天', 'effects': {'mood': 15, 'stress': -10, 'family_relation': 10}},
                {'text': '吃完回房间学习', 'effects': {'mood': 0, 'stress': 0, 'score': 2, 'family_relation': -3}}
            ],
            'condition': lambda p: p.family_type != '穷困' and random.random() > 0.5
        },
        {
            'id': 'financial_difficulty',
            'category': '家庭',
            'title': '经济困难',
            'description': '家里经济状况紧张，父母的表情很凝重。',
            'choices': [
                {'text': '主动提出减少开支', 'effects': {'mood': -5, 'stress': 10}},
                {'text': '申请学校补助', 'effects': {'mood': 0, 'stress': 15, 'money': 100}},
                {'text': '找兼职帮补家用', 'effects': {'mood': -10, 'stress': 20, 'score': -5, 'money': 200}}
            ],
            'condition': lambda p: p.family_type == '穷困' and random.random() > 0.5
        },
        {
            'id': 'single_parent_pressure',
            'category': '家庭',
            'title': '单亲负担',
            'description': '父母一方工作到很晚，家里的事情都需要你来帮忙。',
            'choices': [
                {'text': '主动分担家务', 'effects': {'mood': 5, 'stress': 15, 'family_relation': 12}},
                {'text': '以学习为重，少帮忙', 'effects': {'mood': -5, 'stress': 5, 'score': 2, 'family_relation': -5}}
            ],
            'condition': lambda p: p.family_type == '单亲' and random.random() > 0.5
        },
        {
            'id': 'parents_expectation',
            'category': '家庭',
            'title': '父母的期望',
            'description': '饭桌上，父母又聊起了你的成绩和将来的大学。',
            'choices': [
                {'text': '认真倾听并表态', 'effects': {'mood': 0, 'stress': 8, 'score': 3}},
                {'text': '感到压力很大', 'effects': {'mood': -10, 'stress': 12}},
                {'text': '坦诚说出想法', 'effects': {'mood': 8, 'stress': -3}}
            ],
            'condition': lambda p: random.random() > 0.75
        },
        {
            'id': 'parent_care',
            'category': '家庭',
            'title': '深夜的牛奶',
            'description': '你熬夜学习时，父母悄悄端来一杯热牛奶放在桌上。',
            'choices': [
                {'text': '心怀感激继续努力', 'effects': {'mood': 15, 'stress': -5, 'score': 2, 'family_relation': 8}},
                {'text': '让他们早点休息', 'effects': {'mood': 12, 'stress': -8, 'family_relation': 10}}
            ],
            'condition': lambda p: random.random() > 0.72
        },
        {
            'id': 'family_trip',
            'category': '家庭',
            'title': '周末出游',
            'description': '难得的周末，家人提议一起出去走走放松一下。',
            'choices': [
                {'text': '欣然同往', 'effects': {'mood': 15, 'stress': -12, 'health': 3, 'family_relation': 12}},
                {'text': '留在家学习', 'effects': {'mood': 0, 'stress': 3, 'score': 4, 'family_relation': -4}}
            ],
            'condition': lambda p: random.random() > 0.78
        },
        {
            'id': 'relative_compare',
            'category': '家庭',
            'title': '亲戚的比较',
            'description': '亲戚聚会上，又被拿来和"别人家的孩子"比较。',
            'choices': [
                {'text': '一笑置之', 'effects': {'mood': 5, 'stress': 3}},
                {'text': '默默记在心里', 'effects': {'mood': -10, 'stress': 10}},
                {'text': '暗下决心证明自己', 'effects': {'mood': -3, 'stress': 8, 'score': 5}}
            ],
            'condition': lambda p: p.month in [1, 2] and random.random() > 0.78
        }
    ],
    'interest': [
        {
            'id': 'basketball_match',
            'category': '兴趣',
            'title': '篮球比赛',
            'description': '学校组织篮球比赛，你的班级需要你参赛。',
            'choices': [
                {'text': '积极参赛', 'effects': {'mood': 15, 'stress': -10, 'health': 5}},
                {'text': '专注学习不参加', 'effects': {'mood': -5, 'stress': 0, 'score': 3}}
            ],
            'condition': lambda p: '篮球' in p.interests and random.random() > 0.7
        },
        {
            'id': 'music_performance',
            'category': '兴趣',
            'title': '音乐演出',
            'description': '学校艺术节需要会音乐的同学表演，有人推荐了你。',
            'choices': [
                {'text': '登台表演', 'effects': {'mood': 20, 'stress': -5}},
                {'text': '婉言拒绝', 'effects': {'mood': 0, 'stress': 0}}
            ],
            'condition': lambda p: '音乐' in p.interests and random.random() > 0.8
        }
    ],
    'gaokao': [
        {
            'id': 'gaokao_countdown',
            'category': '高考',
            'title': '高考百日誓师',
            'description': '距离高考还有100天，学校组织了誓师大会，气氛热烈。',
            'choices': [
                {'text': '写下目标，全力以赴', 'effects': {'mood': 10, 'stress': 15, 'score': 5}},
                {'text': '保持平常心', 'effects': {'mood': 5, 'stress': 5}}
            ],
            'condition': lambda p: p.grade == 3 and p.month == 2
        },
        {
            'id': 'mock_exam',
            'category': '高考',
            'title': '模拟考试',
            'description': '高考模拟考试结束，你的成绩排名有所变化。',
            'choices': [
                {'text': '分析试卷，找出不足', 'effects': {'mood': -5, 'stress': 10, 'score': 5}},
                {'text': '调整心态，继续努力', 'effects': {'mood': 5, 'stress': 5}}
            ],
            'condition': lambda p: p.grade == 3 and p.month in [3, 4, 5]
        }
    ],
    'random': [
        {
            'id': 'rainy_day',
            'category': '日常',
            'title': '雨天心情',
            'description': '连续几天阴雨，让人心情有些低落。',
            'choices': [
                {'text': '听音乐放松', 'effects': {'mood': 5, 'stress': -5}},
                {'text': '在家学习', 'effects': {'mood': 0, 'stress': 0, 'score': 2}}
            ],
            'condition': lambda p: random.random() > 0.7
        },
        {
            'id': 'good_news',
            'category': '日常',
            'title': '好消息',
            'description': '收到了一个让人开心的消息！',
            'choices': [
                {'text': '分享给朋友', 'effects': {'mood': 15, 'stress': -10}},
                {'text': '暗自开心', 'effects': {'mood': 10, 'stress': -5}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'sick_day',
            'category': '日常',
            'title': '身体不适',
            'description': '今天感觉身体不太舒服，可能是最近太累了。',
            'choices': [
                {'text': '请假休息', 'effects': {'mood': 5, 'stress': -5, 'health': 10, 'score': -2}},
                {'text': '坚持上课', 'effects': {'mood': -5, 'stress': 5, 'health': -5}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'canteen_food',
            'category': '日常',
            'title': '食堂新菜',
            'description': '食堂今天推出了新菜品，看起来还不错。',
            'choices': [
                {'text': '尝一尝', 'effects': {'mood': 5, 'health': 3}},
                {'text': '还是吃老样子', 'effects': {'mood': 0}}
            ],
            'condition': lambda p: random.random() > 0.8
        },
        {
            'id': 'find_money',
            'category': '日常',
            'title': '捡到零钱',
            'description': '路上捡到了10块钱。',
            'choices': [
                {'text': '交给老师', 'effects': {'mood': 5, 'teacher_relation': 5}},
                {'text': '买点零食', 'effects': {'mood': 10, 'money': 10}}
            ],
            'condition': lambda p: random.random() > 0.9
        },
        {
            'id': 'lost_item',
            'category': '日常',
            'title': '物品丢失',
            'description': '你的笔袋不见了，里面有不少文具。',
            'choices': [
                {'text': '到处找找', 'effects': {'mood': -5, 'stress': 5}},
                {'text': '算了，再买新的', 'effects': {'mood': -3, 'money': -20}}
            ],
            'condition': lambda p: random.random() > 0.9
        },
        {
            'id': 'class_party',
            'category': '日常',
            'title': '班级活动',
            'description': '班级组织了一次集体活动。',
            'choices': [
                {'text': '积极参与', 'effects': {'mood': 15, 'stress': -5}},
                {'text': '低调参与', 'effects': {'mood': 5}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'morning_run',
            'category': '日常',
            'title': '清晨跑步',
            'description': '今天起得早，窗外阳光正好，要不要去操场跑两圈？',
            'choices': [
                {'text': '出门跑步', 'effects': {'mood': 8, 'health': 8, 'stress': -5}},
                {'text': '再睡一会儿', 'effects': {'mood': 5, 'health': -2}}
            ],
            'condition': lambda p: random.random() > 0.7
        },
        {
            'id': 'late_night_study',
            'category': '日常',
            'title': '深夜苦读',
            'description': '夜深了，台灯下还有没做完的题，困意阵阵袭来。',
            'choices': [
                {'text': '咬牙坚持', 'effects': {'mood': -5, 'stress': 8, 'score': 5, 'health': -8}},
                {'text': '早点休息', 'effects': {'mood': 5, 'health': 8, 'score': -2}}
            ],
            'condition': lambda p: random.random() > 0.72
        },
        {
            'id': 'phone_temptation',
            'category': '日常',
            'title': '手机的诱惑',
            'description': '本该学习的晚上，手机里的消息一直在响。',
            'choices': [
                {'text': '关机专心学习', 'effects': {'mood': -3, 'stress': 5, 'score': 6}},
                {'text': '刷一会儿放松', 'effects': {'mood': 10, 'stress': -8, 'score': -4}}
            ],
            'condition': lambda p: random.random() > 0.7
        },
        {
            'id': 'spring_outing',
            'category': '日常',
            'title': '春游踏青',
            'description': '春暖花开，学校组织了一次春游活动。',
            'choices': [
                {'text': '尽情放松', 'effects': {'mood': 18, 'stress': -12, 'health': 5}},
                {'text': '带书去看', 'effects': {'mood': 5, 'score': 2}}
            ],
            'condition': lambda p: p.month in [3, 4] and random.random() > 0.7
        },
        {
            'id': 'snow_day',
            'category': '日常',
            'title': '初雪',
            'description': '今年的第一场雪落下，操场上同学们在打雪仗。',
            'choices': [
                {'text': '加入雪仗', 'effects': {'mood': 15, 'stress': -10, 'health': -3}},
                {'text': '窗边看雪', 'effects': {'mood': 10, 'stress': -5}}
            ],
            'condition': lambda p: p.month in [12, 1] and random.random() > 0.72
        },
        {
            'id': 'borrow_notes',
            'category': '日常',
            'title': '借笔记',
            'description': '一位同学想借你整理得很认真的复习笔记。',
            'choices': [
                {'text': '大方借出', 'effects': {'mood': 5, 'stress': 0}},
                {'text': '委婉拒绝', 'effects': {'mood': -3, 'stress': 3}}
            ],
            'condition': lambda p: random.random() > 0.75
        },
        {
            'id': 'study_breakthrough',
            'category': '日常',
            'title': '灵光一现',
            'description': '一道困扰你很久的难题，突然在某一刻豁然开朗。',
            'choices': [
                {'text': '乘胜追击多刷题', 'effects': {'mood': 15, 'score': 6, 'stress': 3}},
                {'text': '开心地休息一下', 'effects': {'mood': 12, 'stress': -5}}
            ],
            'condition': lambda p: random.random() > 0.78
        },
        {
            'id': 'daydream',
            'category': '日常',
            'title': '走神',
            'description': '课上你不知不觉望向窗外，思绪飘到了很远的地方。',
            'choices': [
                {'text': '赶紧收回注意力', 'effects': {'mood': 0, 'score': 3}},
                {'text': '继续放空', 'effects': {'mood': 5, 'stress': -5, 'score': -3}}
            ],
            'condition': lambda p: random.random() > 0.7
        }
    ],
    'era_2000': [
        {
            'id': 'mp3_player',
            'category': '年代',
            'title': 'MP3随身听',
            'description': '最近MP3播放器很流行，同学们都在听周杰伦的歌。',
            'choices': [
                {'text': '攒钱买一个', 'effects': {'mood': 20, 'money': -200}},
                {'text': '借同学的听', 'effects': {'mood': 10}}
            ],
            'condition': lambda p: p.start_year <= 2005 and p.month in [3, 9] and random.random() > 0.7
        },
        {
            'id': 'internet_cafe',
            'category': '年代',
            'title': '网吧风波',
            'description': '有同学邀请你去网吧打游戏。',
            'choices': [
                {'text': '去玩一次', 'effects': {'mood': 15, 'stress': -10, 'score': -5, 'money': -10}},
                {'text': '拒绝，专注学习', 'effects': {'mood': -5, 'score': 2}}
            ],
            'condition': lambda p: p.start_year <= 2010 and random.random() > 0.85
        }
    ],
    'era_2008': [
        {
            'id': 'olympic_craze',
            'category': '年代',
            'title': '奥运热潮',
            'description': '北京奥运会开始了，到处都是奥运氛围！',
            'choices': [
                {'text': '熬夜看比赛', 'effects': {'mood': 20, 'health': -5, 'stress': -5}},
                {'text': '看新闻回放', 'effects': {'mood': 10}}
            ],
            'condition': lambda p: p.start_year == 2008 and p.month in [7, 8] and random.random() > 0.5
        }
    ],
    'era_2010': [
        {
            'id': 'smartphone_wave',
            'category': '年代',
            'title': '智能手机',
            'description': '智能手机开始普及，很多同学都有了iPhone或安卓手机。',
            'choices': [
                {'text': '向父母申请买一个', 'effects': {'mood': 15, 'money': -500}},
                {'text': '继续用功能机', 'effects': {'mood': 0}}
            ],
            'condition': lambda p: 2010 <= p.start_year <= 2015 and random.random() > 0.8
        }
    ],
    'era_2020': [
        {
            'id': 'online_class',
            'category': '年代',
            'title': '网课时代',
            'description': '因为疫情，学校开始上网课了。',
            'choices': [
                {'text': '认真听网课', 'effects': {'mood': -5, 'stress': 5, 'score': 5}},
                {'text': '边听边摸鱼', 'effects': {'mood': 5, 'stress': -5, 'score': -3}}
            ],
            'condition': lambda p: p.start_year >= 2020 and p.month in [2, 3, 4] and random.random() > 0.6
        },
        {
            'id': 'mask_shortage',
            'category': '年代',
            'title': '口罩紧缺',
            'description': '口罩很难买到，家里存货不多了。',
            'choices': [
                {'text': '少出门省着用', 'effects': {'mood': -5, 'stress': 5}},
                {'text': '托人买一些', 'effects': {'mood': 0, 'money': -50}}
            ],
            'condition': lambda p: p.start_year >= 2020 and p.month in [1, 2] and random.random() > 0.7
        }
    ],
    'high_school': [
        {
            'id': 'science_vs_arts',
            'category': '学业',
            'title': '文理分科',
            'description': '高一结束要分文理科了，你需要做出选择。',
            'choices': [
                {'text': '选择理科', 'effects': {'mood': 0}},
                {'text': '选择文科', 'effects': {'mood': 0}}
            ],
            'condition': lambda p: p.grade == 1 and p.month == 6
        },
        {
            'id': 'school_sports',
            'category': '校园',
            'title': '校运会',
            'description': '一年一度的校运会来了！',
            'choices': [
                {'text': '报名参赛', 'effects': {'mood': 15, 'health': 5, 'stress': -10}},
                {'text': '当啦啦队', 'effects': {'mood': 10, 'stress': -5}},
                {'text': '在教室自习', 'effects': {'mood': -5, 'score': 3}}
            ],
            'condition': lambda p: p.month == 10 and random.random() > 0.5
        },
        {
            'id': 'new_teacher',
            'category': '校园',
            'title': '新老师',
            'description': '班里来了位新老师，教学风格很不一样。',
            'choices': [
                {'text': '积极适应', 'effects': {'mood': 5, 'teacher_relation': 10}},
                {'text': '保持距离', 'effects': {'mood': 0}}
            ],
            'condition': lambda p: p.month == 9 and random.random() > 0.7
        },
        {
            'id': 'dorm_life',
            'category': '校园',
            'title': '宿舍生活',
            'description': '和室友的相处中出现了一些小摩擦。',
            'choices': [
                {'text': '主动沟通解决', 'effects': {'mood': 5, 'stress': 5}},
                {'text': '忍一忍算了', 'effects': {'mood': -5, 'stress': 10}}
            ],
            'condition': lambda p: random.random() > 0.8
        },
        {
            'id': 'library_seat',
            'category': '校园',
            'title': '抢自习座位',
            'description': '自习室一座难求，今天你来晚了，只剩下角落一个位置。',
            'choices': [
                {'text': '将就坐下学习', 'effects': {'mood': -3, 'score': 4}},
                {'text': '回教室自习', 'effects': {'mood': 0, 'score': 2}}
            ],
            'condition': lambda p: random.random() > 0.75
        },
        {
            'id': 'flag_speech',
            'category': '校园',
            'title': '国旗下讲话',
            'description': '老师推荐你代表班级在升旗仪式上发言。',
            'choices': [
                {'text': '鼓起勇气接受', 'effects': {'mood': 12, 'stress': 12, 'teacher_relation': 8}},
                {'text': '紧张地推辞', 'effects': {'mood': -3, 'stress': 5}}
            ],
            'condition': lambda p: random.random() > 0.82
        },
        {
            'id': 'club_activity',
            'category': '校园',
            'title': '社团招新',
            'description': '社团招新season，走廊里摆满了各种社团的摊位。',
            'choices': [
                {'text': '报名感兴趣的社团', 'effects': {'mood': 12, 'stress': 3}},
                {'text': '专注学习不参加', 'effects': {'mood': -3, 'score': 3}}
            ],
            'condition': lambda p: p.month == 9 and random.random() > 0.75
        },
        {
            'id': 'cleaning_duty',
            'category': '校园',
            'title': '值日打扫',
            'description': '轮到你做值日，放学后要留下来打扫教室。',
            'choices': [
                {'text': '认真打扫', 'effects': {'mood': 3, 'teacher_relation': 5}},
                {'text': '草草了事', 'effects': {'mood': 0, 'teacher_relation': -3}}
            ],
            'condition': lambda p: random.random() > 0.78
        },
        {
            'id': 'school_festival',
            'category': '校园',
            'title': '校园艺术节',
            'description': '一年一度的校园艺术节开幕，各班都在准备节目。',
            'choices': [
                {'text': '积极参与排练', 'effects': {'mood': 15, 'stress': -8}},
                {'text': '台下当观众', 'effects': {'mood': 8, 'stress': -3}}
            ],
            'condition': lambda p: p.month in [5, 12] and random.random() > 0.75
        }
    ],
    'deskmate': [
        {
            'id': 'deskmate_help',
            'category': '同桌',
            'title': '同桌求助',
            'description': '你的同桌今天上课一直皱眉，课后他/她悄悄问你能不能帮忙讲一道题。',
            'choices': [
                {'text': '耐心讲解', 'effects': {'mood': 5, 'stress': 5, 'deskmate_relation': 15, 'score': 2}},
                {'text': '简单说一下', 'effects': {'mood': 0, 'deskmate_relation': 5}},
                {'text': '自己也没弄懂', 'effects': {'mood': -5, 'stress': 5}}
            ],
            'condition': lambda p: p.deskmate_relation > 50 and random.random() > 0.7
        },
        {
            'id': 'deskmate_snack',
            'category': '同桌',
            'title': '同桌分享零食',
            'description': '同桌偷偷从书包里拿出零食分给你，老师正在讲台上板书。',
            'choices': [
                {'text': '欣然接受', 'effects': {'mood': 10, 'deskmate_relation': 10}},
                {'text': '婉言拒绝，专心听课', 'effects': {'mood': 0, 'score': 2}},
                {'text': '小声提醒他/她注意', 'effects': {'mood': 5, 'deskmate_relation': 5}}
            ],
            'condition': lambda p: p.deskmate_relation > 40 and random.random() > 0.75
        },
        {
            'id': 'deskmate_chat',
            'category': '同桌',
            'title': '课间闲聊',
            'description': '课间休息，同桌突然问你："你觉得高考后想做什么？"',
            'choices': [
                {'text': '畅聊理想和未来', 'effects': {'mood': 15, 'stress': -5, 'deskmate_relation': 20}},
                {'text': '说还没想好', 'effects': {'mood': 5, 'deskmate_relation': 5}},
                {'text': '继续做题，不想这些', 'effects': {'mood': -5, 'stress': 5, 'score': 3}}
            ],
            'condition': lambda p: p.grade >= 2 and p.deskmate_relation > 60 and random.random() > 0.8
        },
        {
            'id': 'deskmate_conflict',
            'category': '同桌',
            'title': '同桌矛盾',
            'description': '同桌今天对你的态度很冷淡，你不知道发生了什么。',
            'choices': [
                {'text': '主动询问原因', 'effects': {'mood': -5, 'stress': 10, 'deskmate_relation': 10}},
                {'text': '写张小纸条沟通', 'effects': {'mood': 0, 'deskmate_relation': 15}},
                {'text': '先保持距离', 'effects': {'mood': -10, 'stress': 10, 'deskmate_relation': -10}}
            ],
            'condition': lambda p: p.deskmate_relation > 50 and random.random() > 0.85
        },
        {
            'id': 'deskmate_borrow',
            'category': '同桌',
            'title': '借东西',
            'description': '同桌忘带课本了，想和你一起看。',
            'choices': [
                {'text': '大方分享', 'effects': {'mood': 5, 'deskmate_relation': 10}},
                {'text': '有点不情愿但还是同意', 'effects': {'mood': 0, 'deskmate_relation': 5}},
                {'text': '让他/她自己想办法', 'effects': {'mood': -5, 'deskmate_relation': -10}}
            ],
            'condition': lambda p: random.random() > 0.8
        },
        {
            'id': 'deskmate_cheat',
            'category': '同桌',
            'title': '考试求助',
            'description': '小测验时，同桌悄悄向你示意，想看你的答案。',
            'choices': [
                {'text': '假装没看见', 'effects': {'mood': 0, 'deskmate_relation': -5}},
                {'text': '把卷子稍微挪过去', 'effects': {'mood': -5, 'stress': 15, 'deskmate_relation': 10, 'score': -3}},
                {'text': '考后主动帮他/她补习', 'effects': {'mood': 5, 'stress': 5, 'deskmate_relation': 15, 'score': 2}}
            ],
            'condition': lambda p: p.deskmate_relation > 60 and random.random() > 0.85
        },
        {
            'id': 'deskmate_move',
            'category': '同桌',
            'title': '换座位',
            'description': '班主任说要重新调整座位，你的同桌可能会换走。',
            'choices': [
                {'text': '请求老师让你们继续坐一起', 'effects': {'mood': 5, 'deskmate_relation': 20, 'teacher_relation': -5}},
                {'text': '接受安排，顺其自然', 'effects': {'mood': 0, 'deskmate_relation': -10}},
                {'text': '期待换个新同桌', 'effects': {'mood': -5, 'deskmate_relation': -20}}
            ],
            'condition': lambda p: p.month == 2 or p.month == 9 and random.random() > 0.7
        },
        {
            'id': 'deskmate_compete',
            'category': '同桌',
            'title': '同桌竞争',
            'description': '这次考试，你和同桌的分数咬得很紧，暗暗较着劲。',
            'choices': [
                {'text': '良性竞争，互相激励', 'effects': {'mood': 8, 'stress': 5, 'score': 5, 'deskmate_relation': 5}},
                {'text': '暗自憋劲赶超', 'effects': {'mood': 3, 'stress': 10, 'score': 6, 'deskmate_relation': -3}}
            ],
            'condition': lambda p: p.deskmate_relation > 40 and random.random() > 0.78
        },
        {
            'id': 'deskmate_sleep',
            'category': '同桌',
            'title': '同桌瞌睡',
            'description': '同桌上课打瞌睡，眼看老师就要走过来了。',
            'choices': [
                {'text': '悄悄提醒他/她', 'effects': {'mood': 5, 'deskmate_relation': 12}},
                {'text': '装作没看见', 'effects': {'mood': 0, 'deskmate_relation': -5}}
            ],
            'condition': lambda p: random.random() > 0.76
        },
        {
            'id': 'deskmate_secret',
            'category': '同桌',
            'title': '同桌的秘密',
            'description': '同桌悄悄告诉你一个心事，叮嘱你千万别说出去。',
            'choices': [
                {'text': '认真守护这份信任', 'effects': {'mood': 10, 'deskmate_relation': 18}},
                {'text': '感到有些为难', 'effects': {'mood': -3, 'stress': 5, 'deskmate_relation': 5}}
            ],
            'condition': lambda p: p.deskmate_relation > 55 and random.random() > 0.8
        }
    ],
    'crush': [
        {
            'id': 'crush_bookstore',
            'category': '偶遇',
            'title': '书店偶遇',
            'description': '周末去书店买参考书，你发现暗恋的那个同学也在，正在挑选一本小说。',
            'choices': [
                {'text': '假装偶遇，上前打招呼', 'effects': {'mood': 20, 'stress': 10}},
                {'text': '悄悄观察，不主动搭话', 'effects': {'mood': 10, 'stress': 5}},
                {'text': '赶紧躲开，怕被发现', 'effects': {'mood': -5, 'stress': 15}}
            ],
            'condition': lambda p: p.personality['introvert'] > 40 and random.random() > 0.85
        },
        {
            'id': 'crush_bus',
            'category': '偶遇',
            'title': '公交相遇',
            'description': '放学坐公交车，没想到暗恋的人就坐在你后面一排。',
            'choices': [
                {'text': '转身找话题聊天', 'effects': {'mood': 25, 'stress': 15}},
                {'text': '发微信/短信聊', 'effects': {'mood': 15, 'stress': 5}},
                {'text': '装作没发现，静静坐着', 'effects': {'mood': 5, 'stress': 10}}
            ],
            'condition': lambda p: p.personality['introvert'] < 70 and random.random() > 0.88
        },
        {
            'id': 'crush_milktea',
            'category': '偶遇',
            'title': '奶茶店邂逅',
            'description': '和同学去学校门口的奶茶店，暗恋的人正排队在你前面。',
            'choices': [
                {'text': '主动帮他/她付钱', 'effects': {'mood': 15, 'stress': 10, 'money': -15}},
                {'text': '打招呼然后各自买各自的', 'effects': {'mood': 10, 'stress': 5}},
                {'text': '假装没看见', 'effects': {'mood': -5, 'stress': 5}}
            ],
            'condition': lambda p: p.money > 50 and random.random() > 0.88
        },
        {
            'id': 'crush_rain',
            'category': '偶遇',
            'title': '雨天撑伞',
            'description': '放学突然下雨，你没带伞，在校门口遇到暗恋的同学，他/她有多余的一把。',
            'choices': [
                {'text': '接受好意，一起走一段', 'effects': {'mood': 30, 'stress': 10}},
                {'text': '借伞，下次还', 'effects': {'mood': 15, 'stress': 5}},
                {'text': '婉拒，冒雨跑回家', 'effects': {'mood': -10, 'health': -5}}
            ],
            'condition': lambda p: random.random() > 0.9
        },
        {
            'id': 'crush_library',
            'category': '偶遇',
            'title': '图书馆自习',
            'description': '周末在图书馆自习，暗恋的人正好坐在你对面。',
            'choices': [
                {'text': '传张纸条或小声打招呼', 'effects': {'mood': 15, 'stress': 10, 'score': -2}},
                {'text': '专注学习，但心情很好', 'effects': {'mood': 20, 'stress': 0, 'score': 5}},
                {'text': '坐立不安，无法集中', 'effects': {'mood': 10, 'stress': 15, 'score': -3}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.88
        },
        {
            'id': 'crush_supermarket',
            'category': '偶遇',
            'title': '超市购物',
            'description': '和家人逛超市时，偶遇暗恋的同学也在买东西。',
            'choices': [
                {'text': '大方介绍给家人认识', 'effects': {'mood': 20, 'stress': 15}},
                {'text': '简单打个招呼', 'effects': {'mood': 10, 'stress': 5}},
                {'text': '躲到另一排货架', 'effects': {'mood': -5, 'stress': 10}}
            ],
            'condition': lambda p: p.personality['introvert'] > 30 and random.random() > 0.9
        }
    ],
    'emotion': [
        {
            'id': 'emotion_confession',
            'category': '感情',
            'title': '收到表白',
            'description': '课后你的抽屉里出现了一封信，是一位同学鼓起勇气向你表白。',
            'choices': [
                {'text': '认真回应这份心意', 'effects': {'mood': 25, 'stress': 10, 'crush_relation': 20}},
                {'text': '婉拒，专注学业', 'effects': {'mood': -5, 'stress': 5, 'score': 3, 'crush_relation': -10}},
                {'text': '约定高考后再说', 'effects': {'mood': 10, 'stress': 5, 'crush_relation': 8}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.85
        },
        {
            'id': 'emotion_note',
            'category': '感情',
            'title': '传纸条的心动',
            'description': '上课时，你和心仪的同学偷偷传纸条聊天，心跳不自觉地加快。',
            'choices': [
                {'text': '继续聊，享受甜蜜', 'effects': {'mood': 20, 'stress': 5, 'score': -3}},
                {'text': '收起纸条专心听课', 'effects': {'mood': 5, 'score': 5}},
                {'text': '约下课后再聊', 'effects': {'mood': 15, 'stress': 5}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'emotion_study_together',
            'category': '感情',
            'title': '一起自习',
            'description': '晚自习时，喜欢的人坐到了你旁边，轻声问你能不能一起复习。',
            'choices': [
                {'text': '欣然答应，互相鼓励', 'effects': {'mood': 20, 'stress': -5, 'score': 5, 'crush_relation': 12}},
                {'text': '有些紧张但答应了', 'effects': {'mood': 15, 'stress': 10, 'crush_relation': 8}},
                {'text': '婉拒，怕分心', 'effects': {'mood': -5, 'stress': 5, 'score': 3, 'crush_relation': -5}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.85
        },
        {
            'id': 'emotion_teacher_talk',
            'category': '感情',
            'title': '老师的谈话',
            'description': '班主任找你谈话，委婉地提醒你不要因为"早恋"影响学习。',
            'choices': [
                {'text': '保证会处理好学习', 'effects': {'mood': -5, 'stress': 10, 'teacher_relation': 5}},
                {'text': '解释只是普通朋友', 'effects': {'mood': 0, 'stress': 5}},
                {'text': '感到委屈和烦躁', 'effects': {'mood': -15, 'stress': 15, 'teacher_relation': -5}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.88
        },
        {
            'id': 'emotion_breakup',
            'category': '感情',
            'title': '感情的烦恼',
            'description': '最近你和喜欢的人有些误会，对方好几天没理你，你心里很不是滋味。',
            'choices': [
                {'text': '主动沟通解开误会', 'effects': {'mood': 5, 'stress': 10, 'crush_relation': 10}},
                {'text': '把心思放回学习上', 'effects': {'mood': -5, 'stress': 5, 'score': 5, 'crush_relation': -8}},
                {'text': '一个人默默难过', 'effects': {'mood': -20, 'stress': 15, 'health': -5, 'crush_relation': -5}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.88
        },
        {
            'id': 'emotion_secret_like',
            'category': '感情',
            'title': '悄悄的心动',
            'description': '不知从什么时候起，你开始注意起某个人的一举一动。',
            'choices': [
                {'text': '把心动藏在心里', 'effects': {'mood': 10, 'stress': 5, 'crush_relation': 5}},
                {'text': '化作学习的动力', 'effects': {'mood': 8, 'stress': 3, 'score': 5, 'crush_relation': 3}}
            ],
            'condition': lambda p: random.random() > 0.82
        },
        {
            'id': 'emotion_gift',
            'category': '感情',
            'title': '匿名礼物',
            'description': '节日里，你的桌上多了一份没有署名的小礼物。',
            'choices': [
                {'text': '开心地收下', 'effects': {'mood': 18, 'stress': 5, 'crush_relation': 8}},
                {'text': '到处打听是谁送的', 'effects': {'mood': 10, 'stress': 8, 'crush_relation': 5}},
                {'text': '不动声色地放好', 'effects': {'mood': 8, 'stress': 3}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'emotion_walk_home',
            'category': '感情',
            'title': '一起回家',
            'description': '放学路上，喜欢的人正好和你顺路，要不要一起走？',
            'choices': [
                {'text': '主动同行聊天', 'effects': {'mood': 22, 'stress': 8, 'crush_relation': 14}},
                {'text': '默默跟着走一段', 'effects': {'mood': 12, 'stress': 5, 'crush_relation': 6}},
                {'text': '借口先走了', 'effects': {'mood': -3, 'stress': 5, 'crush_relation': -3}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'emotion_jealous',
            'category': '感情',
            'title': '小小的醋意',
            'description': '你看到喜欢的人和别的同学有说有笑，心里泛起一丝失落。',
            'choices': [
                {'text': '调整心态，专注自己', 'effects': {'mood': -5, 'stress': 5, 'score': 4}},
                {'text': '忍不住胡思乱想', 'effects': {'mood': -15, 'stress': 12, 'score': -3, 'crush_relation': -5}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.86
        },
        {
            'id': 'emotion_encourage',
            'category': '感情',
            'title': '一句鼓励',
            'description': '考试失利后，喜欢的人轻轻对你说了句"你已经很棒了"。',
            'choices': [
                {'text': '深受鼓舞，重燃斗志', 'effects': {'mood': 20, 'stress': -10, 'score': 4}},
                {'text': '害羞得说不出话', 'effects': {'mood': 15, 'stress': 5}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'admirer_lovenote',
            'category': '感情',
            'title': '抽屉里的情书',
            'description': '有位同学似乎一直在默默关注你，今天你在抽屉里发现了一封字迹娟秀的信。',
            'choices': [
                {'text': '认真读完，心生好感', 'effects': {'mood': 18, 'stress': 5, 'admirer_relation': 12}},
                {'text': '礼貌但保持距离', 'effects': {'mood': 5, 'stress': 3, 'admirer_relation': -8}},
                {'text': '假装没看到', 'effects': {'mood': -3, 'stress': 5, 'admirer_relation': -5}}
            ],
            'condition': lambda p: random.random() > 0.84
        },
        {
            'id': 'admirer_snack',
            'category': '感情',
            'title': '课桌上的零食',
            'description': '最近你的桌上总会无缘无故多出一些零食和小纸条，写着"加油哦"。',
            'choices': [
                {'text': '回赠一颗糖表示感谢', 'effects': {'mood': 15, 'admirer_relation': 14}},
                {'text': '当作普通同学的好意', 'effects': {'mood': 8, 'admirer_relation': 3}},
                {'text': '婉言请对方不要这样', 'effects': {'mood': -5, 'stress': 5, 'admirer_relation': -12}}
            ],
            'condition': lambda p: random.random() > 0.85
        },
        {
            'id': 'admirer_confess',
            'category': '感情',
            'title': '操场边的告白',
            'description': '放学后，那位一直关注你的同学红着脸把你叫到操场，认真地说出了喜欢你。',
            'choices': [
                {'text': '坦诚自己也有好感', 'effects': {'mood': 25, 'stress': 10, 'admirer_relation': 20}},
                {'text': '谢谢心意，但想先专注高考', 'effects': {'mood': 0, 'stress': 8, 'score': 4, 'admirer_relation': -5}},
                {'text': '明确拒绝', 'effects': {'mood': -8, 'stress': 10, 'admirer_relation': -25}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.86
        },
        {
            'id': 'admirer_help',
            'category': '感情',
            'title': '被默默帮助',
            'description': '你值日时，发现有人悄悄帮你把活干完了，还留了张"别太累"的便签。喜欢你的人又出现了。',
            'choices': [
                {'text': '主动找到对方道谢', 'effects': {'mood': 16, 'admirer_relation': 12}},
                {'text': '心里温暖，默默记下', 'effects': {'mood': 12, 'admirer_relation': 5}},
                {'text': '觉得有点负担', 'effects': {'mood': -3, 'stress': 5, 'admirer_relation': -6}}
            ],
            'condition': lambda p: random.random() > 0.86
        },
        {
            'id': 'admirer_triangle',
            'category': '感情',
            'title': '心动的抉择',
            'description': '你喜欢的人若即若离，而喜欢你的人却一直真诚以待。夜深时你问自己，心究竟在哪边。',
            'choices': [
                {'text': '勇敢追求自己喜欢的人', 'effects': {'mood': 5, 'stress': 12, 'crush_relation': 12, 'admirer_relation': -10}},
                {'text': '回应一直对你好的人', 'effects': {'mood': 12, 'stress': 5, 'admirer_relation': 15, 'crush_relation': -8}},
                {'text': '谁都不选，先拼高考', 'effects': {'mood': -5, 'stress': 8, 'score': 6, 'crush_relation': -3, 'admirer_relation': -3}}
            ],
            'condition': lambda p: p.grade >= 2 and random.random() > 0.88
        }
    ]
}

def get_random_event(player):
    # 0. 时间锚点里程碑事件优先：到点必触发，不被 AI 抽签替换
    for events in EVENTS.values():
        for event in events:
            if event['id'] not in MILESTONE_EVENT_IDS:
                continue
            if event['id'] in player.used_events:
                continue
            cond = event.get('condition')
            if cond is None or cond(player):
                return event

    # 维度覆盖保障：找出七个目标维度中“尚未经历过”的，本回合优先补齐，
    # 确保结局七维度报告每一项都有真实素材（解决“某些分类从不触发”的问题）。
    covered = {h.get('category') for h in getattr(player, 'history', [])}
    missing = [c for c in TARGET_CATEGORIES if c not in covered]
    force_category = random.choice(missing) if missing else None

    # 1. 按比例（默认 80%）优先尝试 AI 动态生成事件，其余走静态事件池。
    #    若本回合需要补齐某维度，则要求 AI 生成该维度事件。
    if is_ai_enabled() and random.random() < AI_EVENT_RATIO:
        ai_event = get_ai_event(player, force_category)
        if ai_event:
            return ai_event
        # AI 调用失败则继续降级到静态事件

    # 2. 静态事件池，排除已使用的
    available = []
    for category, events in EVENTS.items():
        for event in events:
            # 跳过已使用的一次性事件
            if event['id'] in player.used_events:
                continue
            # 检查条件
            if 'condition' not in event or event['condition'](player):
                available.append(event)

    if not available:
        return None

    # 需要补齐的维度优先：在可用池里挑该维度事件（不受家庭过滤影响，
    # 否则穷困家庭将永远无法触发“家庭”维度，导致报告缺项）。
    if force_category:
        forced_pool = [e for e in available if e['category'] == force_category]
        if forced_pool:
            return random.choice(forced_pool)

    # 根据家庭情况做风味过滤（仅在不影响维度补齐时应用）
    if player.family_type == '穷困':
        available = [e for e in available if e['category'] != '家庭']
    elif player.family_type == '单亲':
        available = [e for e in available if e['id'] != 'family_pressure']

    return random.choice(available) if available else None


def check_game_end(player):
    """检查游戏是否应该结束。

    - 高考：只有读到高三(grade==3)的6月才触发，是正常通关结局。
    - 退学(failure)：仅当连续多个月处于严重危机（健康极低或压力极高）时才触发，
      避免某一次事件把状态打到阈值就立刻“没到高三高中就结束”。
    """
    # 正常通关：高三6月参加高考
    if player.grade == 3 and player.month == 6:
        return 'gaokao'
    # 仅在严重且“持续”的危机下才退学：需连续 3 个月危机（见 advance 中维护的 danger_streak）
    if getattr(player, 'danger_streak', 0) >= 3:
        return 'failure'
    return None


# ==================== API 路由 ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start_game():
    data = request.json
    player = Player(data)

    session['player'] = player.__dict__
    session['current_event'] = None

    return jsonify({
        'success': True,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends,
            'history': player.history
        }
    })


@app.route('/api/status', methods=['GET'])
def get_status():
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    return jsonify({
        'success': True,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends,
            'history': player.history
        }
    })


@app.route('/api/advance', methods=['POST'])
def advance_game():
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    # 检查游戏结束条件
    end_reason = check_game_end(player)
    if end_reason == 'gaokao':
        return jsonify({
            'success': True,
            'gameState': {
                'player': player.to_dict(),
                'friends': player.friends,
                'history': player.history
            },
            'event': None,
            'ended': True,
            'endReason': 'gaokao'
        })
    elif end_reason == 'failure':
        return jsonify({
            'success': True,
            'gameState': {
                'player': player.to_dict(),
                'friends': player.friends,
                'history': player.history
            },
            'event': None,
            'ended': True,
            'endReason': 'failure'
        })

    # 获取或生成事件
    event = session.get('current_event')
    if not event:
        new_event = get_random_event(player)
        if new_event:
            event = {
                'id': new_event['id'],
                'category': new_event['category'],
                'title': new_event['title'],
                'description': new_event['description'],
                'choices': [{'text': c['text']} for c in new_event['choices']]
            }
            # AI 事件：完整保存选项效果，并标记来源（静态事件可从 EVENTS 查回）
            if new_event.get('is_ai'):
                event['is_ai'] = True
                event['effects_list'] = [c.get('effects', {}) for c in new_event['choices']]
            session['current_event'] = event

    # 时间信息
    month_names = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
    grade_names = ['', '高一', '高二', '高三']

    return jsonify({
        'success': True,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends,
            'history': player.history[-10:]
        },
        'event': event,
        'timeInfo': {
            'year': player.start_year + player.grade - 1,
            'month': month_names[player.month - 1],
            'gradeName': grade_names[player.grade]
        },
        'ended': False
    })


@app.route('/api/choose', methods=['POST'])
def make_choice():
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    data = request.json
    choice_index = data.get('choiceIndex', 0)

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    event = session.get('current_event')
    if not event:
        return jsonify({'error': '当前没有事件'}), 400

    # AI 事件：效果直接从 session 读取
    if event.get('is_ai'):
        effects_list = event.get('effects_list', [])
        if choice_index < 0 or choice_index >= len(effects_list):
            return jsonify({'error': '无效的选择'}), 400
        effects = effects_list[choice_index]
        choice_text = event['choices'][choice_index]['text']
    else:
        # 静态事件：从 EVENTS 查找原始事件
        original_event = None
        for events in EVENTS.values():
            for e in events:
                if e['id'] == event['id']:
                    original_event = e
                    break
            if original_event:
                break

        if not original_event or choice_index < 0 or choice_index >= len(original_event['choices']):
            return jsonify({'error': '无效的选择'}), 400

        choice = original_event['choices'][choice_index]
        effects = choice['effects']
        choice_text = choice['text']

    # 应用效果
    player.update_stats(effects)
    player.history.append({
        'grade': player.grade,
        'month': player.month,
        'event': event['title'],
        'choice': choice_text,
        'category': event.get('category', '日常')
    })

    # 记录已使用的事件（一次性事件不再重复）
    player.used_events.append(event['id'])

    # 清除事件
    session['current_event'] = None

    # 月末结算
    player.mood = min(100, player.mood + 2)
    player.stress = max(0, player.stress - 1)

    # 家庭影响
    if player.family_type == '完满':
        player.mood = min(100, player.mood + 2)
    elif player.family_type == '穷困':
        player.mood = max(0, player.mood - 1)
    elif player.family_type == '单亲':
        player.stress = min(100, player.stress + 1)

    # 危机连击维护：本月仍处于严重危机则累加，否则清零并给予轻微恢复
    # 这样只有“长期”陷入危机才会退学，而非一次事件打到阈值就提前结束
    if player.health <= 15 or player.stress >= 95:
        player.danger_streak = getattr(player, 'danger_streak', 0) + 1
    else:
        player.danger_streak = 0
        # 压力过高时自然回落一点，给玩家喘息，避免高三长期高压必然退学
        if player.stress >= 85:
            player.stress = max(0, player.stress - 3)
        if player.health <= 30:
            player.health = min(100, player.health + 3)

    # 推进月份
    player.month += 1
    if player.month > 12:
        player.month = 1

    session['player'] = player.__dict__

    return jsonify({
        'success': True,
        'effects': effects,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends,
            'history': player.history[-10:]
        },
        'gradeUp': player.month == 7 and player.grade < 3
    })


@app.route('/api/gradeup', methods=['POST'])
def grade_up():
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    player.grade += 1
    player.month = 9

    # 成绩提升
    for key in player.subjects:
        player.subjects[key] = min(150, player.subjects[key] + 5)

    session['player'] = player.__dict__

    return jsonify({
        'success': True,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends,
            'history': player.history[-10:]
        }
    })


@app.route('/api/gaokao', methods=['POST'])
def gaokao_result():
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    # 计算高考成绩
    base_score = 0
    if player.subject_preference == '理科':
        base_score = (player.subjects['chinese'] + player.subjects['math'] +
                     player.subjects['english'] + player.subjects['physics'] +
                     player.subjects['chemistry'] + player.subjects['biology'])
    elif player.subject_preference == '文科':
        base_score = (player.subjects['chinese'] + player.subjects['math'] +
                     player.subjects['english'] + player.subjects['history'] +
                     player.subjects['geography'] + player.subjects['politics'])
    else:
        base_score = (player.subjects['chinese'] + player.subjects['math'] + player.subjects['english'])

    # 随机因子和状态影响
    random_factor = 0.9 + random.random() * 0.2
    stress_factor = 1 - (player.stress - 50) / 200
    health_factor = 1 + (player.health - 50) / 200

    final_score = round(base_score * random_factor * stress_factor * health_factor)

    # 记录
    player.history.append({
        'grade': player.grade,
        'month': 6,
        'event': '高考',
        'choice': '参加考试',
        'category': '学业',
        'score': final_score
    })

    # 评价和大学推荐
    if final_score >= 650:
        evaluation = '🎉 恭喜！你的成绩非常优秀，可以冲击顶尖名校！'
        college_tier = '顶尖985'
    elif final_score >= 550:
        evaluation = '👏 成绩不错！重点大学有望，继续努力！'
        college_tier = '211/普通985'
    elif final_score >= 450:
        evaluation = '💪 成绩中等，可以选择一所不错的本科院校。'
        college_tier = '一本/二本'
    elif final_score >= 350:
        evaluation = '📚 成绩需要提高，考虑选择适合的专科或二本院校。'
        college_tier = '二本/专科'
    else:
        evaluation = '😢 成绩不太理想，但不要灰心，未来还有很多可能！'
        college_tier = '专科/复读'

    # 存高考分数供志愿填报与报告复用
    session['gaokao_score'] = final_score
    session['player'] = player.__dict__

    return jsonify({
        'success': True,
        'score': final_score,
        'estimatedScore': player.calculate_average_score(),
        'evaluation': evaluation,
        'collegeTier': college_tier,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends,
            'history': player.history[-10:]
        }
    })


@app.route('/api/graduation', methods=['POST'])
def graduation_prom():
    """毕业晚会：向喜欢的人表白、和朋友告别、回应喜欢你的人。
    每个动作仅可进行一次，结果写入 history 供志愿/报告引用。"""
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    data = request.json or {}
    action = data.get('action')

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    done = session.get('graduation', [])
    if action in done:
        return jsonify({'error': '该环节已经完成', 'done': done}), 400

    result = None
    message = ''
    effects_text = ''

    if action == 'confess':
        crush = getattr(player, 'crush', None)
        if not isinstance(crush, dict):
            return jsonify({'error': '没有可表白的对象'}), 400
        rel = crush.get('relation', 0)
        prob = max(0.05, min(0.95, (rel - 30) / 55.0))
        success = random.random() < prob
        if success:
            crush['confessed'] = True
            crush['relation'] = min(100, rel + 15)
            player.update_stats({'mood': 18, 'stress': -8})
            result = 'success'
            message = f'💞 在晚会的灯光下，你鼓起勇气向「{crush["name"]}」表白，TA红着脸点了头。你们约定要去同一座城市！'
            effects_text = '心情 +18，压力 -8'
        else:
            crush['relation'] = min(100, rel + 3)
            player.update_stats({'mood': -10, 'stress': 4})
            result = 'fail'
            message = f'🥺 你向「{crush["name"]}」说出了藏了三年的心事，TA愣了一下，最终给了你一个温柔的拥抱：「我们还是做朋友吧。」'
            effects_text = '心情 -10，压力 +4'
        player.history.append({
            'grade': player.grade, 'month': 6,
            'event': '毕业晚会·表白',
            'choice': f'向{crush["name"]}表白（{"成功" if success else "婉拒"}）',
            'category': '感情'
        })

    elif action == 'farewell':
        friends = getattr(player, 'friends', []) or []
        for f in friends:
            f['relation'] = min(100, f.get('relation', 0) + 5)
        player.update_stats({'mood': 12, 'stress': -6})
        result = 'done'
        if friends:
            names = '、'.join(f.get('name', '') for f in friends)
            message = f'🥹 你和「{names}」围坐在一起，约定常联系。三年的同窗情谊，化作离别时一个用力的拥抱。'
        else:
            message = '🌙 晚会上你独自走到操场，看着熟悉的教学楼，把这三年默默收进心里。'
        effects_text = '心情 +12，压力 -6'
        player.history.append({
            'grade': player.grade, 'month': 6,
            'event': '毕业晚会·告别',
            'choice': '和朋友们郑重告别',
            'category': '社交'
        })

    elif action == 'respond_admirer':
        admirer = getattr(player, 'admirer', None)
        if not isinstance(admirer, dict):
            return jsonify({'error': '没有可回应的对象'}), 400
        admirer['accepted'] = True
        admirer['relation'] = min(100, admirer.get('relation', 0) + 15)
        player.update_stats({'mood': 15, 'stress': -6})
        result = 'accepted'
        message = f'💗 晚会角落，「{admirer["name"]}」终于把心意说出口。这一次，你认真地回应了这份双向奔赴。'
        effects_text = '心情 +15，压力 -6'
        player.history.append({
            'grade': player.grade, 'month': 6,
            'event': '毕业晚会·回应',
            'choice': f'接受{admirer["name"]}的心意',
            'category': '感情'
        })

    else:
        return jsonify({'error': '未知动作'}), 400

    done.append(action)
    session['graduation'] = done
    session['player'] = player.__dict__

    return jsonify({
        'success': True,
        'action': action,
        'result': result,
        'message': message,
        'effectsText': effects_text,
        'done': done,
        'gameState': {
            'player': player.to_dict(),
            'friends': player.friends
        }
    })


@app.route('/api/restart', methods=['POST'])
def restart_game():
    session.clear()
    return jsonify({'success': True})


# 院校档次分数线（录取判定基准）
TIER_BASELINE = {
    '清北': 680,
    'C9': 650,
    '985': 620,
    '211': 560,
    '一本': 500,
    '二本': 420,
    '专科': 320,
}

# 专业方向与文理/兴趣的契合关键词
MAJOR_KEYWORDS = {
    '理工科': {'pref': '理科', 'interests': ['数学', '物理', '编程', '科技', '化学', '生物']},
    '医学': {'pref': '理科', 'interests': ['生物', '化学']},
    '经管财经': {'pref': '文科', 'interests': ['数学', '阅读']},
    '文史哲': {'pref': '文科', 'interests': ['阅读', '写作', '历史', '音乐']},
    '艺术传媒': {'pref': '文科', 'interests': ['音乐', '美术', '绘画', '写作']},
    '师范教育': {'pref': '文科', 'interests': ['阅读', '写作']},
}


def _parent_advice(player):
    """根据家庭类型生成家长倾向"""
    ft = player.family_type
    if ft == '穷困':
        return {'tier': '211', 'major': '经管财经', 'text': '家里希望你选稳妥、好就业的专业。'}
    if ft == '完满':
        return {'tier': '985', 'major': '理工科', 'text': '父母支持你冲击更好的学校。'}
    if ft == '单亲':
        return {'tier': '一本', 'major': '师范教育', 'text': '家长希望你选离家近、稳定的方向。'}
    return {'tier': '一本', 'major': '理工科', 'text': '父母尊重你的选择，建议求稳。'}


def _teacher_advice(player):
    """老师关系越好，越鼓励冲高"""
    rel = getattr(player, 'teacher_relation', 60)
    if rel >= 75:
        return {'aggressive': True, 'text': '班主任很看好你，鼓励你大胆冲一冲。'}
    if rel <= 40:
        return {'aggressive': False, 'text': '老师建议你稳妥填报，不要冒险。'}
    return {'aggressive': None, 'text': '老师建议你结合自身情况理性填报。'}


@app.route('/api/apply', methods=['POST'])
def apply_college():
    """志愿填报：综合分数、兴趣、家长/老师建议、同学影响、情感状态判定录取"""
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    data = request.json or {}
    school_tier = data.get('school_tier', '一本')
    major = data.get('major', '理工科')
    love_city = bool(data.get('love_city', False))  # 是否"为爱奔赴同一城市"

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    score = session.get('gaokao_score')
    if score is None:
        return jsonify({'error': '请先完成高考'}), 400

    baseline = TIER_BASELINE.get(school_tier, 500)
    analysis = []

    # 1. 分数 vs 档次：基准概率
    gap = score - baseline
    prob = 0.6 + gap / 100.0  # 每高/低于线 10 分，概率 ±0.1
    if gap >= 20:
        analysis.append(f'📈 你的 {score} 分高出「{school_tier}」线 {gap} 分，把握很大。')
    elif gap >= 0:
        analysis.append(f'📊 你的 {score} 分刚好够到「{school_tier}」线，属于稳妥范围。')
    else:
        analysis.append(f'⚠️ 你的 {score} 分低于「{school_tier}」线 {-gap} 分，属于冲高。')

    # 2. 兴趣/文理契合
    spec = MAJOR_KEYWORDS.get(major, {})
    interests = getattr(player, 'interests', []) or []
    fit_interest = any(kw in interests for kw in spec.get('interests', []))
    fit_pref = spec.get('pref') == getattr(player, 'subject_preference', '理科')
    if fit_interest:
        prob += 0.08
        analysis.append(f'💡 「{major}」与你的兴趣（{("、".join(interests)) or "无"}）契合，志愿动机充分。')
    if fit_pref:
        prob += 0.05
        analysis.append(f'📚 「{major}」匹配你的{getattr(player, "subject_preference", "理科")}背景。')
    elif not fit_interest:
        prob -= 0.05
        analysis.append(f'🤔 「{major}」与你的兴趣和文理偏好关联不大，需谨慎。')

    # 3. 家长建议
    pa = _parent_advice(player)
    if pa['tier'] == school_tier or pa['major'] == major:
        prob += 0.05
        analysis.append(f'👪 {pa["text"]}你的选择与家长期望一致。')
    else:
        prob -= 0.03
        analysis.append(f'👪 {pa["text"]}你的选择与家长期望略有出入。')

    # 4. 老师建议
    ta = _teacher_advice(player)
    aggressive_choice = school_tier in ('清北', 'C9', '985')
    if ta['aggressive'] is True and aggressive_choice:
        prob += 0.06
        analysis.append(f'👨‍🏫 {ta["text"]}你顺势冲高，信心加成。')
    elif ta['aggressive'] is False and not aggressive_choice:
        prob += 0.04
        analysis.append(f'👨‍🏫 {ta["text"]}你选择求稳，与老师一致。')
    else:
        analysis.append(f'👨‍🏫 {ta["text"]}')

    # 5. 同学影响
    friends = getattr(player, 'friends', []) or []
    if friends:
        avg = sum(f.get('relation', 0) for f in friends) / len(friends)
        if avg >= 75:
            prob += 0.04
            analysis.append(f'🧑‍🤝‍🧑 好友们关系融洽（均值 {round(avg)}），互相鼓劲让你更从容。')
        elif avg <= 45:
            prob -= 0.03
            analysis.append(f'🧑‍🤝‍🧑 与同学关系较淡（均值 {round(avg)}），少了些临场支持。')

    # 6. 情感状态：你喜欢的人 + 喜欢你的人 两条线
    crush = getattr(player, 'crush', None)
    admirer = getattr(player, 'admirer', None)
    if love_city:
        # “为爱同城”优先看感情更深的一方
        crel = crush.get('relation', 0) if crush else 0
        arel = admirer.get('relation', 0) if admirer else 0
        if crel >= arel and crush and crel >= 60:
            prob += 0.05
            analysis.append(f'💕 为了和你喜欢的「{crush["name"]}」去同一座城市，你动力十足（心动值 {crel}）。')
        elif arel > crel and admirer and arel >= 60:
            prob += 0.05
            analysis.append(f'💗 喜欢你的「{admirer["name"]}」与你约定同城，这份双向奔赴给了你底气（好感 {arel}）。')
        else:
            best_name = crush["name"] if (crush and crel >= arel) else (admirer["name"] if admirer else '某人')
            prob -= 0.06
            analysis.append(f'💔 你想为「{best_name}」改志愿，但感情尚浅，略显冲动。')
    else:
        if crush and crush.get('relation', 0) >= 70:
            analysis.append(f'💕 你和喜欢的「{crush["name"]}」感情很好，但你把志愿放在了首位。')
        if admirer and admirer.get('relation', 0) >= 70:
            analysis.append(f'💗 喜欢你的「{admirer["name"]}」默默支持着你的选择。')

    # 概率裁剪与录取判定
    prob = max(0.05, min(0.95, prob))
    admitted = random.random() < prob

    school_name = f'{school_tier}院校'
    if admitted:
        message = f'🎉 恭喜！你被一所「{school_tier}」的{major}专业录取了！'
        choice_text = f'报考 {school_tier} · {major}（录取）'
    else:
        message = f'😢 很遗憾，你与「{school_tier}」失之交臂，可考虑征集志愿或复读。'
        choice_text = f'报考 {school_tier} · {major}（滑档）'

    # 写入 history 并存 session 供报告引用
    player.history.append({
        'grade': player.grade,
        'month': 6,
        'event': '志愿填报',
        'choice': choice_text,
        'category': '校园'
    })
    session['admission'] = {
        'admitted': admitted,
        'tier': school_tier,
        'major': major,
        'school': school_name
    }
    session['player'] = player.__dict__

    return jsonify({
        'success': True,
        'admitted': admitted,
        'school': school_name,
        'tier': school_tier,
        'major': major,
        'probability': round(prob, 2),
        'analysis': analysis,
        'message': message,
        'parentAdvice': pa['text'],
        'teacherAdvice': ta['text']
    })


@app.route('/api/report', methods=['POST'])
def behavior_report():
    """从七个维度生成玩家行为总结报告（纯 AI 生成，无 key 时返回 available:false）"""
    if 'player' not in session:
        return jsonify({'error': '没有游戏会话'}), 404

    player_data = session['player']
    player = Player.__new__(Player)
    player.__dict__.update(player_data)

    report = get_ai_report(player)
    if not report:
        return jsonify({
            'success': True,
            'available': False,
            'message': '行为总结报告由 AI 生成，请在 .env 中配置可用的 DEEPSEEK_API_KEY 后重试。'
        })

    return jsonify({
        'success': True,
        'available': True,
        'report': report
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)