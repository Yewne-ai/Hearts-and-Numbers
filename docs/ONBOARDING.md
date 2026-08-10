# 于你 Yewne 开发者上手指南

> 项目原名 uni / MOMO,因商标注册于 2026-07 更名为**于你 Yewne**(仓库目录名仍为 momo)。

## 这个项目是什么

**于你 Yewne** 是面向中文用户的情绪陪伴 AI App。

不是心理治疗，不是泛聊机器人——**只做"有人在"这件事**：用户说出心情，于你用温暖但不油腻的语言接住，帮 ta 命名情绪、打断内耗、在孤独时陪着。支持**语音对话**（说话进、语音回），有 2 个不同性格的陪伴体。

现状：**Demo 阶段**。核心链路跑通（语音 ↔ 前端 ↔ 后端 ↔ DeepSeek LLM），线上 demo 在 `uniai.net.cn`。

数据库持久化层已落地（用户 / 会话 / 消息，PostgreSQL + Alembic，见 `app/infra/`），由 `.env` 里的 `PERSISTENCE_ENABLED` 开关控制，**本地默认关闭**——不装 PostgreSQL 也能跑通聊天。**还没有登录 / 多账号体系**：用户身份靠前端生成的匿名 `external_user_id`，未做校验。

---

## 仓库结构（三分钟版）

```
momo/
├── apps/web/          # Next.js 网页 Demo（前端主战场）
├── apps/mobile/       # React Native / Expo App（移动端，最低优先）
├── services/api/      # FastAPI 后端（AI 回答 / 语音 / 接口）
└── docs/              # 文档（就是这里）
```

**最常去的地方：**

| 想改什么 | 去哪里 |
|---|---|
| AI 语气 / 人格 / system prompt | `services/api/app/llm/deepseek.py` |
| 接口编排（safety→分类→LLM→TTS） | `services/api/app/domain/conversation/service.py` |
| 危机关键词 / 安全规则 | `services/api/app/domain/safety/rules.py` |
| 语音合成 TTS（豆包） | `services/api/app/tts/doubao.py` |
| 语音识别 STT（Whisper） | `services/api/app/stt/whisper.py` |
| Demo 页面 UI | `apps/web/app/demo/page.tsx` |
| 语音录入 / 打断 / VAD | `apps/web/app/demo/_components/VoiceInputButton.tsx` |
| 语音播放（含手机端兼容） | `apps/web/lib/speech/playYewneSpeech.ts` |
| 前端 API 类型 / 请求封装 | `apps/web/lib/api/yewne.ts` |

---

## 两个人格

用户可在前端切换，每个有独立的 system prompt（都在 `deepseek.py`）：

- **优优**（key: `youyou`）—— 直接、带点毒舌，但毒完会接住情绪
- **妮妮**（key: `nini`）—— 把大问题拆小，帮你迈出第一步，默认人格

切换人格会重置当前会话。

---

## 本地跑起来（复制粘贴即可）

### 前提工具
- **Node.js**（LTS）+ **pnpm**：`npm install -g pnpm`
- **Python 3.12+** + **uv**：`curl -LsSf https://astral.sh/uv/install.sh | sh`

### 后端
```bash
cd services/api
cp .env.example .env        # 填 DEEPSEEK_API_KEY，问负责人要
uv sync
uv run uvicorn app.main:app --reload
```
后端在 **http://localhost:8000** ：Swagger `/docs`，健康检查 `/health`。

> **没有 Key 也能跑**：自动降级 Mock 模式，AI 回固定模板，用来测通路。
> 语音功能（STT/TTS）需要对应的 key，没配就只走文字 + 浏览器朗读。

### 数据库和 Redis（登录、「往期」、偏好统计要用）

不装也能跑聊天——`PERSISTENCE_ENABLED=false` 时后端照常起。但下面这些会不通：
登录注册（验证码存 Redis）、「往期」聊天记录、每轮判定的落库。

**用 Docker**（`compose.yaml` 里 Postgres 16 + Redis 都配好了）：

```bash
docker compose up -d db redis
```

**或者直接装到本机**（没有 Docker 时）：

```bash
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis

# 建库建角色，对上 .env 里那串 DATABASE_URL
createuser -s yewne 2>/dev/null; psql postgres -c "ALTER ROLE yewne PASSWORD 'yewne_dev_password'"
createdb -O yewne yewne_dev
```

然后跑迁移、打开持久化：

```bash
cd services/api
uv run alembic upgrade head
# .env 里把 PERSISTENCE_ENABLED 改成 true
```

#### 两个会卡住的坑

**brew 装不动。** 从境外源拉包可能几十分钟一个字节都没有。配镜像重试：

```bash
HOMEBREW_API_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api" \
HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles" \
brew install postgresql@16
```

`uv sync` 从 PyPI 拉包慢也是同一个原因，`UV_INDEX_URL` 指到国内镜像即可。

**Redis 起不来、`brew services list` 显示 error。** 如果这台机器以前装过
redis-stack，`/opt/homebrew/etc/redis.conf` 里会留下几行
`loadmodule ./modules/redisbloom/...`；普通 redis 找不到这些文件会**直接中止启动**，
而 `brew services start` 仍然报成功。看 `/opt/homebrew/var/log/redis.log`
确认，把那几行注释掉再 restart。

### 前端
另开一个终端：
```bash
cd apps/web
pnpm install
pnpm dev
```
浏览器打开 **http://localhost:3000/demo**

---

## 一条请求是怎么走的

**文字对话**（`POST /v1/chat/demo`）：
```
用户输入 → 安全层(safety/rules.py)：查危机关键词
            命中 → 直接返回固定降级文案，不进 LLM
            通过 → 场景分类(首句) → DeepSeek LLM(system prompt + 历史)
                    成功 → 返回回复
                    失败 → 降级 MockProvider，degraded=true
```

**语音对话**（这是 demo 主交互）：
```
说话 → 前端 VAD 自动断句 → POST /v1/speech/transcribe (Whisper STT)
     → 文字进上面的对话链路
     → 流式接口 /v1/chat/demo/stream：LLM 逐句输出
        每出一句立刻 TTS(豆包) → 前端音频队列顺序播放
```
AI 说话时用户可**打断**（桌面/安卓靠说话自动打断，iOS 靠点击）。

**5 个场景**（scene 字段，后端首句自动分类后沿用）：
`late_night` / `rumination` / `relationship` / `stress` / `loneliness`

---

## 改代码的流程

1. 从 `main` 拉分支：`git checkout -b feat/你的名字-简短描述`
2. 改代码
3. 后端改完跑测试：`cd services/api && uv run pytest`（测试在 `services/api/tests/`）
4. `git add` → `commit` → `push` → 开 **Pull Request**，指派负责人 review

> **原则**：不直接 push main，哪怕一行也开 PR。

---

## 红线（不能违反）

1. AI 回复**不出现**"治疗/诊断/药物/急救"等医疗措辞
2. **不给行动清单**（"你应该做 A/B/C"）——先陪，后建议
3. **危机表达**（自杀/自残/想死）必须走 safety 层固定文案，不进 LLM
4. **API Key 绝不提交 Git**——只放 `.env`（已在 `.gitignore`）

---

## 遇到问题

- 后端报错先看终端日志（structlog JSON，key 很清晰）
- 接口字段不匹配先看 `http://localhost:8000/docs`
- 手机端语音有兼容性坑（尤其 iOS Safari 音频路由），改 `playYewneSpeech.ts` 前先问一下
- 不确定的事直接问团队群
