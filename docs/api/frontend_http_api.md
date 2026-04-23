# Frontend HTTP API v1.2 (Single Session)

本版本按产品约束收敛为**单会话模式**，并补齐 P0 能力：

- 单会话（固定 `session_id=default`）
- 事务性状态存储（SQLite）
- 记忆事件按需加载（游标分页）
- 文本输入长度限制
- 实时语音播放通道（流式输出 + 打断）

## Run

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8090 --reload
```

- Swagger UI: `http://127.0.0.1:8090/docs`
- OpenAPI JSON: `http://127.0.0.1:8090/openapi.json`

## Key conventions

- 单会话固定：`session_id=default`
- `turn_id` 形如 `turn_000001`
- 事件游标：请求 `after`，响应 `next_cursor`
- 时间格式：ISO-8601（UTC）

## Limits and env

- `API_TEXT_MAX_CHARS`：文本最大长度（默认 `128`，硬上限 `8192`）
- `API_AUDIO_MAX_BYTES`：音频上传字节上限（默认 `5242880`，即 5MB）
- `STATE_DB_FILE`：状态数据库路径（默认按 `STATE_FILE` 推导）
- `HISTORY_TAIL_LIMIT`：`/state` 返回的最近事件条数上限（默认 `200`）

## Transaction storage

后端状态与事件写入 SQLite：

- `app_state`：学习状态快照（事务更新）
- `learning_events`：事件日志（自增游标）

设计目的：

- 防止 JSON 文件并发覆盖
- 支持事件按需分页读取
- 长会话下避免一次性加载全部历史

## Endpoints (canonical)

### System

- `GET /health`

### Session state and turns

- `GET /v1/session/state`
- `POST /v1/session/input/text`
- `POST /v1/session/input/audio`
- `POST /v1/session/input/audio/sentence`（句级实时上传）
- `GET /v1/session/events?after=0&limit=50`

### Review / graph / mastery / explore

- `POST /v1/session/review/push`
- `GET /v1/session/review-queue`
- `GET /v1/knowledge/graph`
- `GET /v1/session/mastery`
- `GET /v1/session/explore-window`
- `POST /v1/session/explore-window/open`
- `POST /v1/session/explore-window/close`

### Realtime audio output (stream + interrupt)

- `POST /v1/session/input/text/realtime`
- `POST /v1/session/input/audio/sentence`
- `GET /v1/session/output/audio/stream/{stream_id}`
- `POST /v1/session/output/audio/interrupt/{stream_id}`

说明：

1. 先调用 `input/text/realtime`，拿 `stream_id`。
2. 前端立即拉 `output/audio/stream/{stream_id}` 并边播边收。
3. 若用户打断，调用 `interrupt/{stream_id}`。

## Request / response notes

### Text turn

请求：

```json
{
  "text": "恐龙为什么会灭绝？"
}
```

返回关键字段：

- `turn_id`
- `reply_text`
- `reply_audio_base64`（普通模式）
- `events_cursor`

### Audio turn

`multipart/form-data`：

- `file`：音频文件

返回包含：

- `recognized_text`
- 其他字段同 `TurnResponse`

### Event polling

- `after`：从该游标之后读取
- `limit`：请求条数，内部裁剪到 `1..200`

常见事件：

- `api_turn_completed`
- `review_topic_pushed`
- `explore_window_opened`
- `explore_window_closed`
- 学习引擎事件（如 `mastery_update`、`graph_proposal`、`topic_transition`）

## Errors

- `400`：空文本/空音频/文本超长
- `413`：音频超过上限
- `404`：流式 `stream_id` 不存在
- `422`：请求参数校验失败

## Compatibility routes

为兼容旧前端，保留 `/v1/sessions/*` 路径，但仅接受 `session_id=default`。
