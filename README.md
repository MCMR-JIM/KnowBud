# LoopTutor / LTA（Local Teaching Agent）

面向学龄儿童的本地伴学桌面应用：以有限状态机与决策引擎为核心，语音与 LLM 作为可替换技能层，Streamlit 多页分离儿童端与家长/评委看板。

## English

**LoopTutor** hosts **LTA (Local Teaching Agent)**, a production-oriented desktop learning companion. Core learning flow is driven by a Python FSM and decision engine; ASR/TTS/LLM are stateless skills. The UI is a Streamlit multipage app (child-facing + admin).

This repository currently contains **Phase T0**: project layout, dependencies, environment template, and placeholders for `src/core`, `src/services`, and `src/skills`. Application entry points and business logic will land in subsequent commits.

## 环境要求

- Python **3.11+**
- Windows / macOS / Linux（开发以 Windows 为主时可先验证本机路径）

<<<<<<< HEAD
## 开始
=======
## 快速开始
>>>>>>> 02bbe3e38b8e9e5b531c4a10ae0fc0ed4fca0744

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

应用入口与 `streamlit run` 将在后续里程碑中加入；当前步骤仅保证依赖可安装、目录结构就绪。

## 目录结构（T0）

```text
LoopTutor/
├── src/
│   ├── core/          # 领域模型与决策引擎（后续）
│   ├── services/      # 会话编排与持久化（后续）
│   └── skills/        # 语音、LLM、本地资源（后续）
├── data/              # 运行时数据（.gitignore 已排除 state 等）
├── logs/              # 运行日志
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

## 配置说明

复制 `.env.example` 为 `.env`，至少配置：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | 兼容 OpenAI SDK 的密钥（可对接云 API 或本地网关） |
| `OPENAI_BASE_URL` | API 基地址 |
| `DATA_ROOT` | 本地教学资源根目录 |
| `STATE_FILE` | 学习状态 JSON 路径 |

## 协议与规范

- 学习流程由 **决策引擎（FSM）** 控制，不由 LLM 直接编排。
- `skills` 层不依赖 Streamlit；UI 仅通过编排层调用后端。

## License

未指定；后续由项目所有者补充。
