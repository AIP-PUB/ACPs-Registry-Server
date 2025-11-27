# DRC 数据同步协议 Server 端实现设计

- Server 端是指的 Registry 服务器，负责处理来自 Discovery 的请求，提供数据的快照和变更信息。
- 数据同步的主要代码放在 app.sync 中。有自己的 api, model, schema, service, exception 等模块。
- 需要在 sync.api 中定义 API 接口，以`acps-drc-v1`为前缀，比如：
  - `/acps-drc-v1/snapshots`：快照同步。
  - `/acps-drc-v1/changes`：增量同步。
  - `/acps-drc-v1/info`：系统信息查询。
  - `/acps-drc-v1/webhooks`：Webhook 管理。
- 需要定义一个全局的 seq 生成机制，依赖于 PostgreSQL 的序列（sequence）特性。

## ChangeLog 数据模型

- 需要在 sync.model 中添加 ChangeLog 对象。其中的内容与 Envelope 的内容的一致。
  - ChangeLog 的 seq，是从全局 seq 生成机制中获取的。
  - ChangeLog 的 ts，是当前时间戳。
  - ChangeLog 的 type = acs，表示 Agent Capability Specification (ACS) 数据。目前只有这一种类型。
  - ChangeLog 的 id，对应到具体实现中，是 Registry 中的 Agent.aic。
  - ChangeLog 的 version 对应的是 Agent.acs_version（目前没有，需要添加这个字段），这个字段是 Agent.acs 每次更改时增长的。acs 是否变化是用 Agent.acs_hash 比较的。
  - ChangeLog 的 payload，对应到具体实现中，是 Registry 中的 Agent.acs 字段的内容。
- 每次 Agent 数据更改的操作：
  - 通过比较 Agent.acs_hash 是否不同来判断是否 acs 数据有变化。
  - 如果 acs 数据变化了，那么就进行下列操作：
    - 生成新的 seq 值。
    - Agent.acs_version 字段自增。更新 Agent.acs, acs_hash 等字段内容。
    - 创建 ChangeLog 对象，将 seq 写入，还有其他数据都写入。
    - 更新 Agent.acs_last_seq 字段 为 seq。保证与 ChangeLog 中的 seq 一致。
    - 提交事物。上面的多个操作需要在同一个事物中完成。
- Agent 数据没有删除，都是更改。所以，ChangeLog 中以及返回的 Envelope 中的 op 字段始终是 upsert，所以就省略了。

## Snapshot API

- 在客户端做 Snapshot 的时候，返回的数据每一条是一个 Envelope 对象：
  - Envelope 中的 seq 对应的是 Agent.acs_last_seq 字段。
  - Envelope 中的 ts 对应的是 Agent.updated_at 字段。
  - Envelope 中的 type = acs，目前只有这一种类型。
  - Envelope 中的 id，对应的是 Agent.aic。
  - Envelope 中的 version 对应的是 Agent.acs_version。
  - Envelope 中的 payload 对应的是 ACS 数据，就是 Agent.acs 字段的内容。
- 在 sync.model 中添加一个 Snapshot 对象，用于表示快照数据。
  - id 字段，snapshot 的唯一标识符。
  - types 字段，snapshot 的数据类型。
  - seq 字段，snapshot 的切点 seq 号。
  - chunk_total，snapshot 的总 chunk 数量。
  - object_count，snapshot 的对象数量。
  - from_seq，snapshot 的 from_seq 号，用于增量快照。
  - is_deleted 字段，用于标识快照是否被删除。
  - created_at 字段，用于标识快照的创建时间。
  - last_access_at 字段，用于标识快照的最后访问时间。
  - expire_at 字段，用于标识快照的过期时间。
- 在做 Snapshot 的服务端实现的时候，因为必须支持 Chunking，所以必须在快照创建时"冻结"数据视图，确保所有 chunk 基于同一时刻的数据。采用：**一次性把“截至 切点 seq 的视图”物化**到静态表中，客户端随后对该静态数据做分页传输，适合大规模数据的场景。具体实现是在一个 REPEATABLE READ 隔离级别的事务中，完成对一个或多个表（types 可能是多个）的物化，形成 snapshot-xyz 名字的物化表（xyz 是 Snapshot 对象的 id），物化表的内容是 Envelope 格式。然后返回 xyz 这个 id 和其它信息，以及按照 Envelope.seq 正向排序的 Chunking 数据，客户端根据这个 xyz 开始做 Chunking，同步数据。同步做完之后或者 snapshot 过期之后就删除这个 xyz 的 snapshot-xyz 物化表。并在 Snapshot 对象中标记为 is_deleted。
- 支持全量快照和增量快照两种模式，增量快照通过 `from_seq` 参数指定起始序号。
- 实现快照的自动清理机制，根据访问超时时间和最大生存时间自动清理过期快照。
- 支持通过 `DELETE /acps-drc-v1/snapshots/{id}` 手动删除快照。

## Changes API

- 在做 Changes 增量同步的时候，实现的方法就是查询 ChangeLog 表然后返回相应的数据。以 seq 正向排序，通过在响应头上的 X-Next-Seq 数据，标识本次返回的数据同步的切点。客户端可以用 X-Next-Seq 再次进行增量同步，直到返回 204，表示没有更新的数据了。
- 支持长轮询机制，通过 `wait` 参数实现，减少空拉取。
- 当请求的 `seq` 小于保留窗口的 `oldest_seq` 时，返回 `410 Gone` 错误，客户端需要重新做快照同步。
- 支持通过 `types` 参数过滤特定的对象类型。

## Info API

- 针对协议中的 `info` API，在实现的时候，需要在 `.env` 文件中配置相应的环境变量：
  - `DRC_SERVICE_NAME`：服务名称（如：agent-registry）
  - `DRC_SERVICE_VERSION`：服务版本号
  - `DRC_RETENTION_WINDOW_HOURS`：保留窗口时长（小时，默认 168 小时）
  - `DRC_SNAPSHOT_ACCESS_TIMEOUT_HOURS`：快照访问超时时间（小时，默认 2 小时）
  - `DRC_SNAPSHOT_MAX_LIFETIME_HOURS`：快照最大生存时间（小时，默认 24 小时）
  - `DRC_SUPPORTS_INCREMENTAL_SNAPSHOT`：是否支持增量快照（默认 true）
  - `DRC_SUPPORTS_LONG_POLLING`：是否支持长轮询（默认 true）
- Info API 需要返回协议定义的完整信息，包括系统状态、支持的类型、保留配置、快照配置和变更流配置。

## WebHook API

- 针对 webhook 相关的 API，需要实现完整的 Webhook 管理功能：

### WebHook 数据模型

- 在 `sync.model` 中定义 WebHook 对象，包含以下字段：
  - `id`：Webhook 唯一标识符
  - `url`：回调地址
  - `secret`：签名密钥
  - `types`：关注的数据类型列表（JSON 数组）
  - `events`：关注的事件类型列表（JSON 数组）
  - `status`：状态（active/failed）
  - `description`：描述信息
  - `failure_count`：失败计数
  - `last_triggered_at`：最后触发时间
  - `next_retry_at`：下次重试时间
  - `created_at`：创建时间
  - `updated_at`：更新时间

### WebHook API 端点

- `POST /acps-drc-v1/webhooks`：注册 Webhook
- `GET /acps-drc-v1/webhooks/{id}`：查询 Webhook
- `PUT /acps-drc-v1/webhooks/{id}`：更新 Webhook
- `DELETE /acps-drc-v1/webhooks/{id}`：删除 Webhook
- `POST /acps-drc-v1/webhooks/{id}/reactivate`：重新激活 Webhook
