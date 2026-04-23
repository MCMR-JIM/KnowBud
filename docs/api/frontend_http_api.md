# Frontend HTTP API v1.1 (Detailed)

本文件是前后端分离模式下的完整 API 对接说明，覆盖会话生命周期、回合输入、事件轮询、掌握度、知识图谱、复习队列、探索时间窗，以及兼容接口。

## Quick start

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8090 --reload
```

- Swagger UI: `http://127.0.0.1:8090/docs`
- OpenAPI JSON: `http://127.0.0.1:8090/openapi.json`

## API scope and route count

当前业务接口共 19 个：

- 新版会话化接口（推荐）：14 个，统一前缀 `/v1/sessions/{session_id}`。
- 兼容接口（legacy）：5 个，统一绑定默认会话 `default`。

## Core conventions

- 时间格式：ISO-8601 字符串（UTC）。
- `session_id` 格式：`sess_<12位hex>`（由后端生成）。
- `turn_id` 格式：`turn_000001`（会话内单调递增）。
- 音频回包：`reply_audio_base64` + `reply_audio_mime`，前端自行解码播放。
- 奖励时间窗是后端状态（`explore_window_until`），前端只展示。
- 事件消费采用游标：`after` + `next_cursor`。

## Error semantics

- `400`：请求语义错误（例如 `text` 为空、音频文件为空）。
- `404`：会话不存在（仅新版会话化接口会返回）。
- `422`：请求体/参数校验失败（FastAPI/Pydantic 自动校验）。

错误响应遵循 FastAPI 默认格式：

```json
{
  "detail": "text cannot be empty"
}
```

## Data models (key fields)

### HealthResponse

- `ok: bool`
- `service: str`
- `version: str`
- `arch_mode: str`

### SessionSummary

- `session_id: str`
- `created_at: str`
- `updated_at: str`
- `turn_count: int`

### SessionStateResponse

- `session_id: str`
- `profile: SessionProfile`
  - `student_id: str`
  - `display_name: str`
  - `locale: str`
- `learning: SessionLearningState`
  - `current_topic_id: str | null`
  - `current_phase: str`
  - `total_score: int`
  - `consecutive_correct: int`
  - `consecutive_wrong: int`
  - `explore_window_until: str | null`
  - `review_queue_size: int`
  - `history_event_count: int`
- `topics: TopicInfo[]`
- `proposals: ProposalInfo[]`
- `mastery: MasteryInfo[]`
- `turn_count: int`
- `events_cursor: int`

### TurnResponse / AudioTurnResponse

- `session_id: str`
- `turn_id: str`
- `user_text: str`
- `reply_text: str`
- `earned_points: int`
- `reply_audio_base64: str | null`
- `reply_audio_mime: str`（默认 `audio/mpeg`）
- `current_topic_id: str | null`
- `current_phase: str`
- `total_score: int`
- `explore_window_until: str | null`
- `events_cursor: int`
- `recognized_text: str`（仅 `AudioTurnResponse`）

### EventListResponse

- `session_id: str`
- `after: int`
- `next_cursor: int`
- `events: EventInfo[]`
  - `event_index: int`
  - `ts: str`
  - `kind: str`
  - `payload: object`

### KnowledgeGraphResponse

- `session_id: str`
- `topics: TopicInfo[]`
- `proposals: ProposalInfo[]`
- `mastery: MasteryInfo[]`

### ExploreWindowResponse

- `session_id: str`
- `explore_window_until: str | null`
- `active: bool`
- `remaining_seconds: int | null`

## Event kinds seen by frontend

前端轮询 `/events` 时，可能看到的事件类型包括：

- `api_turn_completed`（每轮文本/语音提交后写入）
- `review_topic_pushed`
- `explore_window_opened`
- `explore_window_closed`
- 以及学习引擎本身写入的历史事件（如 `mastery_update`、`graph_proposal`、`topic_transition` 等）

## Endpoints (recommended, session-scoped)

### 1) System

#### GET `/health`

返回服务状态和 API 版本。

---

### 2) Session lifecycle

#### POST `/v1/sessions`

创建新会话。

请求体（可选）：

```json
{
  "student_id": "u_001",
  "display_name": "demo",
  "locale": "zh-CN"
}
```

返回：`CreateSessionResponse`（包含 `session` 概要和 `state` 快照）。

#### GET `/v1/sessions`

列出会话：`SessionListResponse`。

#### GET `/v1/sessions/{session_id}/state`

读取会话完整状态快照。

错误：`404`（会话不存在）。

---

### 3) Turns

#### POST `/v1/sessions/{session_id}/turns/text`

请求体：

```json
{
  "text": "恐龙为什么会灭绝？"
}
```

行为：

- `text.strip()` 后为空会返回 `400`。
- 成功后写入 `api_turn_completed` 事件。

返回：`TurnResponse`。

#### POST `/v1/sessions/{session_id}/turns/audio`

`multipart/form-data`，字段：

- `file`: wav/mp3 等音频文件

行为：

- 空文件返回 `400`。
- 后端先 ASR，再走一轮问答，再写入 `api_turn_completed` 事件。

返回：`AudioTurnResponse`（含 `recognized_text`）。

---

### 4) Event polling

#### GET `/v1/sessions/{session_id}/events?after=0&limit=50`

查询参数：

- `after`：起始游标，默认 `0`。
- `limit`：拉取条数，默认 `50`，后端裁剪为 `1..200`。

返回：`EventListResponse`。

轮询建议：

1. 首次用 `after=0`。
2. 使用返回的 `next_cursor` 继续拉取。
3. 遇到空数组也保留 `next_cursor`，继续下一次轮询。

---

### 5) Review queue

#### POST `/v1/sessions/{session_id}/review-queue`

请求体：

```json
{
  "topic_id": "demo_01"
}
```

返回：`PushReviewResponse`。

#### GET `/v1/sessions/{session_id}/review-queue`

返回：`ReviewQueueResponse`（`topics` + `size`）。

---

### 6) Knowledge and mastery

#### GET `/v1/sessions/{session_id}/graph`

返回当前知识网视图：`KnowledgeGraphResponse`。

#### GET `/v1/sessions/{session_id}/mastery`

返回掌握度列表：`MasteryListResponse`。

---

### 7) Explore window

#### GET `/v1/sessions/{session_id}/explore-window`

返回探索时间窗状态：`ExploreWindowResponse`。

#### POST `/v1/sessions/{session_id}/explore-window/open`

请求体：

```json
{
  "minutes": 5
}
```

约束：`minutes` 范围 `1..120`。

返回：`ExploreWindowResponse`，并写入 `explore_window_opened` 事件。

#### POST `/v1/sessions/{session_id}/explore-window/close`

关闭探索时间窗，返回 `ExploreWindowResponse`，并写入 `explore_window_closed` 事件。

---

## Legacy compatibility endpoints

以下接口保留用于兼容旧前端，统一绑定默认会话 `default`，且会自动创建：

- `GET /v1/session/state`
- `POST /v1/session/input/text`
- `POST /v1/session/input/audio`
- `POST /v1/session/review/push`
- `GET /v1/knowledge/graph`

说明：

- 若新项目接入，建议只使用 `/v1/sessions/*`。
- legacy 与新接口读写的是不同会话命名空间（`default` vs 显式 `session_id`）。

## Recommended frontend flow (production)

1. 调用 `POST /v1/sessions` 创建会话并持久化 `session_id`。
2. 首屏调用 `GET /v1/sessions/{session_id}/state` 渲染当前学习态。
3. 输入走 `turns/text` 或 `turns/audio`。
4. 用 `events` 做增量轮询驱动消息流和状态提示。
5. 家长端通过 `review-queue` 推入复习主题。
6. 进阶页可按需拉 `graph`、`mastery`、`explore-window`。
