# Session State Storage (SQLite)

本文件说明单会话后端的状态与记忆存储设计（P0 + P2）。

## 目标

- 用事务型存储替代 JSON 直写，避免覆盖/损坏。
- 支持事件日志按需读取，不在每次请求加载全量历史。
- 保持与现有状态模型兼容（`AppState` + `LearningEvent`）。

## 存储位置

- 默认数据库文件：由 `STATE_FILE` 推导，后缀改为 `.db`。
- 可显式指定：`STATE_DB_FILE`。

示例：

```env
STATE_FILE=./data/state.json
STATE_DB_FILE=./data/state.db
```

## 表结构

### `app_state`

保存当前唯一会话状态快照（单行）。

```sql
CREATE TABLE IF NOT EXISTS app_state (
  state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
  state_json TEXT NOT NULL,
  updated_ts TEXT NOT NULL
);
```

- `state_json`：`AppState` 的 JSON 序列化结果。
- 写入时会清空 `history_logs` 字段（历史事件单独放 `learning_events`）。
- P2 相关状态（探索时间窗冷却、影子节点观察计数/回滚计数）随 `state_json` 一并事务保存。

### `learning_events`

保存事件日志（自增游标）。

```sql
CREATE TABLE IF NOT EXISTS learning_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  audio_file_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_learning_events_kind
ON learning_events(kind);
```

- `event_id`：事件游标，供 API 分页读取。
- `payload_json`：事件负载（JSON 对象）。

## 事务与一致性

- SQLite `WAL` 模式：`PRAGMA journal_mode=WAL`。
- `synchronous=NORMAL`：兼顾可靠性与性能。
- 状态和事件分别原子写入；每次写入会 `commit`。

## 启动迁移逻辑

首次启动或数据库为空时：

1. 先尝试读取旧 `STATE_FILE`。
2. 写入 `app_state`。
3. 若旧状态里有 `history_logs`，迁移到 `learning_events`。

迁移后，数据库成为权威存储。

## 读取策略（按需加载）

- `load_app_state(include_history=False)`：只读状态快照，不带历史。
- `load_app_state(include_history=True)`：只加载最近 `HISTORY_TAIL_LIMIT` 条历史。
- 事件分页接口使用 `event_id` 游标：`after` + `limit` -> `next_cursor`。

相关环境变量：

```env
HISTORY_TAIL_LIMIT=200
```

## API 侧游标语义

- 请求：`GET /v1/session/events?after=<cursor>&limit=<n>`
- 返回：`next_cursor`
- 下一次轮询直接用 `next_cursor` 作为新的 `after`

## 运维建议

- 数据库文件建议定期备份（例如每天复制 `state.db`）。
- 清理策略可按 `event_id` 或时间窗口归档旧事件（后续可扩展）。
- 本地单用户场景推荐 SQLite；若迁移服务化可切换到 Postgres。
