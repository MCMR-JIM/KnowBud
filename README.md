# LoopTutor / LTA（Local Teaching Agent）

面向学龄儿童的本地伴学桌面应用：以有限状态机与决策引擎为核心，语音与 LLM 作为可替换技能层，Streamlit 多页分离儿童端与家长/评委看板。

## English

**LoopTutor** hosts **LTA (Local Teaching Agent)**, a production-oriented desktop learning companion. Core learning flow is driven by a Python FSM and decision engine; ASR/TTS/LLM are stateless skills. The UI is a Streamlit multipage app (child-facing + admin).

This repository includes a runnable Streamlit frontend with FSM-driven backend orchestration and pluggable ASR/TTS/LLM skills.

## 环境要求

- Python **3.11+**
- Windows / macOS / Linux（开发以 Windows 为主时可先验证本机路径）

## 快速开始

```bash
cd LoopTutor
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等
```

启动应用：

```bash
streamlit run app.py
```

## 目录分层

```text
LoopTutor/
├── src/
│   ├── core/          # 领域模型与决策引擎
│   ├── services/      # 会话编排与后端调用链
│   └── skills/        # ASR/TTS/LLM 技能实现
├── pages/             # Streamlit 页面
├── scripts/asr_tts/   # ASR/TTS 演示与验证脚本
├── docker/asr_tts/    # Docker 部署编排
├── docs/asr_tts/      # 语音相关文档归档
├── artifacts/audio/   # 运行时音频产物（已忽略）
├── data/              # 运行时状态数据（已忽略生成物）
├── logs/              # 运行日志（已忽略）
└── tests/
```

## 配置说明

复制 `.env.example` 为 `.env`，至少配置：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | 兼容 OpenAI SDK 的密钥（可对接云 API 或本地网关） |
| `OPENAI_BASE_URL` | API 基地址 |
| `DATA_ROOT` | 本地教学资源根目录 |
| `STATE_FILE` | 学习状态 JSON 路径 |
| `VOICE_BACKEND_MODE` | `auto` / `local` / `docker` |
| `ASR_SERVICE_URL` | Docker ASR 服务地址 |
| `TTS_SERVICE_URL` | Docker TTS 服务地址 |
| `AUDIO_ARTIFACT_ROOT` | 入站/出站语音文件落盘目录 |

## 语音部署模式

- `VOICE_BACKEND_MODE=local`：强制走本地 `faster-whisper + edge-tts`
- `VOICE_BACKEND_MODE=docker`：优先走 Docker 服务（地址来自 `ASR_SERVICE_URL`/`TTS_SERVICE_URL`）
- `VOICE_BACKEND_MODE=auto`：有服务地址就走 Docker，否则走本地；服务故障时会自动回退本地

### Docker 启动 ASR/TTS

```bash
docker compose -f docker/asr_tts/docker-compose.yml up -d
```

停止：

```bash
docker compose -f docker/asr_tts/docker-compose.yml down
```

## Frontend API

已提供用于前后端分离的 HTTP API（单会话、回合输入、事件轮询、掌握度、图谱、复习队列、探索时间窗、流式语音输出）：

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8090 --reload
```

接口文档见：`docs/api/frontend_http_api.md`（v1.3，单会话模式，保留 `/v1/sessions/*` 兼容路径）。
存储设计见：`docs/api/session_state_storage.md`（SQLite 事务存储 + 事件按需加载）。

## 协议与规范

- 学习流程由 **决策引擎（FSM）** 控制，不由 LLM 直接编排。
- `skills` 层不依赖 Streamlit；UI 仅通过编排层调用后端。

## 语音链路（ASR -> LLM -> TTS）

- 儿童端页面先把录音交给 `SessionBackend.transcribe_audio()` 做 ASR。
- 文本答案经 `SessionBackend.evaluate_student_answer()` 完成评估与积分变更。
- 评估回复可走 `SessionBackend.synthesize_reply_audio()` 一次性合成，或 `SessionBackend.synthesize_reply_audio_stream()` 流式合成。
- 页面可调用普通回合接口拿 `reply + points + audio`，也可调用实时接口拿 `stream_id` 再边收边播并支持打断。

语音相关脚本统一放到 `scripts/asr_tts/`：

- `scripts/asr_tts/tts_demo.py`
- `scripts/asr_tts/asr_demo.py`

运行时音频产物默认落在 `artifacts/audio/`（已加入 `.gitignore`）。

## License

未指定；后续由项目所有者补充。
