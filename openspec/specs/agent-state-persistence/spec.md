# agent-state-persistence Specification

## Purpose
TBD - created by archiving change add-ai-chat-qa. Update Purpose after archive.
## Requirements
### Requirement: AsyncPostgresSaver 接入与连接池生命周期
chat 父图 SHALL 使用 `AsyncPostgresSaver`（`langgraph-checkpoint-postgres`）
作为 checkpointer，底层为 `psycopg_pool.AsyncConnectionPool`（连接参数
复用 `PostgresConfig`）。该池 SHALL 与现有 SQLAlchemy/asyncpg 业务池
并存、职责分离。池与 checkpointer SHALL 在 FastAPI lifespan 中初始化
（打开池 → `await setup()` → 装配图）并在关停时释放；图实例 SHALL 经
惰性单例获取，MUST NOT 在模块 import 时建立数据库连接。

#### Scenario: 服务启动完成持久化装配
- **WHEN** 服务启动
- **THEN** psycopg 连接池打开、checkpointer 表就绪（setup 幂等）、
  chat 父图携带 checkpointer 可用

#### Scenario: 服务关停释放资源
- **WHEN** 服务优雅关停
- **THEN** 在途生成任务被取消，psycopg 连接池关闭，无连接泄漏

### Requirement: checkpointer 对业务层透明
checkpointer 的表结构 SHALL 由 `setup()` 自动创建与演进，MUST NOT
手写 DDL 维护；业务路由与服务层 MUST NOT 直接查询 checkpoint 表——
会话列表、消息历史、统计一律以业务表为事实源。checkpointer 仅服务于
图运行时的多轮状态恢复与容错。

#### Scenario: 业务查询不触碰 checkpoint
- **WHEN** 审查 chat 相关路由与服务层代码
- **THEN** 不存在对 checkpoint 表的任何直接读写

### Requirement: checkpoint 保留 7 天并定期清理
checkpoint 数据 SHALL 按 TTL 清理：保留天数由
`ENV.chat_checkpoint_ttl_days` 配置（默认 7）。服务 SHALL 在启动时执行
一次清理，并以后台任务按日循环：以
`chat_sessions.last_message_at` 早于阈值的会话圈定 thread_id，逐一
`adelete_thread`。清理 MUST NOT 影响业务表中的会话与消息数据。

#### Scenario: 过期 checkpoint 被清理
- **WHEN** 某会话最后一条消息早于 7 天且清理任务运行
- **THEN** 该 thread 的 checkpoint 数据被删除，业务表会话与消息完整保留

### Requirement: checkpoint 缺失时历史回落业务表
系统 SHALL 在会话的 checkpoint 已被 TTL 清理（或首次接入前的存量会话）时
仍支持继续问答：condense 节点在 checkpointer 无历史消息时 MUST 从
`rag.chat_messages` 读取该会话最近的若干条消息作为改写历史。

#### Scenario: 过期会话继续追问
- **WHEN** 用户在 checkpoint 已清理的旧会话中继续提问
- **THEN** 问答正常完成，指代消解基于业务表回落的历史进行

