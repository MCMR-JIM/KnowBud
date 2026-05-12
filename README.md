# Sprout — 儿童伴学桌面应用

面向学龄儿童的本机学习伙伴：以有限状态机(FSM)与决策引擎为教学核心，语音对话(ASR/TTS)与大语言模型(LLM)为可替换技能层，提供本地化、无网亦可用的沉浸式伴学体验。

## English

**Sprout** is a production-grade desktop learning companion for school-age children. The tutoring flow is driven by a Python FSM and decision engine — not an LLM prompt chain. ASR, TTS, and LLM are stateless, pluggable skill modules. Frontend options include a React/TypeScript SPA and a Streamlit multipage app (child-facing + parent admin).

---

## 核心特性

### 学习引擎
- **FSM 决策核心**：6 条优先级规则驱动的 5 阶段学习循环（未开始→学习→练习→复习→已掌握），不由 LLM 直接编排
- **Agent 架构**（可选）：`LEARNING_ARCH_MODE=agent` 启用主题路由 + 图谱策展 + 掌握度引擎的智能调度
- **掌握度追踪**：深度/稳定性/连胜/间隔重复多维评估，自动触发复习与探索奖励

### 知识图谱
- 知识点节点支持 10 种边类型（requires / supports / part_of / derived_from / defines / explains / causes / uses 等）
- 图谱提案全生命周期：提议→验证→影子→激活→驳回
- **图谱检索代理**：LLM 多轮工具调用，在已有知识结构中定位新知识点
- **图谱定位器 & 游走器**：精确判定新节点的最佳插入位置
- **候选图谱审核**：命名校验（冗余/练习标题/近似重复）+ 逻辑校验（错误父节点/前置反转/孤立节点/跨学科边）

### 文档摄入管线
- 多格式解析：PDF (PyMuPDF)、DOCX (python-docx)、PPTX (python-pptx)，图像/扫描件走 MinerU
- **双管线并行**：
  - 传统管线：逐块 LLM 分类 + 图谱搜索
  - 结构化管线（新）：快速文档扫描→主题块提取→树形组织→图谱定位→提案生成
- 文档结构分析：自动识别课文区、单词表、练习题、附录
- **候选图谱提取**：知识点节点 + 中继节点 + 连边 + 合并候选，支持流式进度反馈
- 摄入进度追踪：解析→提取→审核→编译 四阶段实时可见

### 语音对话
- **ASR**：`faster-whisper` 本地推理 (int8 量化) 或 Docker Whisper 服务
- **TTS**：`edge-tts` 本地合成或 Docker TTS 服务，儿童友好语音参数
- 三种部署模式：`local` | `docker` | `auto`（自动降级回退）
- 流式语音输出 + 中断支持（实时对话体验）
- 语音产物落盘 `artifacts/audio/`

### LLM 技能
- 问题生成与答案评估（鼓励性反馈，无挫败感）
- 五维雷达评估：专注度/活跃度/逻辑性/掌握度/情绪
- 资源块分类与知识节点提案
- **LLM 网关抽象层**：统一 `call_llm` / `call_llm_json` / `call_llm_text` 调用接口，自动处理 JSON 栅栏解析、DeepSeek 特殊参数等
- 兼容所有 OpenAI 兼容 API，支持本地模型加载（HuggingFace Transformers）

### 家长/管理端
- 学科管理（创建/编辑/删除学科根节点，LLM 辅助学科分类）
- 资源上传（拖拽即可，自动触发后台摄入管线）
- **知识图谱可视化**（D3.js 力导向图 + ECharts 图表）
- 学习分析（雷达图/柱状图/折线图/得分趋势）
- 复习队列管理（推送知识点到孩子复习列表）
- **LLM 设置面板**：API 密钥配置、提供商选择（DeepSeek 预设/自定义）、本地模型下载管理、GPU 信息检测
- 错题本与学习回放
- 文件浏览器

### 探索时间窗
- 掌握奖励机制：真正掌握知识点后获得自由探索时间
- 可配置时长与冷却期
- 探索期间的非计划提问自动生成图谱提案

---

## 技术栈

| 层 | 技术选型 |
|---|---------|
| **后端核心** | Python 3.11+, Pydantic v2, SQLite |
| **HTTP API** | FastAPI, Uvicorn, python-multipart |
| **LLM** | OpenAI SDK (兼容所有厂商), HuggingFace Transformers, Torch |
| **ASR** | faster-whisper (int8), Docker Whisper |
| **TTS** | edge-tts (async), Docker TTS |
| **文档解析** | PyMuPDF, python-docx, python-pptx, MinerU |
| **Child 前端** | React 19, TypeScript 6, Vite 8, Tailwind CSS 3 |
| **可视化** | D3.js 7, ECharts 6, Recharts 3 |
| **PDF 阅读** | react-pdf 10, pdfjs-dist 5 |
| **Parent 前端** | React Router 7, Axios, Lucide React |
| **Streamlit 前端** | Streamlit 1.28+ (快速原型/管理用) |
| **容器化** | Docker Compose (ASR/TTS 服务) |
| **测试** | Pytest 7+ |
| **状态存储** | SQLite (事务存储) + JSON (兼容快照) |

---

## 项目结构

```text
Sprout/
├── src/
│   ├── core/              # 领域模型、FSM 决策引擎、动作定义、安全删除
│   ├── services/          # 会话编排、文档摄入、图谱操作、LLM 网关
│   │   ├── session_backend.py     # 中央编排器 (1840 行)
│   │   ├── document_ingestion.py  # 文档摄入管线 (2389 行)
│   │   ├── resource_graph_curation.py  # 资源图谱策展 (1415 行)
│   │   ├── candidate_review.py    # 候选图谱审核 (856 行)
│   │   ├── graph_search.py        # 图谱检索代理 (527 行)
│   │   ├── graph_locator.py       # 图谱定位器 (368 行)
│   │   ├── graph_walker.py        # 图谱游走器 (369 行)
│   │   ├── document_analyzer.py   # 文档结构分析 (218 行)
│   │   ├── llm_gateway.py         # LLM 调用抽象层 (150 行)
│   │   └── local_llm_server.py    # 本地 LLM 推理 (195 行)
│   ├── skills/            # ASR/TTS/LLM 技能插件（无 UI 依赖）
│   ├── api/               # FastAPI HTTP API (v1.3)
│   │   ├── app.py                 # API 路由 (1667 行)
│   │   ├── schemas.py            # 请求/响应模型
│   │   └── settings_routes.py    # 设置 API
│   └── agent/             # Agent 架构 (v2)
│       ├── orchestrator.py       # 编排器
│       ├── topic_router.py       # 主题路由
│       ├── mastery_engine.py     # 掌握度引擎
│       ├── graph_curator.py      # 图谱策展
│       └── policy.py             # 策略配置
├── frontend/              # React/TypeScript 前端
│   └── src/
│       ├── pages/         # Home, KidsLearning, StudyRoom, AdminDashboard, ModeSelect
│       ├── components/    # SettingsPanel, PdfViewer, CelebrationModal, Live2DRabbit
│       └── api/           # Axios 客户端封装
├── pages/                 # Streamlit 页面（儿童学习/家长看板）
├── docker/asr_tts/        # Docker ASR/TTS 部署
├── scripts/               # 工具脚本 (MinerU worker, 资源图谱模拟, 模型加载测试)
├── tests/                 # Pytest 测试套件 (14 个测试文件)
├── docs/                  # API 文档、图谱管线说明、ASR/TTS 指南
├── data/                  # 运行时数据（已 gitignore）
├── app.py                 # Streamlit 入口（星梦乐园首页）
└── design.py              # UI 主题、配色、图标、伴学宠物定义
```

---

## 快速开始

### 1. 环境准备

```bash
# 要求 Python 3.11+
cd Sprout
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
# 编辑 .env，至少填入 OPENAI_API_KEY
```

### 2. 启动后端 API

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8090 --reload
```

API 文档：启动后访问 `http://localhost:8090/docs`

### 3. 启动前端（二选一）

**React 前端（推荐，功能完整）**：

```bash
cd frontend
npm install
npm run dev          # 默认 http://localhost:5173
```

**Streamlit 前端（轻量快速）**：

```bash
streamlit run app.py
```

### 4. (可选) Docker 部署 ASR/TTS 服务

```bash
docker compose -f docker/asr_tts/docker-compose.yml up -d

# 停止
docker compose -f docker/asr_tts/docker-compose.yml down
```

---

## 配置说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | — | 兼容 OpenAI SDK 的 API 密钥 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 基地址 |
| `OPENAI_MODEL` | `gpt-4o-mini` | 默认模型 |
| `DATA_ROOT` | `./data/library` | 教学资源根目录 |
| `STATE_DB_FILE` | `./data/state.db` | SQLite 状态数据库 |
| `VOICE_BACKEND_MODE` | `auto` | 语音后端模式：`auto` / `local` / `docker` |
| `LEARNING_ARCH_MODE` | `legacy` | 学习架构：`legacy` / `agent` / `hybrid` |
| `ASR_SERVICE_URL` | `http://127.0.0.1:9000` | Docker ASR 服务地址 |
| `TTS_SERVICE_URL` | `http://127.0.0.1:5501` | Docker TTS 服务地址 |
| `WHISPER_MODEL_SIZE` | `base` | faster-whisper 模型大小 |
| `EDGE_TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | TTS 语音角色 |
| `EXPLORE_WINDOW_MINUTES` | `5` | 探索时间窗时长（分钟） |
| `TOPIC_INERTIA_BONUS` | `0.12` | 主题惯性奖励 |
| `TOPIC_SWITCH_MARGIN` | `0.2` | 主题切换最低优势 |
| `PREREQ_UNLOCK_DEPTH` | `1` | 前置解锁掌握深度 |
| `SHADOW_PROMOTE_DEPTH` | `2` | 影子提案晋升深度 |
| `FSM_FAIL_THRESHOLD` | `3` | 连续错误触发复习阈值 |
| `FSM_MASTER_STREAK` | `3` | 连续正确触发掌握阈值 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

完整配置见 `.env.example`。

---

## 设计原则

1. **教学流程由 FSM 决策引擎控制，不由 LLM 直接编排**：LLM 只负责内容生成（出题、评估、分类），不参与流程控制
2. **技能层无 UI 依赖**：`src/skills/` 不依赖 Streamlit 或任何前端框架，纯后端能力
3. **前后端分离**：FastAPI 提供 RESTful API，前端通过 HTTP 调用，支持 React / Streamlit 双前端
4. **状态持久化**：SQLite 事务存储 + 事件溯源，支持断点续学
5. **纵深离线可用**：本地 ASR/TTS/LLM 推理，断网不影响核心学习体验

---

## 测试

```bash
# 运行全部测试
pytest

# 按模块运行
pytest tests/test_document_ingestion.py -v
pytest tests/test_candidate_review.py -v
pytest tests/test_decision_engine.py -v
pytest tests/test_agent_flow.py -v
```

---

## 语音链路

```
儿童录音 → ASR (faster-whisper / Docker Whisper)
         → LLM 评估答案 + 生成回复
         → TTS (edge-tts / Docker) 合成语音
         → 前端播放（支持流式 + 中断）
```

- `VOICE_BACKEND_MODE=local`：强制本地 `faster-whisper + edge-tts`
- `VOICE_BACKEND_MODE=docker`：走 Docker 服务
- `VOICE_BACKEND_MODE=auto`：优先 Docker，不可用时自动回退本地

---

## 文档摄入管线

```
上传文档 → 格式解析 (PDF/DOCX/PPTX/图像)
        → 结构分析 (课文/单词表/练习/附录识别)
        → 主题块提取 (LLM 识别教学单元)
        → 图谱定位 (确定各知识点在图中的位置)
        → 提案生成 (创建图谱节点提案)
        → 候选审核 (命名与逻辑校验)
        → 编译入库 (写入图谱)
```

进度全程可视：`文档解析中 → 候选节点提取中 → 候选结构已生成 → 审核中 → 编译入图中 → 已完成`

---

## License

项目所有者后续补充。
