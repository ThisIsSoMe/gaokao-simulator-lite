"""
DeepSeek API 客户端
用于动态生成高考模拟器的事件内容（标题、描述、选项、效果）。
读取失败或未启用时返回 None，由调用方降级到静态事件。
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# 有效的事件分类（含用户新增的"感情"）
VALID_CATEGORIES = ['学业', '社交', '家庭', '日常', '校园', '同桌', '感情']

# 各效果字段的合法取值范围（与 app.py 中 update_stats 的语义一致）
EFFECT_RANGES = {
    'mood': (-30, 30),
    'stress': (-30, 30),
    'health': (-30, 30),
    'score': (-15, 15),
    'money': (-1000, 1000),
    'deskmate_relation': (-30, 30),
    'teacher_relation': (-30, 30),
    'crush_relation': (-30, 30),
    'admirer_relation': (-30, 30),
    'friend_relation': (-30, 30),
    'family_relation': (-20, 20),
}

GRADE_NAMES = {1: '高一', 2: '高二', 3: '高三'}

SYSTEM_PROMPT = """你是中国高考模拟游戏的剧情生成器。根据玩家当前状态，生成一个贴合情境、有代入感的校园生活事件。

要求：
1. 事件要符合中国高中生的真实生活，语言生动自然。
2. 根据玩家的年级、月份、心情、压力、家庭情况、兴趣、同桌关系等定制内容。
3. 提供 2~3 个有意义且各有取舍的选项，选项后果（effects）要合理。
4. 只输出 JSON，不要任何额外文字或 markdown 代码块标记。

## 输出格式（严格 JSON）
{
    "id": "ai_generated_xxx",
    "category": "学业|社交|家庭|日常|校园|同桌|感情",
    "title": "事件标题（不超过15字）",
    "description": "事件描述（30~80字，第二人称）",
    "choices": [
        {"text": "选项文本", "effects": {"mood": 10, "stress": -5}}
    ]
}

## effects 可用字段及取值范围（整数）
- mood 心情: -30~30
- stress 压力: -30~30
- health 健康: -30~30
- score 成绩: -15~15
- money 零花钱: -1000~1000
- deskmate_relation 同桌关系: -30~30
- teacher_relation 师生关系: -30~30
- crush_relation 与「你喜欢的人」的亲密度: -30~30
- admirer_relation 与「喜欢你的人」的亲密度: -30~30
- friend_relation 与朋友的亲密度: -30~30
- family_relation 与家人的亲密度: -20~20
每个选项的 effects 只需包含相关字段，无需全部填写。

## 关于「感情」分类
感情线有两个对象：一个是「你喜欢的人」（你主动暗恋，对应 crush_relation），一个是「喜欢你的人」（对方主动对你示好，对应 admirer_relation）。
生成感情类事件时，请围绕其中一方展开，并在对应选项里给出 crush_relation 或 admirer_relation 的变化。"""


REPORT_CATEGORIES = ['学业', '社交', '家庭', '日常', '校园', '同桌', '感情']

REPORT_SYSTEM_PROMPT = """你是中国高考模拟游戏的结局点评师。玩家走完了高中三年，请你根据其经历，从七个维度总结这位玩家的行为风格与成长轨迹。

要求：
1. 逐一点评这七个维度：学业、社交、家庭、日常、校园、同桌、感情。
2. 语言温暖、有洞察力，像一位了解学生的班主任在写评语。每个维度结合玩家在该维度的实际选择来点评；若该维度没有经历，则给出鼓励性的中性评语。
3. 给出一段总体评语（summary，60~120字）。
4. 每个维度给一个简短标签（tag，4字以内，如"稳扎稳打""重情重义"）。
5. 只输出 JSON，不要任何额外文字或 markdown 代码块标记。

## 输出格式（严格 JSON）
{
    "summary": "总体评语",
    "categories": [
        {"name": "学业", "tag": "标签", "comment": "该维度点评（30~60字）"},
        {"name": "社交", "tag": "标签", "comment": "..."},
        {"name": "家庭", "tag": "标签", "comment": "..."},
        {"name": "日常", "tag": "标签", "comment": "..."},
        {"name": "校园", "tag": "标签", "comment": "..."},
        {"name": "同桌", "tag": "标签", "comment": "..."},
        {"name": "感情", "tag": "标签", "comment": "..."}
    ]
}
categories 必须按上述七个维度的顺序，且恰好包含这七项。"""


def _build_user_prompt(player, force_category=None):
    """根据玩家状态构建用户 prompt；force_category 指定时要求生成该分类事件"""
    grade_name = GRADE_NAMES.get(getattr(player, 'grade', 1), '高一')
    personality = getattr(player, 'personality', {}) or {}
    introvert = personality.get('introvert', 50)
    introvert_desc = '内向' if introvert > 60 else ('外向' if introvert < 40 else '中立')
    interests = getattr(player, 'interests', []) or []

    category_req = ''
    if force_category:
        category_req = (
            f"\n## 本次特别要求\n"
            f"- 事件分类（category）必须是「{force_category}」，请紧扣该主题设计情节与选项。\n"
        )
        if force_category == '感情':
            crush = getattr(player, 'crush', None) or {}
            admirer = getattr(player, 'admirer', None) or {}
            category_req += (
                f"- 你喜欢的人：{crush.get('name', '某人')}（你的心动值 {crush.get('relation', 0)}，用 crush_relation 调整）\n"
                f"- 喜欢你的人：{admirer.get('name', '某人')}（TA 对你的好感 {admirer.get('relation', 0)}，用 admirer_relation 调整）\n"
                f"- 请围绕其中一方设计剧情，并在选项里给出对应的 crush_relation 或 admirer_relation 变化。\n"
            )

    return f"""## 玩家当前状态
- 姓名: {getattr(player, 'name', '玩家')}（{getattr(player, 'gender', '男')}）
- 年级: {grade_name}
- 月份: {getattr(player, 'month', 9)}月
- 入学年份: {getattr(player, 'start_year', 2020)}
- 家庭类型: {getattr(player, 'family_type', '普通')}
- 心情: {getattr(player, 'mood', 80)} / 压力: {getattr(player, 'stress', 30)} / 健康: {getattr(player, 'health', 90)}
- 性格倾向: {introvert_desc}
- 文理偏好: {getattr(player, 'subject_preference', '理科')}
- 兴趣: {('、'.join(interests)) if interests else '无'}
- 同桌关系: {getattr(player, 'deskmate_relation', 70)} / 师生关系: {getattr(player, 'teacher_relation', 60)}
{category_req}
请生成一个与上述状态契合的事件，严格按系统要求的 JSON 格式输出。"""


def _clamp_effects(effects):
    """将效果值修正到合法范围，过滤未知字段"""
    cleaned = {}
    for key, value in effects.items():
        if key not in EFFECT_RANGES:
            continue
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        low, high = EFFECT_RANGES[key]
        cleaned[key] = max(low, min(high, value))
    return cleaned


def _validate_event(data, force_category=None):
    """校验并规整 AI 返回的事件数据，非法返回 None。
    force_category 指定时，强制覆盖 category 为该值（保证维度覆盖需求）。"""
    if not isinstance(data, dict):
        return None
    title = data.get('title')
    description = data.get('description')
    choices = data.get('choices')
    if not title or not description or not isinstance(choices, list) or not choices:
        return None

    if force_category in VALID_CATEGORIES:
        category = force_category
    else:
        category = data.get('category')
        if category not in VALID_CATEGORIES:
            category = '日常'

    valid_choices = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        text = choice.get('text')
        if not text:
            continue
        effects = choice.get('effects')
        effects = _clamp_effects(effects) if isinstance(effects, dict) else {}
        valid_choices.append({'text': str(text), 'effects': effects})

    if not valid_choices:
        return None

    event_id = data.get('id') or 'ai_generated'
    if not str(event_id).startswith('ai_'):
        event_id = f'ai_{event_id}'

    return {
        'id': str(event_id),
        'category': category,
        'title': str(title),
        'description': str(description),
        'choices': valid_choices,
        'is_ai': True,
    }


def _build_report_prompt(player):
    """根据玩家终局状态 + 按 category 聚合的 history 构建报告 prompt"""
    grade_name = GRADE_NAMES.get(getattr(player, 'grade', 3), '高三')
    history = getattr(player, 'history', []) or []

    # 按维度聚合玩家的选择
    by_cat = {cat: [] for cat in REPORT_CATEGORIES}
    for h in history:
        cat = h.get('category')
        if cat in by_cat:
            by_cat[cat].append(f"{h.get('event', '')}→{h.get('choice', '')}")

    lines = []
    for cat in REPORT_CATEGORIES:
        items = by_cat[cat]
        if items:
            lines.append(f"- {cat}：" + '；'.join(items[:8]))
        else:
            lines.append(f"- {cat}：（无相关经历）")
    history_text = '\n'.join(lines)

    crush = getattr(player, 'crush', None) or {}
    admirer = getattr(player, 'admirer', None) or {}
    family = getattr(player, 'family', []) or []
    family_text = '、'.join(f"{m.get('role')}({m.get('relation')})" for m in family) or '无'
    friends = getattr(player, 'friends', []) or []
    friends_text = '、'.join(f"{f.get('name')}({f.get('relation')})" for f in friends) or '无'

    return f"""## 玩家终局状态
- 姓名: {getattr(player, 'name', '玩家')}（{getattr(player, 'gender', '男')}）
- 年级: {grade_name}
- 文理偏好: {getattr(player, 'subject_preference', '理科')}
- 兴趣: {('、'.join(getattr(player, 'interests', []) or [])) or '无'}
- 家庭类型: {getattr(player, 'family_type', '普通')}
- 心情: {getattr(player, 'mood', 80)} / 压力: {getattr(player, 'stress', 30)} / 健康: {getattr(player, 'health', 90)}
- 同桌关系: {getattr(player, 'deskmate_relation', 70)} / 师生关系: {getattr(player, 'teacher_relation', 60)}
- 你喜欢的人: {crush.get('name', '无')}（心动值 {crush.get('relation', 0)}）
- 喜欢你的人: {admirer.get('name', '无')}（TA 的好感 {admirer.get('relation', 0)}）
- 家人亲密度: {family_text}
- 朋友亲密度: {friends_text}

## 玩家三年间各维度的经历与选择
{history_text}

请基于以上信息，严格按系统要求的 JSON 格式输出七维度行为总结报告。其中「感情」维度请结合「你喜欢的人」和「喜欢你的人」两条线综合点评。"""


def _validate_report(data):
    """校验并规整 AI 返回的报告数据，非法返回 None"""
    if not isinstance(data, dict):
        return None
    summary = data.get('summary')
    categories = data.get('categories')
    if not summary or not isinstance(categories, list):
        return None

    # 以维度名建索引，保证七项齐全且有序
    by_name = {}
    for c in categories:
        if isinstance(c, dict) and c.get('name') in REPORT_CATEGORIES:
            by_name[c['name']] = c

    result_cats = []
    for cat in REPORT_CATEGORIES:
        c = by_name.get(cat)
        if c and c.get('comment'):
            result_cats.append({
                'name': cat,
                'tag': str(c.get('tag') or ''),
                'comment': str(c['comment'])
            })
        else:
            result_cats.append({'name': cat, 'tag': '', 'comment': '这段经历着墨不多，未来仍有无限可能。'})

    return {'summary': str(summary), 'categories': result_cats}


class DeepSeekClient:
    def __init__(self):
        self.api_key = os.getenv('DEEPSEEK_API_KEY')
        self.base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
        self.model = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
        self.enabled = os.getenv('DEEPSEEK_ENABLED', 'true').lower() == 'true'
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def is_enabled(self):
        """启用且配置了 API Key 才视为可用"""
        return self.enabled and bool(self.api_key)

    def generate_event(self, player, force_category=None):
        """调用 DeepSeek 生成事件，失败返回 None。
        force_category 指定时，要求并强制事件分类为该值。"""
        if not self.is_enabled():
            return None
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': _build_user_prompt(player, force_category)},
                ],
                response_format={'type': 'json_object'},
                temperature=1.2,
                timeout=15,
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            event = _validate_event(data, force_category)
            if event is None:
                logger.warning('DeepSeek 返回的事件格式无效，降级到静态事件')
            return event
        except json.JSONDecodeError as exc:
            logger.warning('DeepSeek 响应 JSON 解析失败: %s', exc)
            return None
        except Exception as exc:
            logger.warning('DeepSeek API 调用失败: %s', exc)
            return None

    def generate_report(self, player):
        """调用 DeepSeek 生成七维度行为报告，失败返回 None"""
        if not self.is_enabled():
            return None
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': REPORT_SYSTEM_PROMPT},
                    {'role': 'user', 'content': _build_report_prompt(player)},
                ],
                response_format={'type': 'json_object'},
                temperature=0.9,
                timeout=20,
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            report = _validate_report(data)
            if report is None:
                logger.warning('DeepSeek 返回的报告格式无效')
            return report
        except json.JSONDecodeError as exc:
            logger.warning('DeepSeek 报告 JSON 解析失败: %s', exc)
            return None
        except Exception as exc:
            logger.warning('DeepSeek 报告调用失败: %s', exc)
            return None


# 模块级单例
_client_instance = None


def _get_instance():
    global _client_instance
    if _client_instance is None:
        _client_instance = DeepSeekClient()
    return _client_instance


def get_ai_event(player, force_category=None):
    """公共接口：生成一个 AI 事件，失败返回 None。
    force_category 指定时，强制该事件的分类。"""
    return _get_instance().generate_event(player, force_category)


def is_ai_enabled():
    """公共接口：AI 事件生成是否可用"""
    return _get_instance().is_enabled()


def get_ai_report(player):
    """公共接口：生成七维度行为总结报告，失败返回 None"""
    return _get_instance().generate_report(player)
