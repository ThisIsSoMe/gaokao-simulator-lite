# 高考模拟器 Lite

基于 Flask 的精美网页版高考模拟器

## 快速开始

```bash
# 进入项目目录
cd /home/work/wukun04/icode/gaokao-simulator-lite

# 安装依赖
pip install -r requirements.txt

# 配置 DeepSeek（可选，用于 AI 动态生成事件）
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 启动服务
python app.py
```

然后打开浏览器访问 http://localhost:5000

## AI 动态事件（DeepSeek）

游戏支持调用 DeepSeek API 根据玩家当前状态（年级、心情、压力、家庭、兴趣、同桌关系等）动态生成事件。

- 在 `.env` 中设置 `DEEPSEEK_API_KEY` 即可启用
- 设置 `DEEPSEEK_ENABLED=false` 或不配置 Key 时，自动降级使用内置静态事件
- API 超时、网络错误、JSON 解析失败、效果值越界等异常均会安全降级或自动修正

## 功能特点

- 精美的现代化UI设计
- 流畅的交互动画效果
- 完整的高中三年模拟
- 多种事件类型和选择（含 AI 动态生成）
- 家庭情况影响系统
- 高考成绩结算

## 技术栈

- 后端: Flask
- AI: DeepSeek API（OpenAI SDK 兼容）
- 前端: 原生 HTML/CSS/JS
- 会话管理: Flask Session


## Author
ThisIsSoMe
Claude Code
Claude Opus 4.8