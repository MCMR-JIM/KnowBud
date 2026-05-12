# 后端知识图谱 Pipeline 技术文档

> **版本**: 1.0  
> **适用范围**: Sprout 后端知识图谱的完整数据流，从资源上传到图节点创建、去重、批准、落库。  
> **相关源码**:
> - `src/api/app.py` — HTTP API 入口
> - `src/services/document_ingestion.py` — 文档摄入引擎
> - `src/services/graph_locator.py` — 图谱定位器
> - `src/services/graph_search.py` — 图谱搜索Agent
> - `src/services/document_analyzer.py` — 文档结构分析器
> - `src/services/session_backend.py` — 会话后端（Proposal 生命周期）
> - `src/services/resource_graph_curation.py` — 资源图谱策展
> - `src/core/models.py` — 核心数据模型
> - `src/agent/models.py` — Agent 数据模型（含 EdgeType）

---

## 1. 架构总览

### 1.1 完整 Pipeline 流程图

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          知识图谱 Pipeline 全景                                    │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────────────────────┐ │
│  │ POST /upload │───▶│ _run_resource_   │───▶│ ingest_document_resource()       │ │
│  │              │    │ ingestion()      │    │   (document_ingestion.py)        │ │
│  └──────────────┘    └──────────────────┘    └──────────┬──────────────────────┘ │
│                                                         │                         │
│                              ┌──────────────────────────┼──────────────────────┐ │
│                              │    enable_new_pipeline   │   legacy pipeline    │ │
│                              │    && subject != None     │   (逐块分类)          │ │
│                              ▼                          ▼                      │ │
│         ┌────────────────────────────────┐  ┌───────────────────────┐         │ │
│         │ _run_structured_ingestion()    │  │ _classify_chunk() × N │         │ │
│         │                                │  │ + graph_search agent  │         │ │
│         │ ┌────────────────────────────┐ │  │ + deduplicate_title   │         │ │
│         │ │ Phase 1: _fast_document_   │ │  └───────────┬───────────┘         │ │
│         │ │ scan()                     │ │              │                     │ │
│         │ │  → 全文档扫描，识别 blocks  │ │              ▼                     │ │
│         │ │  → 学科分流策略             │ │  ┌───────────────────────┐         │ │
│         │ └──────────┬─────────────────┘ │  │ create_resource_level_ │         │ │
│         │            │                    │  │ proposals()           │         │ │
│         │            ▼                    │  │  → 候选聚类            │         │ │
│         │ ┌────────────────────────────┐ │  │  → 创建 GraphProposal │         │ │
│         │ │ _process_topic_block() × N │ │  └───────────────────────┘         │ │
│         │ │  → 并行为每个 block 提取   │ │                                      │ │
│         │ │    知识点标题               │ │                                      │ │
│         │ └──────────┬─────────────────┘ │                                      │ │
│         │            │                    │                                      │ │
│         │            ▼                    │                                      │ │
│         │ ┌────────────────────────────┐ │                                      │ │
│         │ │ _batch_organize_topic_tree │ │                                      │ │
│         │ │  → 树形组织结构化分组      │ │                                      │ │
│         │ │ _create_relay_and_attach() │ │                                      │ │
│         │ │  → 创建中继节点            │ │                                       │ │
│         │ └──────────┬─────────────────┘ │                                      │ │
│         │            │                    │                                      │ │
│         │            ▼                    │                                      │ │
│         │ ┌────────────────────────────┐ │                                      │ │
│         │ │ Phase 2: GraphLocator      │ │                                      │ │
│         │ │  cluster_into_relays()     │ │                                      │ │
│         │ │  locate() × N              │ │                                      │ │
│         │ │  → 精确定位 + 创建节点     │ │                                      │ │
│         │ │  create_graph_proposal()   │ │                                      │ │
│         │ │  approve_graph_proposal()  │ │                                      │ │
│         │ └──────────┬─────────────────┘ │                                      │ │
│         │            │                    │                                      │ │
│         │            ▼                    ▼                                      │ │
│         │ ┌────────────────────────────────────────┐                            │ │
│         │ │ _build_segments_from_scan()            │                            │ │
│         │ │  → 生成 ResourceSegment 列表            │                            │ │
│         │ │ replace_resource_segments()            │                            │ │
│         │ │  → 写入数据库                          │                            │ │
│         │ └────────────────────────────────────────┘                            │ │
│         └────────────────────────────────────────────────────────────────────┘ │
│                                                                                   │
│  最终产出: TopicNode 加入 graph, ResourceSegment 入库, GraphProposal 状态变为 active │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件关系图

```
┌──────────────┐     ┌─────────────────────────┐     ┌──────────────────┐
│   FastAPI App │────▶│   SingleSessionRuntime  │────▶│ SessionBackend   │
│   (app.py)    │     │   (app.py 内部类)        │     │ (session_       │
└──────┬───────┘     └─────────────────────────┘     │  backend.py)     │
       │                                              └────────┬─────────┘
       │ 路由层                                              │ 业务层
       │                                                     │
  ┌────┴─────────────────────────────────────────────────────┴────────┐
  │                                                                    │
  │  POST /v1/knowledge/subject  ──▶ _classify_subject_by_title()     │
  │                                 ──▶ create_graph_proposal_from_    │
  │                                     resource()                    │
  │                                 ──▶ approve_graph_proposal()      │
  │                                                                    │
  │  POST /v1/resource/upload     ──▶ _run_resource_ingestion()       │
  │                                 ──▶ ingest_document_resource()    │
  │                                                                    │
  └────────────────────────────────────────────────────────────────────┘

核心类与函数依赖:
  ingest_document_resource()  _run_structured_ingestion()
  ├── _select_parser()          ├── _fast_document_scan()   ← Phase 1
  ├── _units_to_chunks()        ├── _process_topic_block()  ← 并行提取
  ├── _classify_chunk()         │   └── _extract_topics_from_block_text()
  │   └── GraphSearchAgent      ├── _batch_organize_topic_tree()
  │       .search()             ├── _create_relay_and_attach()  ← 中继节点
  │                             ├── GraphLocator               ← Phase 2
  │                             │   .cluster_into_relays()
  │                             │   .locate()
  │                             │   .refresh()
  │                             └── _build_segments_from_scan()
```

### 1.3 数据模型说明

#### TopicNode (`src/core/models.py:14`)

```python
class TopicNode(BaseModel):
    topic_id: str             # 唯一标识，如 "auto_现在进行时"
    title: str                # 知识点标题
    difficulty: int           # 难度 1-5
    parent_ids: list[str]     # 层级归属（parent→child 关系，边类型由 edge_type 决定）
    prerequisite_ids: list[str]  # 前置依赖（requires 关系：必须先学这些才能学本节点）
    tags: list[str]           # 标签列表，如 ["subject:language", "facet:grammar", "language:english"]
```

**设计要点**:
- `parent_ids` 与 `prerequisite_ids` 是两条正交的维度：前者表达层级树结构，后者表达学习依赖顺序。
- `tags` 是实现多学科隔离的核心，以 `subject:xxx` 区分命名空间，`facet:root` 标记根节点，`language:xxx` 标记语言实例。

#### GraphProposalRecord (`src/core/models.py:91`)

```python
class GraphProposalRecord(BaseModel):
    proposal_id: str             # 唯一标识
    title: str                   # 提案标题（即知识点名）
    summary: str                 # 摘要
    trigger: str                 # 触发源，如 "resource_ingest"
    tags: list[str]              # 标签（与 TopicNode 同结构）
    parent_node_ids: list[str]   # 父节点 ID
    prerequisite_node_ids: list[str]  # 前置节点 ID
    pending_parent_proposal_ids: list[str]  # 等待审批的父 Proposal ID
    edge_type: str               # 边类型（requires / part_of / related 等）
    status: str                  # proposed → validated → shadow → active (或 rejected)
    reason: str                  # 原因说明
    created_topic_id: str | None # 批准后分配的 TopicNode ID
    observation_count: int       # Shadow 周期观察计数
    created_ts: str
    updated_ts: str
```

**生命周期状态机**:
```
proposed ──▶ validated ──▶ shadow ──▶ active
   │            │           │
   ▼            ▼           ▼
rejected    rejected     rejected
```

- `pending_parent_proposal_ids`: 当父节点本身也是 Proposal（尚未批准为 TopicNode）时，暂存其 ID。一旦父 Proposal 获批为 TopicNode，系统会通过 `_propagate_approved_parent_to_child_proposals()` 自动补全子节点对父节点的引用。

#### ResourceSegment (`src/core/models.py:55`)

```python
class ResourceSegment(BaseModel):
    segment_id: str                         # 唯一标识
    start_ms: int                           # 起始毫秒（资源内位置）
    end_ms: int | None                      # 结束毫秒
    label: str                              # 标签，如 "chunk"
    status: str                             # classified / proposed / unclassified
    sequence_index: int                     # 片段序号
    text: str | None                        # 片段文本
    locator: dict[str, Any]                 # 定位器，如 {"kind":"pdf","page_start":1}
    topic_id: str | None                    # 匹配到的知识点 ID
    proposal_id: str | None                 # 挂靠的提案 ID
    proposed_topic_title: str | None        # LLM 提议的知识点标题
    proposed_parent_node_ids: list[str]     # LLM 提议的父节点
    decision: str                           # link / propose / unclassified
    confidence: float                       # 置信度 0-1
    reason: str                             # 决策原因
    guiding_question: str | None            # 引导问题
    teaching_hint: str | None               # 教学提示
```

**决策字段 `decision` 的语义**:

| 值 | 含义 |
|---|---|
| `link` | 已成功映射到已有 TopicNode (`topic_id` 非空) |
| `propose` | 提议创建新节点 (`proposal_id` 或 `proposed_topic_title` 非空) |
| `unclassified` | 未能分类（文本内容不包含可提取的知识点） |

---

## 2. 学科管理

### 2.1 POST /v1/knowledge/subject 端点

**入口**: `src/api/app.py:846`

```python
@app.post("/v1/knowledge/subject", tags=["knowledge"])
def create_subject_root(
    title: str = Form(...),
) -> dict[str, Any]:
```

**功能**: 接收前端传入的学科名称（如 "数学"、"英语"、"物理"），创建该学科的根节点（root node）。

**处理流程**:

1. 调用 `_classify_subject_by_title(backend, title)` 进行学科分类
2. 生成 tags: `[f"subject:{subject}", "facet:root"]`，若为语言学科且检测到语言实例，追加 `language:{language_id}`
3. 通过 `create_graph_proposal_from_resource()` 创建根节点 Proposal
4. 立即调用 `approve_graph_proposal()` 批准
5. 返回 `{topic_id, title, tags}`

### 2.2 _classify_subject_by_title 的学科命名空间隔离机制

**函数**: `src/api/app.py:811`

```python
def _classify_subject_by_title(backend: SessionBackend, title: str) -> tuple[str, str | None]:
```

**隔离机制**:

1. **Slugify**: 对标题做规范化处理——去除非字母数字/汉字的字符，转小写，截取前 20 字符。作为 `subject` 的唯一 key。
2. **语言检测**: 仅对标题中包含语言关键词（"英语"、"语文"、"english" 等）的输入使用 LLM 判断具体语言实例（english / chinese / japanese / korean）。若是语言学科，返回 `("language", language_id)`。
3. **非语言学科**: 直接使用 slug 作为 subject key，**不调用 LLM**。例如输入 "物理" → `("物理", None)`。

### 2.3 为什么用用户输入的学科名作为唯一 subject key 而非预设分类

**设计考量**:

- **开放性**: 预设学科列表（如 `SUBJECT_PROFILES` 中定义的 math/science/physics 等）仅覆盖常见学科。用户可能上传校本科目的资源（如"围棋"、"编程"），预设分类无法穷举。
- **命名空间隔离**: 每个 subject key 对应一个独立的图谱命名空间。`subject:` tag 前缀确保不同学科的知识节点不会互相干扰。
- **向后兼容**: 通过 `_canonical_subject()` 将 `english` / `chinese` 归一到 `language`，保证历史数据与新数据的兼容。
- **预设 Profile**: `SUBJECT_PROFILES` 中的预定义学科（`src/services/resource_graph_curation.py:72`）仍然发挥作用——它们提供 facets 分类规则、标记词典和边类型策略。用户自创学科可以 fallback 到 `"general"` profile。

---

## 3. 文档分析阶段（Phase 1）

### 3.1 _fast_document_scan 的学科分流策略

**函数**: `src/services/document_ingestion.py:1000`

```python
def _fast_document_scan(
    backend: SessionBackend,
    chunks: list[TextUnit],
    subject: str,
    language_id: str | None = None,
) -> dict:
```

**功能**: 单次 LLM 调用完成对整份文档的结构化分析。根据 `subject` 选择不同的 System Prompt，实现学科分流：

| 条件 | 分流策略 | 支持的 block 类型 |
|---|---|---|
| `subject="language"` + `language_id="english"` | 英语教材分析 | `grammar_point`, `vocabulary_theme`, `pronunciation`, `reading`, `functional_expression`, `word_list`, `exercise_only` |
| `subject="language"` + `language_id="chinese"` | 语文教材分析 | `character_learning`, `poetry`, `reading_comprehension`, `writing`, `language_point`, `word_list`, `exercise_only` |
| 其他所有学科 | 通用教学文档分析 | `topic_area`, `exercise_only`, `fuzzy`, `word_list`, `appendix` |

**文档截断处理**: 若全文超过 24,000 字符，取前 12,000 + 后 12,000 字符拼接，中间用省略标记分隔。

**返回格式**:
```json
{
  "doc_type": "textbook",
  "blocks": [
    {
      "label": "Unit 1 - Present Continuous",
      "summary": "现在进行时的用法和例句",
      "type": "grammar_point",
      "start_marker": "Unit 1",
      "end_marker": "Unit 2"
    }
  ]
}
```

### 3.2 各学科的分块类型和提取规则

#### 英语 (language / english)

| Block 类型 | 提取内容 | 知识点示例 |
|---|---|---|
| `grammar_point` | 语法知识点 | "现在进行时"、"情态动词 must" |
| `vocabulary_theme` | 词汇主题 | "天气词汇"、"动物词汇" |
| `pronunciation` | 发音规则 | "a_e /eɪ/"、"aw /ɔː/" |
| `reading` | 课文阅读理解 | "英语故事阅读理解" |
| `functional_expression` | 功能句型 | "表达喜好"、"电话用语" |
| `word_list` | 单词表（跳过） | — |
| `exercise_only` | 练习题（仅记录） | — |

#### 语文 (language / chinese)

| Block 类型 | 提取内容 | 知识点示例 |
|---|---|---|
| `character_learning` | 生字识字 | "会认字:山水火" |
| `poetry` | 古诗词 | "《静夜思》" |
| `reading_comprehension` | 课文理解 | "课文中心思想" |
| `writing` | 写作练习 | "看图写话"、"日记" |
| `language_point` | 语言知识点 | "比喻"、"排比" |
| `word_list` | 生字表（跳过） | — |
| `exercise_only` | 练习题（仅记录） | — |

#### 理科 (math, physics, chemistry, biology, science, history, geography)

| Block 类型 | 提取内容 | 知识点示例 |
|---|---|---|
| `topic_area` | 知识域 | "牛顿第一定律"、"分数的加减法" |
| `exercise_only` | 练习题（仅记录） | — |
| `fuzzy` | 模糊段落（可能触发精读） | — |
| `word_list` / `appendix` | 附属材料（跳过） | — |

### 3.3 中继节点（relay node）的聚类逻辑

**函数**: `src/services/document_ingestion.py:742`

```python
def _batch_organize_topic_tree(
    *, backend, candidates: list[str], subject: str, language_id: str | None = None,
) -> list[dict]:
```

**功能**: 在知识点提取完成后（`_process_topic_block` 做完），将所有候选标题送入 LLM，要求组织为树形分组结构。

**规则**:
1. 中继节点标题必须以 `[中继]` 结尾，与叶子节点区分
2. 每个输入的关键词必须在树中出现一次（不丢失、不凭空创建）
3. 同级概念平铺在同一中继下
4. 对语言学科提供分组提示（英语按语法/词汇/发音/阅读/写作/功能句型分组；语文按识字/古诗词/阅读理解/写作/语言知识点分组）

**返回格式**:
```json
[
  {
    "title": "英语语法[中继]",
    "children": [
      {"title": "现在进行时", "children": []},
      {"title": "一般过去时", "children": []}
    ]
  },
  {
    "title": "英语词汇[中继]",
    "children": [
      {"title": "天气词汇与天气表达", "children": []},
      {"title": "规则词汇与表达", "children": []}
    ]
  }
]
```

**中继节点的创建时机**: 中继节点通过 `_create_relay_and_attach()` 立即创建并批准（见第4.4节）。中继节点只在实际有子节点时才创建，叶子节点留给 Phase 2 的 GraphLocator 处理。

---

## 4. 知识点定位阶段（Phase 2）

### 4.1 GraphLocator 的 locate() 方法

**类**: `src/services/graph_locator.py:22`

```python
class GraphLocator:
    def __init__(self, backend: SessionBackend, subject: str, language_id: str | None = None):
        self._backend = backend
        self._subject = subject
        self._language_id = language_id
        self._topics_cache: list[TopicNode] | None = None  # 惰性加载

    def locate(self, topic_title: str, topic_desc: str = "") -> GraphPosition:
```

**返回值** (`GraphPosition`):
```python
@dataclass
class GraphPosition:
    exists: bool                         # 是否在图谱中已存在
    node_id: str | None                  # 已存在节点的 ID
    parent_ids: list[str]                # 推荐的父节点 ID
    successor_ids: list[str]             # 推荐的后继节点 ID（即本节点应是哪些节点的前置）
    reason: str                          # 定位原因
```

**定位逻辑（两阶段）**:

**阶段 A — 确定性精确标题匹配（无 LLM 调用）**:
1. 将候选标题转小写
2. 遍历所有已知 TopicNode，精确比较标题字符串
3. 如果匹配到，立即返回 `exists=True`，`parent_ids` 和 `successor_ids` 从匹配节点的已有关系中提取
4. 这是去重的第一道防线，零成本

**阶段 B — LLM 辅助定位（仅精确匹配失败时）**:
1. 调用 `_build_graph_snapshot()` 生成当前图谱的紧凑快照
2. 快照格式: `[[id, title, [前置id列表], [后继id列表]], ...]`
3. 将快照 + 新 topic 信息送入 LLM
4. LLM 判断是否存在语义等价的节点，或推荐应放在图中的什么位置
5. 返回 `GraphPosition`，包含推荐的 `parent_ids` 和 `successor_ids`

### 4.2 图快照的 subject 隔离机制

**函数**: `GraphLocator._build_graph_snapshot():236`

```python
def _build_graph_snapshot(self) -> str:
    topic_ids = {t.topic_id for t in self._topics}
    same_subject = [
        t for t in self._topics
        if self._subject is None
        or any(tag == f"subject:{self._subject}" for tag in t.tags)
        or not any(tag.startswith("subject:") for tag in t.tags)  # 无 subject tag 的 legacy 节点
    ]
    if not same_subject:
        same_subject = list(self._topics)  # fallback
    ...
```

**隔离规则**:
1. 只收集带有 `subject:{当前学科}` tag 的节点
2. 兼容无 subject tag 的 legacy 节点（允许它们在所有学科中可见）
3. 如果同 subject 节点为空，fallback 到全部节点
4. 生成的快照仅包含 `[topic_id, title, parent_ids, successor_ids]`

**为什么需要隔离**: 防止 LLM 将物理学的"速度"概念挂到英语的"阅读速度"节点下。同时确保 GraphLocator 提示词中的节点列表可控（避免 token 溢出）。

### 4.3 parent_ids 和 prerequisite_for_ids（successor_ids）的语义

在 `GraphPosition` 中：

- **`parent_ids`**: 新知识点应挂在哪些已有节点**下面**（层级归属）。这意味着新节点是 parent 的子节点。创建 Proposal 时，`parent_node_ids` 字段将填入这些值。
- **`successor_ids`**（也称 `prerequisite_for_ids`）: 哪些已有知识点**依赖**这个新知识点。这意味着新节点是已有节点的前置。创建 Proposal 时，`prerequisite_node_ids` 字段将填入这些值。

**实际使用**（`_run_structured_ingestion:958`）:
```python
parents = [pid for pid in pos.parent_ids if pid in topic_map.values()]
if not parents and root_topic_id:
    parents = [root_topic_id]  # 至少挂在根节点下

successors = [pid for pid in pos.successor_ids
              if pid in topic_map.values() and pid != root_topic_id]

proposal = backend.create_graph_proposal_from_resource(
    title=title, summary=desc,
    parent_node_ids=parents,           # ← parent_ids 语义
    prerequisite_node_ids=successors,  # ← successor_ids 语义（倒置）
    ...
)
```

**注意**: 这里存在语义"倒置"——GraphPosition 返回的 `successor_ids` 被赋值到了 Proposal 的 `prerequisite_node_ids` 字段。设计原因为：LLM 输出"哪些已有节点应该是新节点的后继"，而图数据库存储的是"新节点依赖哪些已有节点（前置）"。

### 4.4 中继节点的创建时机

**函数**: `_create_relay_and_attach()` (`document_ingestion.py:786`)

中继节点在 **两个时机** 被创建：

1. **Batch Tree Organization 阶段**（`_run_structured_ingestion:913`）: 
   `_batch_organize_topic_tree()` 返回树形结构后，遍历树，对每个含子节点的 `[中继]` 节点调用 `_create_relay_and_attach()`。此时没有 GraphLocator 参与。

2. **GraphLocator cluster_into_relays 阶段**（`_run_structured_ingestion:937`）:
   对于未被 `_batch_organize_topic_tree` 覆盖的候选（标题数 > 2 时），调用 `locator.cluster_into_relays(all_titles)` 再次聚类，结果同样传给 `_create_relay_and_attach()`。

**中继节点的关键属性**:
- `tags` 包含 `subject:{学科}`, `facet:{profile.default_facet}`, 以及 language tag
- `edge_type` 为 `"part_of"`（表示子节点是 relay 的组成部分）
- 创建后**立即调用 `approve_graph_proposal()` 批准**——不需要人工审核
- 中继节点自身可能嵌套（树结构递归创建）

---

## 5. 去重与防重复机制

整个 Pipeline 实现了**四层去重**，从确定性到语义性逐步升级。

### 5.1 精确标题匹配（确定性，无 LLM 调用）

**位置**: `graph_locator.py:48-57`

```python
title_lower = topic_title.strip().lower()
for topic in self._topics:
    if topic.title.strip().lower() == title_lower:
        return GraphPosition(exists=True, node_id=topic.topic_id, ...)
```

**原理**: 在调用 LLM 之前，先做 O(n) 的字符串精确比较（忽略大小写和前导/尾随空格）。匹配即返回，完全不消耗 LLM token。这是最快速、最便宜的去重手段。

### 5.2 同批次内去重

**位置**: `document_ingestion.py:909`

```python
seen: set[str] = set()
deduped = [(t, d) for t, d in all_topics if not (t in seen or seen.add(t))]
```

**原理**: 同一份文档的多个 block 可能提取出相同标题的知识点（如多个单元都涉及"现在进行时"）。用 Python set 做内存去重，保留首次出现的。

**此外**: `GraphSearchAgent.search()` 在 Phase 2 前也会尝试 Link 到已有节点（`document_ingestion.py:399-403`），如果搜索到匹配且 confidence ≥ 0.55，则将 decision 从 "propose" 改为 "link"。

### 5.3 跨上传去重

**位置**: `document_ingestion.py:417-468`（语义消歧阶段）

```python
from src.services.resource_graph_curation import deduplicate_candidate_title
matched_id = deduplicate_candidate_title(
    backend=backend,
    candidate_title=proposed_topic_title,
    candidate_subject=subject,
    candidate_facet="",
    candidate_text=text,
    candidate_language_id=language_id,
    existing_nodes=existing,  # 包含所有已存在的 TopicNode + 活跃 Proposal
)
```

**原理**:

1. 收集所有已有节点（包含已批准的 TopicNode + 活跃的 GraphProposal）
2. 对候选标题做粗筛：过滤到同 subject 的节点
3. 调用 LLM（`deduplicate_candidate_title` 函数）判断候选概念是否与已有节点"本质相同"
   - 本质相同：同一学术概念的不同叫法、简繁表述（如"现在进行时" vs "Present Continuous"）
   - 不同概念：不同维度、不同学术范畴、粒度差异显著
4. 如果 LLM 返回匹配，则将 matched_id 用于 link；否则继续 propose

**匹配键设计**（`resource_graph_curation.py:1310-1317`）:

```python
def _topic_match_key(topic: TopicNode) -> tuple[str, str | None, str, str]:
    subject = _infer_topic_subject(topic)
    facet = _infer_topic_facet(...)
    language_id = _language_id_from_tags(...)
    normalized = normalize_candidate_title(topic.title, ...)
    return (subject, language_id, facet, normalized)
```

同一 `(学科, 语言, facet, 规范化标题)` 组合被认为是同一概念。

### 5.4 自引用防护

**位置**: `session_backend.py:354-360`（在 `approve_graph_proposal` 中）

```python
prerequisite_ids=list(dict.fromkeys(
    pid for pid in (
        *(approved_parents if approved_edge_type == "requires" else []),
        *(p for p in getattr(proposal, "prerequisite_node_ids", []) if p in valid_topic_ids)
    )
    if pid != created_topic_id  # never self-reference
))
```

**位置**: `graph_locator.py:205`（在 `review_placements` 的审核提示中）

```
4. 自引用：节点引用自己作为 parent 或 prerequisite_for
```

**原理**: 一个节点不应该以自己为前置依赖，也不应该以自己为父节点。代码中在创建 TopicNode 和更新 prerequisite_ids 时均检查并过滤 `pid != created_topic_id`。

---

## 6. 自动批准与缓存刷新

### 6.1 为什么创建后立即批准

**调用链** (`_run_structured_ingestion:963-979`):

```python
proposal = backend.create_graph_proposal_from_resource(
    title=title, summary=desc[:200],
    tags=_proposal_tags(subject=subject, ...),
    parent_node_ids=parents,
    prerequisite_node_ids=successors,
    edge_type="part_of" if parents else "requires",
    reason=pos.reason[:80],
)
_st, _pr, tpc, _, _ = backend.approve_graph_proposal(
    proposal_id=proposal.proposal_id, difficulty=1,
)
topic_map[title] = tpc.topic_id
locator.refresh()
```

**立即批准的原因**:

1. **Pipeline 内批处理的确定性**: 文档摄入是一个自动化批处理流程。中继节点、叶子节点都由 LLM 提议，无需人工审核即进入图谱。
2. **后续节点依赖已批准节点**: 同一批次中，后处理的叶子节点需要引用先创建的 relay 节点作为 parent。如果不立即批准，后续节点的 parent_ids 将无法解析。
3. **Segment 关联的及时性**: 批准后 `_relink_segments_for_approved_proposal()` 会将所有引用 `proposal_id` 的 segment 转为 `status="classified"`，`topic_id` 指向新节点。
4. **自动扩展**: 批准还触发 `_rescan_segments_for_topic()`，扫描所有 segment 中尚未分类的部分，尝试匹配到新批准的 topic。

**特殊处理 — subject root**: `POST /v1/knowledge/subject` 端点同样在创建 root proposal 后立即批准，确保学科根节点立即可用。

### 6.2 locator.refresh() 的作用和时机

**函数**: `graph_locator.py:233`

```python
def refresh(self) -> None:
    self._topics_cache = None
```

**作用**: 清空 `_topics_cache`，强制下次访问 `._topics` 属性时重新从 SessionBackend 加载最新状态。

**调用时机**:

1. **创建 relay 节点后** (`document_ingestion.py:947`): `cluster_into_relays` → `_create_relay_and_attach` 后立即 refresh，确保后续 `locate()` 调用能看到新 relay 节点。
2. **每个叶子节点批准后** (`document_ingestion.py:979`): 新节点加入图谱后 refresh，确保下一个同层节点能感知到刚创建的节点，从而正确建立层级和前置关系。

**为什么需要 refresh**: `GraphLocator` 采用惰性加载策略（`self._topics_cache`），创建新的 TopicNode 后若不清缓存，LLM 定位时将无法看到新节点，导致同一批次内的节点无法互相引用。

---

## 7. 边类型语义

### 7.1 parent_ids（层级归属）vs prerequisite_ids（前置依赖）

| 字段 | 语义 | 图含义 | 学习含义 |
|---|---|---|---|
| `parent_ids` | 层级归属 | parent → child (树结构) | "A 是 B 的分类/父概念" |
| `prerequisite_ids` | 前置依赖 | prereq → dependent (DAG) | "必须先学 A 才能学 B" |

**存储形式**:
- `parent_ids`: TopicNode 字段，表示本节点的直接父节点列表
- `prerequisite_ids`: TopicNode 字段，表示本节点的直接前置节点列表

**图结构示例**:
```
        数学[facet:root]           ← parent of everything below
        /    |    \
     代数    几何    统计
    /  \     /  \
  加法 减法 点  线段
  (prerequisite: 加法 → 乘法)     ← prereq 边可以跨树分支
```

### 7.2 edge_type 的取值和含义

**定义**: `src/agent/models.py:9`

```python
class EdgeType(str, Enum):
    REQUIRES = "requires"           # 前置依赖：A 必须在 B 之前学习
    SUPPORTS = "supports"           # 辅助支撑
    RELATED = "related"             # 相关但不分先后
    PART_OF = "part_of"             # 组成部分（父子层级关系）
    DERIVED_FROM = "derived_from"   # 推导自
    DEFINES = "defines"             # 定义关系
    EXPLAINS = "explains"           # 解释关系
    EVIDENCE_FOR = "evidence_for"   # 证据支撑
    CAUSES = "causes"               # 因果关系
    USES = "uses"                   # 使用关系
    FORMULA_USES_QUANTITY = "formula_uses_quantity"  # 公式使用量
```

**各学科的默认 edge_type**:

| 学科 | 默认 edge_type | 说明 |
|---|---|---|
| language | `related` | 语言知识点间多为并列/关联关系 |
| math | `requires` | 数学有明显的先决条件链 |
| science/physics/chemistry/biology | `related` | 科学知识点多为相关而非严格依赖 |
| history/geography | `related` | 文史知识点关联 |

**具体 facet 的 edge_type 策略** (在 `_pick_edge_type` 中，`resource_graph_curation.py:1001`):

| Facet | Edge Type | 含义 |
|---|---|---|
| `formula`, `quantity`, `theorem_or_rule` | `defines` | 公式/定理定义了量之间的关系 |
| `experiment` | `evidence_for` | 实验为理论提供证据 |
| `phenomenon`, `model`, `reading`, `writing`, `culture` | `explains` | 模型/阅读解释现象 |
| `cause_effect` | `causes` | 因果链 |
| `method`, `application`, `functional_expression` | `uses` | 方法/功能句型使用概念 |
| `operation`, `grammar`, `vocabulary`, `pronunciation`, `concept`, `event`, `person`, `place`, `map_skill` | `part_of` | 属于某个更大概念的一部分 |

### 7.3 approval 时两类边的写入逻辑

**函数**: `session_backend.py:301`

```python
def approve_graph_proposal(
    self, *, proposal_id: str, parent_node_ids: list[str] | None = None,
    edge_type: str | None = None, difficulty: int = 1, ...
) -> tuple[AppState, GraphProposalRecord, TopicNode, int, int]:
```

**核心逻辑**（`session_backend.py:348-378`）:

```python
if topic is None:
    topic = TopicNode(
        ...
        parent_ids=list(approved_parents) if approved_edge_type != "requires" else [],
        prerequisite_ids=list(dict.fromkeys(
            pid for pid in (
                *(approved_parents if approved_edge_type == "requires" else []),
                *(p for p in getattr(proposal, "prerequisite_node_ids", []) if p in valid_topic_ids)
            )
            if pid != created_topic_id
        )),
        ...
    )
else:
    if approved_edge_type == "requires":
        topic.prerequisite_ids = list(dict.fromkeys([...approved_parents]))
    else:
        topic.parent_ids = list(dict.fromkeys([...approved_parents]))
```

**写入规则**:

1. **新建 TopicNode 时**:
   - 若 `edge_type == "requires"`: `approved_parents` → `prerequisite_ids`（将 parent 视为前置依赖），`parent_ids` 为空
   - 若 `edge_type != "requires"`（如 `part_of`）: `approved_parents` → `parent_ids`（作为层级父节点）

2. **更新已有 TopicNode 时**:
   - 若 `edge_type == "requires"`: 追加到 `prerequisite_ids`
   - 否则: 追加到 `parent_ids`
   - 总是合并 proposal 自带的 `prerequisite_node_ids` 到 topic 的 `prerequisite_ids`

3. **自引用防护**: 始终保持 `pid != created_topic_id` 的检查

---

## 8. 前端测试页

### 8.1 学科卡片 UI

前端测试页面 (`docs/api/resource_graph_test.html`) 提供：

- **学科选择卡片**: 展示预设学科（数学、英语、物理等）和自定义学科输入
- **学科创建按钮**: 调用 `POST /v1/knowledge/subject`，创建学科根节点
- **已创建学科列表**: 从 `/v1/knowledge/graph` 获取全部 topic，按 `subject:` tag 分组展示
- **学科 Root 节点展示**: 以醒目标签展示 `facet:root` 节点

### 8.2 Canvas 力导向图

前端使用 **D3-force** 在 HTML5 Canvas 上渲染知识图谱的力导向布局：

- **节点**: 每个 TopicNode 显示为一个圆形，面积按 degree（连接数）缩放
- **颜色**: 按 `subject:` tag 着色（数学=蓝, 英语=绿, 物理=红, 等）
- **边**: 
  - `parent_ids` 边为**实线**（表示层级归属）
  - `prerequisite_ids` 边为**虚线**（表示前置依赖）
- **交互**: 
  - 拖拽节点：调整布局
  - 悬停：显示 tooltip（title, tags, difficulty）
  - 滚轮缩放

**数据来源**: `GET /v1/knowledge/graph` → `{topics, proposals, mastery}`

### 8.3 rootSelect 过滤器

- **下拉选择器**: 筛选当前显示的学科 root 节点
- **联动逻辑**: 选择学科 root 后，图谱仅显示该 root 节点下的子树（通过 `parent_ids` / `prerequisite_ids` 的 BFS 遍历）
- **全部显示**: 选项 "All" 显示整个图谱

### 8.4 上传流程

1. **选择学科 root**: 从下拉列表选择目标学科根节点，获得 `topic_id`
2. **选择文件**: 支持 PDF、DOCX、TXT 格式
3. **输入资源名称**: 与学科关联的显示名
4. **选择 category**: learn / review
5. **可选参数**: subject（覆盖默认学科），language_id（语言实例）
6. **提交**: 调用 `POST /v1/resource/upload`（FormData），包含 file + topic_id + resource_name + category + subject + language_id
7. **异步处理**: 上传后立即返回资源信息，后台线程执行 `_run_resource_ingestion`
8. **轮询状态**: 前端通过 `GET /v1/resource/{id}/ingestion-status` 轮询 ingestion 进度
9. **刷新图谱**: 摄入完成后刷新图谱视图，查看新创建的节点和边

**关键后端代码**:
```python
# app.py:641-702
def _run_resource_ingestion(*, resource_id, default_topic_id, subject, language_id):
    topics = backend.load_app_state(include_history=False).curriculum.topics
    segments = ingest_document_resource(
        backend=backend, record=record, topics=topics,
        default_topic_id=default_topic_id,
        subject=subject, language_id=language_id,
        enable_graph_search=not bool(subject),
        enable_new_pipeline=bool(subject),
    )
    backend.update_resource_ingestion(resource_id, status="completed")
```

**参数说明**:
- `enable_graph_search=not bool(subject)`: 当未指定 subject 时，回退到老 pipeline 的逐块分类 + GraphSearchAgent 模式
- `enable_new_pipeline=bool(subject)`: 当指定 subject 时，启用两步法结构化摄入（Phase 1 扫描 + Phase 2 定位）
