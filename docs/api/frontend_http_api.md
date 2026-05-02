# Frontend HTTP API v1.3 (Single Session)

本文档描述当前前端对接的 HTTP API。服务运行于单会话模式，固定 `session_id=default`，面向儿童学习页、家长后台、资源管理和实时音频播放场景。

当前版本重点能力：

- 单会话固定路由与兼容路由并存
- SQLite 事务化状态与事件存储
- 文本/音频输入回合处理
- 实时语音流式播放与打断
- 复习队列、知识图谱、掌握度查询
- 学习资源上传、索引与文件访问
- 探索奖励时间窗控制

## Run

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8090 --reload
```

- Swagger UI: `http://127.0.0.1:8090/docs`
- OpenAPI JSON: `http://127.0.0.1:8090/openapi.json`

## Base Info

- Base URL: `http://127.0.0.1:8090`
- API version prefix: `/v1`
- Current API version string: `1.3.0`
- Default session id: `default`
- Content types:
  - JSON: `application/json`
  - File upload: `multipart/form-data`
  - Audio stream: `audio/mpeg`

## Core conventions

- 单会话固定：`session_id=default`
- 轮次 ID：`turn_000001`、`turn_000002` 这种零填充格式
- 流式音频 ID：`stream_<12位随机十六进制>`
- 事件游标采用递增整数：请求传 `after`，响应返回 `next_cursor`
- 时间字段统一为 ISO-8601 字符串，通常带 UTC 时区
- 当前接口没有统一的业务 `code` 包装，成功和失败都直接返回原始 JSON 或文件流

## Limits and environment variables

### Text and audio

- `API_TEXT_MAX_CHARS`
  - 文本最大长度
  - 默认 `128`
  - 服务端硬上限 `8192`
- `API_AUDIO_MAX_BYTES`
  - 音频上传大小上限
  - 默认 `5242880`，即 5MB
  - 服务端硬上限 25MB

### State and history

- `STATE_DB_FILE`
  - SQLite 状态数据库路径
- `STATE_FILE`
  - 若存在，部分默认路径会从它推导
- `HISTORY_TAIL_LIMIT`
  - `/v1/session/state` 返回最近历史时的内部上限说明
  - 当前状态接口实际返回的是汇总状态，不直接返回完整 history event 列表

### Explore window and graph behavior

- `EXPLORE_WINDOW_COOLDOWN_MINUTES`
  - 探索奖励时间窗关闭后的冷却时长
- `SHADOW_ACTIVATE_OBSERVATION_TURNS`
  - 影子节点晋升为 active 的最少观察轮次
- `SHADOW_ROLLBACK_WRONG_STREAK`
  - 影子节点连续失败回滚阈值

## Storage model

后端状态与事件写入 SQLite，避免 JSON 文件并发覆盖问题。

核心表：

- `app_state`
  - 保存当前学习状态快照
- `learning_events`
  - 保存学习事件日志，支持按游标分页读取
- `resource_library`
  - 保存资源元数据、分段信息与存储路径

设计目的：

- 保证状态更新事务性
- 支持长会话增量读取事件，而不是一次性加载全部历史
- 支持资源库与知识节点绑定

## Response and error format

### Success responses

- 常规接口返回 JSON 对象
- 文件接口返回二进制文件内容
- 音频流接口返回 `audio/mpeg` 流

### Error responses

服务端主要通过 FastAPI `HTTPException` 抛错，错误响应通常为：

```json
{
  "detail": "text cannot be empty"
}
```

请求体验证失败时，FastAPI 返回 `422 Unprocessable Entity`，格式通常为：

```json
{
  "detail": [
    {
      "loc": ["body", "text"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

### Common status codes

- `200 OK`
  - 请求成功
- `400 Bad Request`
  - 业务参数不合法，如空文本、空音频、非法 `category`
- `404 Not Found`
  - `topic_id`、`resource_id`、`stream_id` 不存在，或兼容路由传入了非 `default` 的 `session_id`
- `413 Payload Too Large`
  - 音频文件超过大小上限
- `422 Unprocessable Entity`
  - JSON body、表单字段或 query 参数校验失败
- `500 Internal Server Error`
  - 未捕获的后端内部异常

## Data model summary

### SessionProfile

| Field | Type | Description |
| --- | --- | --- |
| `student_id` | `string` | 学生唯一标识 |
| `display_name` | `string` | 展示名称 |
| `locale` | `string` | 语言区域，默认 `zh-CN` |

### SessionLearningState

| Field | Type | Description |
| --- | --- | --- |
| `current_topic_id` | `string \| null` | 当前学习知识点 ID |
| `current_phase` | `string` | 当前学习阶段 |
| `total_score` | `integer` | 当前累计积分 |
| `consecutive_correct` | `integer` | 连续答对次数 |
| `consecutive_wrong` | `integer` | 连续答错次数 |
| `explore_window_until` | `string \| null` | 当前探索时间窗结束时间 |
| `explore_window_cooldown_until` | `string \| null` | 探索时间窗冷却结束时间 |
| `review_queue_size` | `integer` | 复习队列大小 |
| `history_event_count` | `integer` | 当前累计事件条数 |

### TopicInfo

| Field | Type | Description |
| --- | --- | --- |
| `topic_id` | `string` | 知识点 ID |
| `title` | `string` | 标题 |
| `difficulty` | `integer` | 难度级别 |
| `prerequisite_ids` | `string[]` | 前置知识点 ID 列表 |
| `tags` | `string[]` | 标签列表 |

### ProposalInfo

| Field | Type | Description |
| --- | --- | --- |
| `proposal_id` | `string` | 提案 ID |
| `title` | `string` | 提案标题 |
| `trigger` | `string` | 触发来源 |
| `status` | `string` | 当前状态 |
| `reason` | `string` | 触发原因 |
| `created_topic_id` | `string \| null` | 若已创建主题，则为新主题 ID |
| `updated_ts` | `string` | 最后更新时间 |

### MasteryInfo

| Field | Type | Description |
| --- | --- | --- |
| `topic_id` | `string` | 知识点 ID |
| `mastery_state` | `string` | 掌握状态 |
| `depth_level` | `integer` | 深度级别 |
| `stability_level` | `integer` | 稳定性级别 |
| `success_count` | `integer` | 成功次数 |
| `success_streak` | `integer` | 当前连续成功次数 |
| `spaced_success_count` | `integer` | 间隔复习成功次数 |
| `last_success_ts` | `string \| null` | 最后成功时间 |

### EventInfo

| Field | Type | Description |
| --- | --- | --- |
| `event_index` | `integer` | 事件顺序号，从 1 开始 |
| `ts` | `string` | 事件时间 |
| `kind` | `string` | 事件类型 |
| `payload` | `object` | 事件附加内容 |

### ReviewQueueItem

| Field | Type | Description |
| --- | --- | --- |
| `topic_id` | `string` | 待复习主题 ID |
| `title` | `string` | 主题标题 |
| `resource_count` | `integer` | 当前绑定资源数 |

### ResourceSegmentInfo

| Field | Type | Description |
| --- | --- | --- |
| `segment_id` | `string` | 片段 ID |
| `start_ms` | `integer` | 起始毫秒 |
| `end_ms` | `integer \| null` | 结束毫秒 |
| `label` | `string` | 片段标签 |
| `status` | `string` | 片段状态。常见值：`confirmed`、`classified`、`proposed`、`unclassified`、`parse_failed`、`unsupported` |
| `sequence_index` | `integer` | 文档分段顺序 |
| `text` | `string \| null` | 分段正文文本。媒体资源通常为空，文档资源通常有值 |
| `locator` | `object` | 文档定位信息，如 TXT 行号、PDF 页号、DOCX 段落号、PPTX 幻灯片号 |
| `topic_id` | `string \| null` | 若该片段已挂到现有知识点，则为目标主题 ID |
| `proposal_id` | `string \| null` | 若该片段触发图谱提案，则为提案 ID |
| `proposed_topic_title` | `string \| null` | 若触发提案，则为建议主题标题 |
| `decision` | `string` | 片段分类决策：`link`、`propose`、`unclassified` |
| `confidence` | `number` | 分类或提案置信度，范围 `0..1` |
| `reason` | `string` | 分类/提案原因摘要 |

### ResourceInfo

| Field | Type | Description |
| --- | --- | --- |
| `resource_id` | `string` | 资源 ID |
| `topic_id` | `string` | 绑定主题 ID |
| `topic_title` | `string` | 绑定主题标题 |
| `resource_name` | `string` | 前端显示名称 |
| `category` | `string` | `learn` 或 `review` |
| `media_type` | `string` | `video`、`audio`、`image`、`pdf`、`docx`、`pptx`、`txt`、`binary` 等 |
| `mime_type` | `string` | 文件 MIME 类型 |
| `original_filename` | `string` | 原始文件名 |
| `resource_url` | `string` | 资源下载/访问路径 |
| `size_bytes` | `integer` | 文件大小 |
| `created_ts` | `string` | 创建时间 |
| `segments` | `ResourceSegmentInfo[]` | 资源分段列表 |

## Endpoints

### 1. System

#### `GET /health`

健康检查接口。

##### Response `200`

当前实现至少返回：

```json
{
  "ok": true
}
```

##### Status codes

- `200`：服务进程可用

### 2. Session state and turns

#### `GET /v1/session/state`

获取当前单会话的完整汇总状态。

##### Response `200`

```json
{
  "session_id": "default",
  "profile": {
    "student_id": "u1",
    "display_name": "demo",
    "locale": "zh-CN"
  },
  "learning": {
    "current_topic_id": "demo_01",
    "current_phase": "learning",
    "total_score": 10,
    "consecutive_correct": 0,
    "consecutive_wrong": 0,
    "explore_window_until": null,
    "explore_window_cooldown_until": null,
    "review_queue_size": 0,
    "history_event_count": 0
  },
  "topics": [],
  "proposals": [],
  "mastery": [],
  "turn_count": 0,
  "events_cursor": 0
}
```

##### Status codes

- `200`：成功返回当前状态

#### `POST /v1/session/input/text`

提交一次普通文本回合，返回文字回复和完整音频的 Base64。

##### Request body

```json
{
  "text": "恐龙为什么会灭绝？"
}
```

##### Request fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `text` | `string` | yes | 用户文本输入。Pydantic 允许 `1..8192` 字符，业务层还会按 `API_TEXT_MAX_CHARS` 再次限制。 |

##### Response `200`

```json
{
  "session_id": "default",
  "turn_id": "turn_000001",
  "user_text": "恐龙为什么会灭绝？",
  "reply_text": "因为环境变化、小行星撞击等因素叠加。",
  "earned_points": 5,
  "reply_audio_base64": "SUQz...",
  "reply_audio_mime": "audio/mpeg",
  "current_topic_id": "topic_demo_01",
  "current_phase": "learning",
  "total_score": 25,
  "explore_window_until": null,
  "events_cursor": 18
}
```

##### Response fields

| Field | Type | Description |
| --- | --- | --- |
| `session_id` | `string` | 固定为 `default` |
| `turn_id` | `string` | 当前回合 ID |
| `user_text` | `string` | 实际被处理的输入文本 |
| `reply_text` | `string` | Tutor 文本回复 |
| `earned_points` | `integer` | 本轮获得积分 |
| `reply_audio_base64` | `string \| null` | 完整回复音频的 Base64 编码 |
| `reply_audio_mime` | `string` | 音频 MIME，当前默认 `audio/mpeg` |
| `current_topic_id` | `string \| null` | 当前主题 ID |
| `current_phase` | `string` | 当前学习阶段 |
| `total_score` | `integer` | 本轮执行后累计积分 |
| `explore_window_until` | `string \| null` | 探索时间窗结束时间 |
| `events_cursor` | `integer` | 本轮完成后最新事件游标 |

##### Status codes

- `200`：成功处理文本回合
- `400`：`text` 为空，或超过 `API_TEXT_MAX_CHARS`
- `422`：JSON body 缺失，或字段类型不合法

##### Notes

- 服务端会先 `trim()` 文本，纯空白会按空文本处理
- 每次成功请求都会追加 `api_turn_completed` 事件

#### `POST /v1/session/input/audio`

提交一次普通音频回合，服务端先做语音识别，再执行学习回合。

##### Request

`multipart/form-data`

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | binary | yes | 用户上传的音频文件 |

##### Response `200`

```json
{
  "session_id": "default",
  "turn_id": "turn_000002",
  "user_text": "语音识别结果",
  "recognized_text": "语音识别结果",
  "reply_text": "好的，我们来一起看看。",
  "earned_points": 5,
  "reply_audio_base64": "SUQz...",
  "reply_audio_mime": "audio/mpeg",
  "current_topic_id": "topic_demo_01",
  "current_phase": "learning",
  "total_score": 30,
  "explore_window_until": null,
  "events_cursor": 19
}
```

##### Status codes

- `200`：成功识别并处理音频回合
- `400`：文件为空
- `413`：文件超过 `API_AUDIO_MAX_BYTES`
- `422`：未提交 `file` 字段，或表单格式不合法

##### Notes

- `recognized_text` 为 ASR 结果
- 事件中 `input_mode=audio`

#### `POST /v1/session/input/audio/sentence`

句级实时音频上传入口。当前实现直接复用 `/v1/session/input/audio` 的逻辑与响应结构。

##### Status codes

- `200`
- `400`
- `413`
- `422`

### 3. Realtime audio output

典型流程：

1. 调用 `POST /v1/session/input/text/realtime`
2. 取回 `stream_id`
3. 立即拉取 `GET /v1/session/output/audio/stream/{stream_id}`
4. 用户打断时调用 `POST /v1/session/output/audio/interrupt/{stream_id}`

#### `POST /v1/session/input/text/realtime`

初始化实时文本回合，不直接返回整段音频 Base64，而是返回可拉取的 `stream_id`。

##### Request body

```json
{
  "text": "讲一下黑洞"
}
```

##### Response `200`

```json
{
  "session_id": "default",
  "turn_id": "turn_000003",
  "reply_text": "黑洞是引力非常强的天体。",
  "earned_points": 5,
  "current_topic_id": "topic_space_01",
  "current_phase": "learning",
  "total_score": 35,
  "explore_window_until": null,
  "stream_id": "stream_a1b2c3d4e5f6",
  "events_cursor": 20
}
```

##### Status codes

- `200`：成功初始化实时流
- `400`：空文本或文本超长
- `422`：请求体不合法

##### Notes

- 本接口也会追加 `api_turn_completed` 事件
- 该事件 `payload.audio_mode=stream`

#### `GET /v1/session/output/audio/stream/{stream_id}`

拉取流式音频内容。

##### Path params

| Field | Type | Description |
| --- | --- | --- |
| `stream_id` | `string` | 由 realtime 初始化接口返回 |

##### Response `200`

- `Content-Type: audio/mpeg`
- Body 为流式二进制音频块

##### Status codes

- `200`：成功建立音频流
- `404`：`stream_id` 不存在或已被消费

##### Notes

- 流结束后，服务端会消费并移除该 `stream_id`
- 同一 `stream_id` 设计上应视为一次性消费资源

#### `POST /v1/session/output/audio/interrupt/{stream_id}`

请求中断流式播放。

##### Response `200`

```json
{
  "session_id": "default",
  "stream_id": "stream_a1b2c3d4e5f6",
  "interrupted": true
}
```

##### Status codes

- `200`：请求已处理

##### Notes

- 即使 `stream_id` 不存在，也不会返回 `404`
- 当流已结束或不存在时，返回 `interrupted=false`
- 该接口是幂等式行为，更像“尝试停止”而不是“必须存在才停止”

### 4. Event polling

#### `GET /v1/session/events?after=0&limit=50`

按游标增量拉取学习事件。

##### Query params

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `after` | `integer` | no | `0` | 从该游标之后开始取 |
| `limit` | `integer` | no | `50` | 请求条数，内部会被裁剪到 `1..200` |

##### Response `200`

```json
{
  "session_id": "default",
  "after": 0,
  "next_cursor": 3,
  "events": [
    {
      "event_index": 1,
      "ts": "2026-01-01T00:00:00+00:00",
      "kind": "api_turn_completed",
      "payload": {
        "turn_id": "turn_000001",
        "input_mode": "text",
        "user_text": "你好",
        "earned_points": 5
      }
    }
  ]
}
```

##### Status codes

- `200`：成功返回事件列表
- `422`：query 参数类型不合法

##### Common event kinds

- `api_turn_completed`
- `review_topic_pushed`
- `resource_uploaded`
- `explore_window_opened`
- `explore_window_open_blocked`
- `explore_window_closed`
- `graph_shadow_rollback`
- 引擎类事件，如 `mastery_update`、`graph_proposal`、`topic_transition`

##### Cursor semantics

- 若前端已消费到 `next_cursor=120`，下一次建议请求 `after=120`
- `event_index` 为展示友好序号
- `next_cursor` 才是下一次轮询应使用的真实游标

### 5. Review queue

#### `POST /v1/session/review/push`

把指定主题加入复习队列。

##### Request body

```json
{
  "topic_id": "topic_demo_01"
}
```

兼容旧字段：

```json
{
  "content": "topic_demo_01"
}
```

##### Request fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `topic_id` | `string \| null` | recommended | 推荐字段，复习主题 ID |
| `content` | `string \| null` | compatibility only | 旧字段别名，语义等同 `topic_id` |

##### Response `200`

```json
{
  "session_id": "default",
  "queued": true,
  "topic_id": "topic_demo_01",
  "review_queue_size": 2
}
```

##### Status codes

- `200`：成功处理请求。若已在队列中，通常仍会成功返回，只是 `queued` 取决于运行态结果
- `400`：`topic_id` 和 `content` 都为空
- `404`：主题不存在
- `422`：请求体格式错误

#### `GET /v1/session/review-queue`

获取当前复习队列。

##### Response `200`

```json
{
  "session_id": "default",
  "topics": ["topic_demo_01"],
  "size": 1,
  "items": [
    {
      "topic_id": "topic_demo_01",
      "title": "恐龙为什么会灭绝？",
      "resource_count": 3
    }
  ]
}
```

##### Response fields

| Field | Type | Description |
| --- | --- | --- |
| `topics` | `string[]` | 兼容旧前端的主题 ID 列表 |
| `size` | `integer` | 队列大小 |
| `items` | `ReviewQueueItem[]` | 新结构，包含标题与资源数 |

##### Status codes

- `200`：成功返回复习队列

### 6. Resource management

#### `POST /v1/resource/upload`

上传资源并绑定到知识节点。

##### Request

`multipart/form-data`

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | binary | yes | 上传文件 |
| `topic_id` | `string` | yes | 目标知识节点 ID |
| `resource_name` | `string` | yes | 前端显示名称 |
| `category` | `string` | no | `learn` 或 `review`，默认 `learn` |

##### Server behavior

1. 校验 `topic_id` 和 `resource_name` 非空
2. 校验 `category` 只能是 `learn` 或 `review`
3. 校验主题存在
4. 文件落盘到 `DATA_ROOT/resources`
5. 推断 `mime_type` 与 `media_type`
6. 写入资源记录
7. 若是媒体资源，默认创建单个 `seg_full` 片段
8. 若是文档资源（当前支持 `txt`、`pdf`、`docx`、`pptx`，`doc` 会降级为 unsupported），服务端会尝试：
   - 解析文本
   - 自动切块
   - 调用 LLM 做“挂已有知识点 / 提议新知识点 / 暂不归类”的判断
   - 把分段结果写入 `resource_segments`
9. 当 `category=review` 时，自动尝试推入复习队列
10. 写入 `resource_uploaded` 事件
11. 若执行了文档解析，还会额外写入 `resource_ingested` 事件

##### Response `200`

```json
{
  "session_id": "default",
  "queued": true,
  "review_queue_size": 3,
  "resource": {
    "resource_id": "res_xxx",
    "topic_id": "topic_demo_01",
    "topic_title": "恐龙为什么会灭绝？",
    "resource_name": "恐龙灭绝讲解视频",
    "category": "review",
    "media_type": "video",
    "mime_type": "video/mp4",
    "original_filename": "lesson.mp4",
    "resource_url": "/v1/resource/files/res_xxx",
    "size_bytes": 123456,
    "created_ts": "2026-05-02T10:00:00+00:00",
    "segments": [
      {
        "segment_id": "seg_res_xxx_0000_ab12cd",
        "start_ms": 0,
        "end_ms": null,
        "label": "chunk",
        "status": "classified",
        "sequence_index": 0,
        "text": "第一段正文内容",
        "locator": {
          "kind": "txt",
          "line_start": 1,
          "line_end": 3
        },
        "topic_id": "topic_demo_01",
        "proposal_id": null,
        "proposed_topic_title": null,
        "decision": "link",
        "confidence": 0.91,
        "reason": "片段讨论当前知识点"
      }
    ]
  }
}
```

##### Status codes

- `200`：上传成功
- `400`：`topic_id` 为空、`resource_name` 为空、`category` 非法
- `404`：主题不存在
- `422`：表单字段缺失或类型不合法
- `500`：文件落盘或记录写入失败

##### Media type inference

服务端会基于 MIME 或扩展名推断 `media_type`，常见结果如下：

- 视频：`video`
- 音频：`audio`
- 图片：`image`
- PDF：`pdf`
- Word：`doc`、`docx`
- PowerPoint：`ppt`、`pptx`
- 文本：`txt`
- 其他：`binary`

##### Document ingestion notes

- 当前已接入解析链路的文档类型：`txt`、`pdf`、`docx`、`pptx`
- `doc` 目前会保留上传成功，但分段状态通常为 `unsupported`
- 如果缺少对应解析依赖，或文件本身损坏，分段状态可能为 `parse_failed`
- 文档上传成功不代表每个分段都已归类到知识点；未命中的片段会标记为 `unclassified`
- 若某个片段被判断应新增知识点，分段会返回 `proposal_id` 和 `proposed_topic_title`

#### `GET /v1/resource/topics/{topic_id}`

获取指定知识节点下的全部资源。

说明：

- 不仅返回 `resource.topic_id == {topic_id}` 的资源
- 也会返回那些“主绑定主题不等于该 `topic_id`，但其某个文档片段被归类到了该 `topic_id`”的资源
- 这样前端可以直接按主题查看跨主题文档命中的资源

##### Response `200`

```json
{
  "session_id": "default",
  "topic_id": "topic_demo_01",
  "topic_title": "恐龙为什么会灭绝？",
  "resources": []
}
```

##### Status codes

- `200`：成功返回资源列表
- `404`：主题不存在

#### `GET /v1/resource/{resource_id}/segments`

获取某个资源的完整分段结果。

##### Response `200`

```json
{
  "resource_id": "res_xxx",
  "segments": [
    {
      "segment_id": "seg_res_xxx_0000_ab12cd",
      "start_ms": 0,
      "end_ms": null,
      "label": "chunk",
      "status": "classified",
      "sequence_index": 0,
      "text": "第一段正文内容",
      "locator": {
        "kind": "txt",
        "line_start": 1,
        "line_end": 3
      },
      "topic_id": "topic_demo_01",
      "proposal_id": null,
      "proposed_topic_title": null,
      "decision": "link",
      "confidence": 0.91,
      "reason": "片段讨论当前知识点"
    }
  ]
}
```

##### Status codes

- `200`：成功返回分段结果
- `404`：资源不存在

##### Notes

- 家长端上传成功后，可以调用该接口单独读取文档分段与归类结果
- 前端也可以直接读取上传接口返回体里的 `resource.segments` 做首屏展示

#### `GET /v1/resource/files/{resource_id}`

获取资源文件本体。

##### Response `200`

- Body: 文件二进制内容
- `Content-Type`: 资源记录中的 `mime_type`
- `Content-Disposition`: 使用原始文件名下载/展示

##### Status codes

- `200`：成功返回文件
- `404`：资源不存在，或资源记录存在但磁盘文件缺失

##### Notes

- 该接口适用于 `<audio>`、`<video>`、`<img>` 直接引用
- 前端可把相对路径 `resource_url` 拼接到 API host 使用

### 7. Knowledge graph and mastery

#### `GET /v1/knowledge/graph`

返回知识图谱、提案和掌握度快照。

##### Response `200`

```json
{
  "session_id": "default",
  "topics": [],
  "proposals": [],
  "mastery": []
}
```

##### Status codes

- `200`：成功返回图谱快照

#### `GET /v1/session/mastery`

返回掌握度列表。

##### Response `200`

```json
{
  "session_id": "default",
  "mastery": [
    {
      "topic_id": "topic_demo_01",
      "mastery_state": "learning",
      "depth_level": 1,
      "stability_level": 0,
      "success_count": 2,
      "success_streak": 1,
      "spaced_success_count": 0,
      "last_success_ts": null
    }
  ]
}
```

##### Status codes

- `200`：成功返回掌握度信息

### 8. Explore window

#### `GET /v1/session/explore-window`

获取当前探索奖励时间窗状态。

##### Response `200`

```json
{
  "session_id": "default",
  "explore_window_until": null,
  "active": false,
  "remaining_seconds": null,
  "cooldown_until": null,
  "cooldown_remaining_seconds": null
}
```

##### Status codes

- `200`：成功返回状态

#### `POST /v1/session/explore-window/open`

打开探索奖励时间窗。

##### Request body

```json
{
  "minutes": 5
}
```

##### Request fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `minutes` | `integer` | no | 时间窗时长，默认 `5`，允许范围 `1..120` |

##### Response `200`

```json
{
  "session_id": "default",
  "explore_window_until": "2026-05-02T11:20:00+00:00",
  "active": true,
  "remaining_seconds": 300,
  "cooldown_until": null,
  "cooldown_remaining_seconds": null
}
```

##### Status codes

- `200`：成功返回当前状态
- `422`：`minutes` 超出范围或请求体不合法

##### Important behavior

- 若当前仍在冷却期，接口不会返回 `409`
- 服务端会记录 `explore_window_open_blocked` 事件
- 但 HTTP 仍返回 `200`，并返回当前状态快照
- 前端必须通过 `active` 和 `cooldown_remaining_seconds` 判断是否真正打开成功

#### `POST /v1/session/explore-window/close`

关闭探索奖励时间窗。

##### Response `200`

```json
{
  "session_id": "default",
  "explore_window_until": null,
  "active": false,
  "remaining_seconds": null,
  "cooldown_until": "2026-05-02T11:30:00+00:00",
  "cooldown_remaining_seconds": 480
}
```

##### Status codes

- `200`：成功关闭并返回当前状态

## Compatibility routes

为兼容旧前端，保留 `/v1/sessions/*` 风格路由，但全部只接受 `session_id=default`。

若传入其他 `session_id`，返回：

- `404 Not Found`

错误示例：

```json
{
  "detail": "single-session mode only supports: default"
}
```

### Supported compatibility endpoints

- `POST /v1/sessions`
- `GET /v1/sessions`
- `GET /v1/sessions/{session_id}/state`
- `POST /v1/sessions/{session_id}/turns/text`
- `POST /v1/sessions/{session_id}/turns/audio`
- `GET /v1/sessions/{session_id}/events`
- `POST /v1/sessions/{session_id}/review-queue`
- `GET /v1/sessions/{session_id}/review-queue`
- `GET /v1/sessions/{session_id}/graph`
- `GET /v1/sessions/{session_id}/mastery`
- `GET /v1/sessions/{session_id}/explore-window`
- `POST /v1/sessions/{session_id}/explore-window/open`
- `POST /v1/sessions/{session_id}/explore-window/close`

### Compatibility notes

- `POST /v1/sessions`
  - 不会真的创建多会话
  - 作用是更新默认会话的 `student_id`、`display_name`、`locale`
- `GET /v1/sessions`
  - 只会返回一个会话摘要，即 `default`

## Frontend integration recommendations

- 文本交互优先用 `/v1/session/input/text/realtime` + 流式音频接口，体验更好
- 若前端只想拿整段音频，可继续使用 `/v1/session/input/text`
- 轮询事件时保存 `next_cursor`，避免重复拉历史
- 调用 `open` 探索窗后，不要只看 HTTP `200`，还要检查 `active`
- 访问资源文件时，优先使用 `resource_url`，不要自行推导文件路径
- `interrupt` 接口按幂等方式使用，前端无需把“已结束”视为错误

## Changelog summary for v1.3

- API 收敛到单会话模式
- 增加事务性 SQLite 状态存储
- 增加按游标分页读取事件
- 增加实时音频流与打断能力
- 增加复习队列、资源库、知识图谱、掌握度接口
- 保留 `/v1/sessions/*` 兼容路径，方便旧前端平滑迁移
