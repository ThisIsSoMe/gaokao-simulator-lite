// 高考模拟器 - 前端逻辑

// 状态管理
let gameState = null;
let currentEvent = null;

// DOM 元素
const coverScreen = document.getElementById('cover-screen');
const timemachineScreen = document.getElementById('timemachine-screen');
const createScreen = document.getElementById('create-screen');
const gameScreen = document.getElementById('game-screen');
const endScreen = document.getElementById('end-screen');
const whiteFlash = document.getElementById('white-flash');

// ==================== UI 交互 ====================

// 滑块值显示更新
document.querySelectorAll('.slider').forEach(slider => {
  const valueId = slider.id + '-value';
  const valueEl = document.getElementById(valueId);
  if (valueEl) {
    slider.addEventListener('input', () => {
      valueEl.textContent = slider.value;
    });
  }
});

// 文理科选择
function selectSubject(card, value) {
  document.querySelectorAll('.subject-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
}

// 家庭情况选择
function selectFamily(card, value) {
  document.querySelectorAll('.family-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
}

// 兴趣标签选择
document.querySelectorAll('.interest-tag input').forEach(checkbox => {
  checkbox.addEventListener('change', () => {
    checkbox.closest('.interest-tag').classList.toggle('selected', checkbox.checked);
  });
});

// ==================== 封面与时光机 ====================

// 从封面进入创建角色
function showCreateScreen() {
  coverScreen.classList.add('hidden');
  createScreen.classList.remove('hidden');
}

// 获取年代名称
function getEraName(year) {
  if (year >= 2020) return '新冠时代';
  if (year >= 2018) return '互联网爆发';
  if (year >= 2015) return '移动互联网时代';
  if (year >= 2010) return '智能手机元年';
  if (year >= 2008) return '奥运之年';
  if (year >= 2005) return 'MP3时代';
  return '千禧之年';
}

// 时光机动画序列
async function showTimemachineSequence(startYear) {
  // 显示时光机界面
  createScreen.classList.add('hidden');
  timemachineScreen.classList.remove('hidden');

  const timemachine = document.querySelector('.timemachine');
  const timemachineText = document.getElementById('timemachine-text');
  const eraName = getEraName(startYear);

  // 阶段1: 启动时光机
  await delay(800);
  timemachineText.textContent = '时光机启动中...';

  // 阶段2: 门打开
  await delay(1000);
  timemachine.classList.add('doors-open');
  timemachineText.textContent = '时空隧道开启...';

  // 阶段3: 白光穿越
  await delay(1500);
  whiteFlash.classList.remove('hidden');
  whiteFlash.classList.add('active');
  document.getElementById('flash-text').textContent = `正在穿越到${eraName}...`;

  // 阶段4: 到达
  await delay(2000);
  whiteFlash.classList.remove('active');
  whiteFlash.classList.add('hidden');
  timemachineScreen.classList.add('hidden');
  gameScreen.classList.remove('hidden');
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ==================== 游戏逻辑 ====================

// 创建角色
document.getElementById('create-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  // 收集表单数据
  const genderInput = document.querySelector('input[name="gender"]:checked');
  const subjectInput = document.querySelector('input[name="subjectPreference"]:checked');
  const familyInput = document.querySelector('input[name="familyType"]:checked');

  const interests = [];
  document.querySelectorAll('input[name="interest"]:checked').forEach(cb => {
    interests.push(cb.value);
  });

  const config = {
    name: document.getElementById('name').value || '张三',
    gender: genderInput ? genderInput.value : '男',
    province: document.getElementById('province').value,
    start_year: parseInt(document.getElementById('startYear').value),
    learning_ability: parseInt(document.getElementById('learningAbility').value),
    initial_score: parseInt(document.getElementById('initialScore').value),
    stress_resistance: parseInt(document.getElementById('stressResistance').value),
    introvert: parseInt(document.getElementById('introvert').value),
    rational: parseInt(document.getElementById('rational').value),
    subject_preference: subjectInput ? subjectInput.value : '理科',
    interests: interests,
    initial_friends: parseInt(document.getElementById('initialFriends').value),
    family_type: familyInput ? familyInput.value : '普通'
  };

  try {
    const response = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });

    const data = await response.json();

    if (data.success) {
      gameState = data.gameState;

      // 触发时光机动画序列
      const startYear = config.start_year;
      await showTimemachineSequence(startYear);

      // 更新UI（包括年代标签）
      updateGameUI();
      advanceGame();
    } else {
      showToast('创建角色失败', 'negative');
    }
  } catch (error) {
    console.error('创建角色失败:', error);
    showToast('网络错误，请重试', 'negative');
  }
});

// 推进游戏
async function advanceGame() {
  hideEvent();
  showLoading();

  try {
    const response = await fetch('/api/advance', {
      method: 'POST'
    });

    const data = await response.json();

    if (data.success) {
      gameState = data.gameState;

      // 更新时间显示
      if (data.timeInfo) {
        updateTimeDisplay(data.timeInfo);
      }

      // 更新状态
      updateGameUI();

      // 显示事件或结束
      if (data.event) {
        showEvent(data.event);
      } else if (data.ended) {
        showEndScreen(data.endReason);
      } else {
        // 没有事件，继续推进
        setTimeout(advanceGame, 300);
      }
    }
  } catch (error) {
    console.error('推进游戏失败:', error);
  } finally {
    hideLoading();
  }
}

// 更新游戏UI
function updateGameUI() {
  if (!gameState || !gameState.player) return;

  const p = gameState.player;

  // 玩家头像
  document.getElementById('player-avatar-emoji').textContent = p.gender === '女' ? '👩‍🎓' : '👨‍🎓';

  // 玩家信息
  document.getElementById('player-name').textContent = p.name;
  document.getElementById('player-school').textContent = `${p.school} · ${getGradeName(p.grade)}`;

  // 年代标签
  const eraName = getEraName(p.year);
  document.getElementById('player-era-tag').textContent = eraName;

  // 徽章
  document.getElementById('family-badge').textContent = `${p.family_type}家庭`;
  document.getElementById('interest-badge').textContent = p.interests.join('、') || '无';

  // 状态值
  document.getElementById('mood-value').textContent = p.mood;
  document.getElementById('mood-bar').style.width = `${p.mood}%`;

  document.getElementById('stress-value').textContent = p.stress;
  document.getElementById('stress-bar').style.width = `${p.stress}%`;

  document.getElementById('health-value').textContent = p.health;
  document.getElementById('health-bar').style.width = `${p.health}%`;

  document.getElementById('score-value').textContent = p.estimated_score;

  // 历史记录
  if (gameState.history && gameState.history.length > 0) {
    document.getElementById('history-list').innerHTML = gameState.history
      .map(h => `<div class="history-item"><strong>${h.event}</strong>: ${h.choice}</div>`)
      .reverse()
      .join('');
  } else {
    document.getElementById('history-list').innerHTML = '<div class="history-empty">暂无记录</div>';
  }

  // 人物关系面板
  renderRelations();
}

// 渲染人物关系面板
function renderRelations() {
  const list = document.getElementById('relation-list');
  if (!list || !gameState || !gameState.player) return;
  const p = gameState.player;
  const rows = [];

  const bar = (emoji, label, value) => {
    const v = Math.max(0, Math.min(100, Math.round(value)));
    return `<div class="relation-item">
      <span class="relation-emoji">${emoji}</span>
      <span class="relation-name">${label}</span>
      <div class="relation-bar"><div class="relation-fill" style="width:${v}%"></div></div>
      <span class="relation-value">${v}</span>
    </div>`;
  };

  if (p.crush) {
    const tag = p.crush.confessed ? '（已表白）' : '';
    rows.push(bar('💕', `我喜欢的·${p.crush.name}${tag}`, p.crush.relation));
  }
  if (p.admirer) {
    const tag = p.admirer.accepted ? '（在一起）' : '';
    rows.push(bar('💗', `喜欢我的·${p.admirer.name}${tag}`, p.admirer.relation));
  }
  if (p.teacher) {
    rows.push(bar('👨‍🏫', p.teacher.name, p.teacher.relation));
  }
  if (typeof p.deskmate_relation === 'number') {
    rows.push(bar('🤝', '同桌', p.deskmate_relation));
  }
  (p.family || []).forEach(m => {
    rows.push(bar('👪', `${m.role}·${m.name}`, m.relation));
  });
  (gameState.friends || []).forEach(f => {
    rows.push(bar('🧑‍🤝‍🧑', f.name, f.relation));
  });

  list.innerHTML = rows.length ? rows.join('') : '<div class="history-empty">暂无人物关系</div>';
}

// 更新时间显示
function updateTimeDisplay(timeInfo) {
  if (!timeInfo) return;

  document.querySelector('.time-year').textContent = timeInfo.year;
  document.getElementById('time-month').textContent = timeInfo.month;
  document.getElementById('time-grade').textContent = timeInfo.gradeName;
}

// 显示事件
function showEvent(event) {
  document.getElementById('event-badge').textContent = event.category;
  document.getElementById('event-title').textContent = event.title;
  document.getElementById('event-description').textContent = event.description;

  const choicesContainer = document.getElementById('choices-container');
  choicesContainer.innerHTML = event.choices.map((choice, index) =>
    `<button class="choice-btn" onclick="makeChoice(${index})">${choice.text}</button>`
  ).join('');

  document.getElementById('event-card').style.display = 'block';
}

// 隐藏事件
function hideEvent() {
  document.getElementById('event-card').style.display = 'none';
}

// 显示/隐藏加载
function showLoading() {
  document.getElementById('loading').style.display = 'flex';
}

function hideLoading() {
  document.getElementById('loading').style.display = 'none';
}

// 做选择
async function makeChoice(choiceIndex) {
  try {
    const response = await fetch('/api/choose', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ choiceIndex })
    });

    const data = await response.json();

    if (data.success) {
      gameState = data.gameState;

      // 显示效果
      if (data.effects) {
        showEffects(data.effects);
      }

      // 更新UI
      updateGameUI();

      // 检查升级
      if (data.gradeUp) {
        await gradeUp();
      }

      // 继续游戏
      setTimeout(advanceGame, 800);
    }
  } catch (error) {
    console.error('做出选择失败:', error);
    showToast('操作失败，请重试', 'negative');
  }
}

// 升级
async function gradeUp() {
  try {
    const response = await fetch('/api/gradeup', {
      method: 'POST'
    });

    const data = await response.json();

    if (data.success) {
      gameState = data.gameState;

      // 显示升级提示
      showToast(`🎓 升入${getGradeName(gameState.player.grade)}！`, 'positive');
    }
  } catch (error) {
    console.error('升级失败:', error);
  }
}

// 显示效果提示
function showEffects(effects) {
  const items = [];

  if (effects.mood) {
    const sign = effects.mood > 0 ? '+' : '';
    const type = effects.mood > 0 ? 'positive' : 'negative';
    items.push({ text: `😊 心情${sign}${effects.mood}`, type });
  }
  if (effects.stress) {
    const sign = effects.stress > 0 ? '+' : '';
    const type = effects.stress > 0 ? 'negative' : 'positive';
    items.push({ text: `😰 压力${sign}${effects.stress}`, type });
  }
  if (effects.health) {
    const sign = effects.health > 0 ? '+' : '';
    const type = effects.health > 0 ? 'positive' : 'negative';
    items.push({ text: `💪 健康${sign}${effects.health}`, type });
  }
  if (effects.score) {
    const sign = effects.score > 0 ? '+' : '';
    const type = effects.score > 0 ? 'positive' : 'negative';
    items.push({ text: `📝 成绩${sign}${effects.score}`, type });
  }
  if (effects.money) {
    const sign = effects.money > 0 ? '+' : '';
    const type = effects.money > 0 ? 'positive' : 'negative';
    items.push({ text: `💰 零花钱${sign}${effects.money}`, type });
  }
  if (effects.crush_relation) {
    const sign = effects.crush_relation > 0 ? '+' : '';
    const type = effects.crush_relation > 0 ? 'positive' : 'negative';
    items.push({ text: `💕 心动值${sign}${effects.crush_relation}`, type });
  }
  if (effects.admirer_relation) {
    const sign = effects.admirer_relation > 0 ? '+' : '';
    const type = effects.admirer_relation > 0 ? 'positive' : 'negative';
    items.push({ text: `💗 TA对你的好感${sign}${effects.admirer_relation}`, type });
  }
  if (effects.friend_relation) {
    const sign = effects.friend_relation > 0 ? '+' : '';
    const type = effects.friend_relation > 0 ? 'positive' : 'negative';
    items.push({ text: `🧑‍🤝‍🧑 好友关系${sign}${effects.friend_relation}`, type });
  }
  if (effects.family_relation) {
    const sign = effects.family_relation > 0 ? '+' : '';
    const type = effects.family_relation > 0 ? 'positive' : 'negative';
    items.push({ text: `👪 亲情${sign}${effects.family_relation}`, type });
  }
  if (effects.deskmate_relation) {
    const sign = effects.deskmate_relation > 0 ? '+' : '';
    const type = effects.deskmate_relation > 0 ? 'positive' : 'negative';
    items.push({ text: `🤝 同桌关系${sign}${effects.deskmate_relation}`, type });
  }
  if (effects.teacher_relation) {
    const sign = effects.teacher_relation > 0 ? '+' : '';
    const type = effects.teacher_relation > 0 ? 'positive' : 'negative';
    items.push({ text: `👨‍🏫 师生关系${sign}${effects.teacher_relation}`, type });
  }

  items.forEach(item => {
    showToast(item.text, item.type);
  });
}

// 显示Toast
function showToast(message, type = 'positive') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<div class="toast-content">${message}</div>`;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'toastSlideIn 0.3s ease reverse';
    setTimeout(() => toast.remove(), 300);
  }, 2000);
}

// 显示结束界面
async function showEndScreen(endReason) {
  if (endReason === 'failure') {
    // 因压力过大或健康问题退学
    gameScreen.classList.add('hidden');
    endScreen.classList.remove('hidden');

    document.getElementById('final-score').textContent = '退学';
    document.getElementById('college-tier').textContent = '';
    document.getElementById('evaluation-text').textContent = '😢 由于压力过大或健康问题，你未能完成高中学业... 但人生不止一条路！';
    document.getElementById('score-details').style.display = 'none';
    document.getElementById('prom-section').style.display = 'none';
    document.getElementById('end-choices').style.display = 'none';
    document.getElementById('retry-section').style.display = 'block';
    // 退学也给一份行为总结
    loadReport();
    return;
  }

  // 调用高考API
  try {
    const response = await fetch('/api/gaokao', {
      method: 'POST'
    });

    const data = await response.json();

    if (data.success) {
      gameScreen.classList.add('hidden');
      endScreen.classList.remove('hidden');

      // 显示成绩
      document.getElementById('final-score').textContent = data.score;
      document.getElementById('college-tier').textContent = data.collegeTier || '';
      document.getElementById('evaluation-text').textContent = data.evaluation;

      // 显示成绩详情
      document.getElementById('score-details').style.display = 'block';
      showScoreDetails(data);

      // 先举办毕业晚会，再进入志愿填报
      showProm(data);
    }
  } catch (error) {
    console.error('高考结算失败:', error);
  }
}

// 毕业晚会：表白 / 告别朋友 / 回应仰慕者
let promData = null;

function showProm(data) {
  promData = data;
  const section = document.getElementById('prom-section');
  section.style.display = 'block';
  document.getElementById('prom-log').innerHTML = '';
  document.getElementById('prom-continue').style.display = 'none';

  renderPromActions([]);
}

function renderPromActions(done) {
  const p = gameState && gameState.player;
  const crush = p && p.crush;
  const admirer = p && p.admirer;
  const friends = (gameState && gameState.friends) || [];

  const actions = [];
  if (crush && !done.includes('confess')) {
    actions.push(`<button class="prom-btn confess" onclick="promAction('confess')">💞 向喜欢的「${crush.name}」表白</button>`);
  }
  if (admirer && !admirer.accepted && !done.includes('respond_admirer')) {
    actions.push(`<button class="prom-btn admirer" onclick="promAction('respond_admirer')">💗 回应喜欢你的「${admirer.name}」</button>`);
  }
  if (!done.includes('farewell')) {
    const label = friends.length ? `🥹 和朋友们郑重告别` : `🌙 独自和这三年告别`;
    actions.push(`<button class="prom-btn farewell" onclick="promAction('farewell')">${label}</button>`);
  }

  const container = document.getElementById('prom-actions');
  if (actions.length === 0) {
    container.innerHTML = '';
    document.getElementById('prom-continue').style.display = 'block';
  } else {
    container.innerHTML = actions.join('');
    // 至少做过一个动作后即可继续
    document.getElementById('prom-continue').style.display = done.length ? 'block' : 'none';
  }
}

async function promAction(action) {
  document.querySelectorAll('.prom-btn').forEach(b => b.disabled = true);
  try {
    const response = await fetch('/api/graduation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
    const data = await response.json();

    if (data.success) {
      if (data.gameState) gameState = data.gameState;

      const log = document.getElementById('prom-log');
      const li = document.createElement('li');
      li.className = `prom-log-item ${data.result || ''}`;
      li.innerHTML = `<span class="prom-log-msg">${data.message}</span>` +
        (data.effectsText ? `<span class="prom-log-eff">${data.effectsText}</span>` : '');
      log.appendChild(li);

      renderPromActions(data.done || []);
    } else {
      document.querySelectorAll('.prom-btn').forEach(b => b.disabled = false);
    }
  } catch (error) {
    console.error('毕业晚会动作失败:', error);
    document.querySelectorAll('.prom-btn').forEach(b => b.disabled = false);
  }
}

// 结束晚会，进入志愿填报
function finishProm() {
  document.getElementById('prom-section').style.display = 'none';
  showCollegeChoices(promData);
}

// 显示志愿选择
function showCollegeChoices(data) {
  const endChoices = document.getElementById('end-choices');
  endChoices.style.display = 'block';

  const score = data.score;

  // 根据分数推荐可填报的院校档次（稳/冲两档为主）
  let tiers;
  if (score >= 680) tiers = ['清北', 'C9', '985'];
  else if (score >= 650) tiers = ['C9', '985', '211'];
  else if (score >= 620) tiers = ['985', '211', '一本'];
  else if (score >= 560) tiers = ['211', '一本', '二本'];
  else if (score >= 500) tiers = ['一本', '二本'];
  else if (score >= 420) tiers = ['二本', '专科'];
  else tiers = ['专科'];

  const majors = ['理工科', '医学', '经管财经', '文史哲', '艺术传媒', '师范教育'];

  applyState = { tier: tiers[Math.floor(tiers.length / 2)] || tiers[0], major: majors[0] };

  const renderOpts = (containerId, opts, key) => {
    document.getElementById(containerId).innerHTML = opts.map(o =>
      `<button class="apply-opt ${applyState[key] === o ? 'active' : ''}" data-key="${key}" data-val="${o}" onclick="selectApplyOption('${key}','${o}')">${o}</button>`
    ).join('');
  };
  renderOpts('tier-options', tiers, 'tier');
  renderOpts('major-options', majors, 'major');

  // 建议提示（来自后端 /api/gaokao 透传或前端默认）
  const advice = document.getElementById('apply-advice');
  advice.innerHTML = '';

  // 感情线任一方好感较高时，显示"为爱填报"选项
  const player = gameState && gameState.player;
  const crush = player && player.crush;
  const admirer = player && player.admirer;
  const loveWrap = document.getElementById('apply-love-wrap');
  const crel = crush ? crush.relation : 0;
  const arel = admirer ? admirer.relation : 0;
  if (crel >= 50 || arel >= 50) {
    loveWrap.style.display = 'block';
    const loveLabel = document.getElementById('apply-love-label');
    if (loveLabel) {
      const who = crel >= arel ? (crush && crush.name) : (admirer && admirer.name);
      loveLabel.textContent = ` 💕 为了和「${who}」去同一座城市，调整志愿`;
    }
  } else {
    loveWrap.style.display = 'none';
  }
}

let applyState = { tier: '一本', major: '理工科' };

// 选择志愿选项
function selectApplyOption(key, val) {
  applyState[key] = val;
  document.querySelectorAll(`.apply-opt[data-key="${key}"]`).forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === val);
  });
}

// 提交志愿，调用后端录取判定
async function submitApplication() {
  const loveCity = document.getElementById('apply-love-city').checked;
  document.getElementById('apply-submit').disabled = true;

  try {
    const response = await fetch('/api/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        school_tier: applyState.tier,
        major: applyState.major,
        love_city: loveCity
      })
    });
    const data = await response.json();

    if (data.success) {
      document.getElementById('end-choices').style.display = 'none';

      const result = document.getElementById('apply-result');
      result.style.display = 'block';
      document.getElementById('apply-result-message').textContent = data.message;
      document.getElementById('apply-analysis').innerHTML =
        (data.analysis || []).map(a => `<li>${a}</li>`).join('');

      // 录取结果出来后加载行为报告
      await loadReport();
    }
  } catch (error) {
    console.error('志愿提交失败:', error);
    document.getElementById('apply-submit').disabled = false;
  }
}

// 加载 AI 行为总结报告
async function loadReport() {
  const section = document.getElementById('report-section');
  section.style.display = 'block';
  document.getElementById('report-summary').textContent = '报告生成中...';
  document.getElementById('report-categories').innerHTML = '';

  try {
    const response = await fetch('/api/report', { method: 'POST' });
    const data = await response.json();

    if (data.success && data.available && data.report) {
      document.getElementById('report-summary').textContent = data.report.summary || '';
      document.getElementById('report-categories').innerHTML =
        (data.report.categories || []).map(c => `
          <div class="report-category">
            <div class="report-cat-head">
              <span class="report-cat-name">${c.name}</span>
              ${c.tag ? `<span class="report-cat-tag">${c.tag}</span>` : ''}
            </div>
            <p class="report-cat-comment">${c.comment}</p>
          </div>`).join('');
    } else {
      document.getElementById('report-summary').textContent =
        data.message || '行为总结报告暂不可用。';
    }
  } catch (error) {
    console.error('报告加载失败:', error);
    document.getElementById('report-summary').textContent = '报告加载失败。';
  }
}

// 复读
async function retryGame() {
  // 复读就是重新开始
  await restartGame();
}

// 显示成绩详情
function showScoreDetails(data) {
  const p = gameState.player;
  const subjectNames = {
    'chinese': '语文',
    'math': '数学',
    'english': '英语',
    'physics': '物理',
    'chemistry': '化学',
    'biology': '生物',
    'history': '历史',
    'geography': '地理',
    'politics': '政治'
  };

  let html = '';
  let total = 0;

  if (p.subject_preference === '理科') {
    ['chinese', 'math', 'english', 'physics', 'chemistry', 'biology'].forEach(key => {
      const score = Math.round(p.subjects[key]);
      total += score;
      html += `<div class="score-row">
        <span>${subjectNames[key]}</span>
        <span>${score}分</span>
      </div>`;
    });
  } else if (p.subject_preference === '文科') {
    ['chinese', 'math', 'english', 'history', 'geography', 'politics'].forEach(key => {
      const score = Math.round(p.subjects[key]);
      total += score;
      html += `<div class="score-row">
        <span>${subjectNames[key]}</span>
        <span>${score}分</span>
      </div>`;
    });
  } else {
    ['chinese', 'math', 'english'].forEach(key => {
      const score = Math.round(p.subjects[key]);
      total += score;
      html += `<div class="score-row">
        <span>${subjectNames[key]}</span>
        <span>${score}分</span>
      </div>`;
    });
  }

  html += `<div class="score-row total">
    <span>总分</span>
    <span>${data.score}分</span>
  </div>`;

  document.getElementById('score-table').innerHTML = html;
}

// 重新开始
async function restartGame() {
  try {
    await fetch('/api/restart', { method: 'POST' });

    gameState = null;
    currentEvent = null;
    promData = null;

    endScreen.classList.add('hidden');
    createScreen.classList.add('hidden');
    coverScreen.classList.remove('hidden');

    // 重置结束界面各区块的显隐，避免下一局残留
    ['prom-section', 'apply-result', 'report-section', 'retry-section'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });

    // 重置表单
    document.getElementById('create-form').reset();
  } catch (error) {
    console.error('重启失败:', error);
  }
}

// 辅助函数
function getGradeName(grade) {
  return ['', '高一', '高二', '高三'][grade] || '';
}