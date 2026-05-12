# Sprout — 儿童伴学桌面应用

面向学龄儿童的本机学习伙伴：以有限状态机(FSM)与决策引擎为教学核心，语音对话(ASR/TTS)与大语言模型(LLM)为可替换技能层，提供本地化、无网亦可用的沉浸式伴学体验。

## English

**Sprout** is a production-grade desktop learning companion for school-age children. The tutoring flow is driven by a Python FSM and decision engine — not an LLM prompt chain. ASR, TTS, and LLM are stateless, pluggable skill modules. The frontend is a React/TypeScript SPA with child-facing and parent-facing views.

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
| **前端框架** | React 19, TypeScript 6, Vite 8 |
| **样式** | Tailwind CSS 3 |
| **可视化** | D3.js 7, ECharts 6, Recharts 3 |
| **PDF 阅读** | react-pdf 10, pdfjs-dist 5 |
| **路由/HTTP** | React Router 7, Axios |
| **图标** | Lucide React |
| **容器化** | Docker Compose (ASR/TTS 服务) |
| **测试** | Pytest 7+ |
| **状态存储** | SQLite (事务存储) + JSON (兼容快照) |

---

## 前端架构

### 页面路由

| 路由 | 页面 | 面向 |
|------|------|------|
| `/` | `Home.tsx` | 身份选择（小朋友 / 家长） |
| `/mode` | `ModeSelect.tsx` | 伴学宠物选择（星空兔 / 小智龙） |
| `/kids` | `KidsLearning.tsx` | 儿童学习主页面 |
| `/study` | `StudyRoom.tsx` | 沉浸式学习舱 |
| `/admin` | `AdminDashboard.tsx` | 家长管理看板 |

### 交互流程

```
首页身份选择 → 宠物选择 → 学习主页面（语音/文字对话）
                         → 学习舱（积分、图谱、闯关）
                         → 家长看板（图谱可视化、资源管理、LLM配置）
```

### 技术细节

- **视图切换**：React Router 7 基于 URL 的路由，支持浏览器前进/后退
- **API 通信**：`client.ts` 封装 `SessionAPI`（会话状态/回合/事件/复习/探索窗/知识图谱）和 `ResourceAPI`（上传/片段/教学提示/摄入状态），通过 `config.ts` 统一管理 API 基地址
- **样式方案**：Tailwind CSS 3 工具类优先 + 自定义毛玻璃卡片、渐变进度条等组件风格
- **数据可视化**：D3.js 力导向图渲染知识图谱（节点拖拽、缩放、聚焦），ECharts 渲染学习分析图表（雷达图、柱状图、折线图），Recharts 渲染简洁统计图
- **PDF 阅读**：react-pdf 10 + pdfjs-dist 5 内嵌 PDF 渲染，支持页码跳转
- **Live2D**：通过 `Live2DRabbit.tsx` 加载 Live2D Cubism 模型，实现伴学宠物动画交互
- **状态持久化**：`localStorage` 存储角色选择和用户画像，页面刷新不丢失

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
│       ├── pages/
│       │   ├── Home.tsx              # 首页：身份选择（小朋友/家长）
│       │   ├── ModeSelect.tsx        # 伴学宠物选择（星空兔/小智龙）
│       │   ├── KidsLearning.tsx      # 儿童学习页：语音/文字对话、TTS 播放、PDF 阅读
│       │   ├── StudyRoom.tsx         # 沉浸式学习舱：积分条、知识图谱、闯关流程
│       │   └── AdminDashboard.tsx    # 家长管理看板：学科管理、资源上传、图谱可视化、LLM 设置
│       ├── components/
│       │   ├── SettingsPanel.tsx     # LLM 设置：API 密钥、模型选择、GPU 信息、模型下载
│       │   ├── PdfViewer.tsx         # PDF 阅读器 (react-pdf)
│       │   ├── CelebrationModal.tsx  # 成就庆祝弹窗
│       │   ├── DynamicMediaBoard.tsx # 动态多媒体展示板
│       │   ├── Live2DRabbit.tsx      # 伴学宠物 Live2D 展示
│       │   └── AppDialog.tsx         # 通用弹窗组件
│       └── api/
│           ├── client.ts             # Axios 封装：SessionAPI + ResourceAPI
│           └── config.ts             # API 基地址配置
├── docker/asr_tts/        # Docker ASR/TTS 部署
├── scripts/               # 工具脚本 (MinerU worker, 资源图谱模拟, 模型加载测试)
├── tests/                 # Pytest 测试套件 (14 个测试文件)
├── docs/                  # API 文档、图谱管线说明、ASR/TTS 指南
└── data/                  # 运行时数据（已 gitignore）
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

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev          # 默认 http://localhost:5173
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
2. **技能层无 UI 依赖**：`src/skills/` 不依赖任何前端框架，纯后端能力
3. **前后端分离**：FastAPI 提供 RESTful API，前端通过 HTTP 调用
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

MIT
