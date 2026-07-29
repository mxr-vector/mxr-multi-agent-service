# chat-session-management Specification

## Purpose
TBD - created by archiving change add-ai-chat-qa. Update Purpose after archive.
## Requirements
### Requirement: 会话与消息业务表
系统 SHALL 在 `database/rag_parent_child_schema.sql` 新增
`rag.chat_sessions` 与 `rag.chat_messages` 两张表，并遵循现有约定：
uuidv7 主键、无外键（关联由业务层保证）、无触发器（updated_at 业务层
显式赋值）、无 CHECK（取值业务层校验）。`chat_sessions.id` SHALL 由
应用端（uuid_utils.compat.uuid7）生成，并同时作为 LangGraph checkpointer
的 `thread_id`。`chat_messages` SHALL 含 `session_id`、`role`
（'user'/'assistant'）、`content`、`thinking`、`sources JSONB`、
`kb_ids JSONB`、`metrics JSONB`（推理复杂度，仅 assistant 消息填写，
user 消息为 NULL）、`sequence`（会话内单调序号，
`UNIQUE(session_id, sequence)`）、`status`
（'generating'/'done'/'stopped'/'failed'）、`error` 字段。
checkpointer 自身的表 MUST NOT 手写进该 SQL 文件。

#### Scenario: 会话 id 与 thread_id 一致
- **WHEN** 创建一个新会话
- **THEN** 业务表 `chat_sessions.id` 与该会话图执行的 checkpointer
  `thread_id` 为同一 uuidv7 值

#### Scenario: 消息序号唯一
- **WHEN** 同一会话内并发或重复写入相同 sequence 的消息
- **THEN** 唯一约束拒绝重复行，会话内消息顺序可靠

#### Scenario: 推理指标仅记录在 assistant 消息
- **WHEN** 一轮问答完成落库
- **THEN** assistant 消息的 metrics 为结构化指标对象，user 消息的
  metrics 为 NULL

### Requirement: 会话创建与标题生成
系统 SHALL 提供创建会话接口；显式创建时标题为缺省占位，随首轮问答自动更新。
会话标题 SHALL 在首轮问答完成后由 rewrite_model 基于首问生成一句简短摘要
（异步执行，不阻塞问答流；生成失败时 SHALL 回落为首问截断（前 30 个字符），
不影响问答结果）。会话 SHALL 记录属主 `username` 与归属 `dept_id`
（从用户上下文注入）。

#### Scenario: 首轮完成后生成摘要标题
- **WHEN** 新会话的第一轮问答正常完成
- **THEN** 会话标题被更新为 rewrite_model 生成的一句摘要，且标题生成
  不阻塞 done 帧的下发

#### Scenario: 摘要生成失败回落截断
- **WHEN** rewrite_model 调用失败或超时
- **THEN** 会话标题回落为首问前 30 个字符截断，问答流程不受影响

### Requirement: 会话查询接口仅属主可见
系统 SHALL 提供会话列表（分页，按 `last_message_at` 倒序）、会话详情、
会话消息历史（分页，按 sequence 升序）与统计（本人会话总数/消息总数）
接口。所有查询 MUST 以当前用户 `username` 等值过滤——问答历史为个人
数据，不做部门扇出；他人会话按不存在处理（不泄露存在性）。列表与历史
MUST 排除软删会话；消息历史 SHALL 返回 content/thinking/sources/status
等展示字段，MUST NOT 读取 checkpointer 数据。

#### Scenario: 只能看到本人会话
- **WHEN** 用户 A 请求会话列表
- **THEN** 结果只含 A 创建的未删除会话，按最后消息时间倒序

#### Scenario: 访问他人会话
- **WHEN** 用户 A 请求用户 B 的会话详情或消息历史
- **THEN** 返回"会话不存在"的业务异常

#### Scenario: 历史来自业务表
- **WHEN** 前端加载某会话的消息历史
- **THEN** 数据全部来自 `rag.chat_messages`，包含来源快照与消息状态

### Requirement: 会话删除
系统 SHALL 支持删除单个会话与清空本人全部会话。删除 SHALL 为业务表
软删（`status='deleted'`），并 SHALL 同步删除该 thread 的 checkpoint
数据（`adelete_thread`）；在途生成任务存在时 SHALL 先取消再删除。

#### Scenario: 删除会话同步清理 checkpoint
- **WHEN** 用户删除一个会话
- **THEN** 会话置为软删、不再出现在列表，且其 checkpointer thread 数据被删除

#### Scenario: 清空全部会话
- **WHEN** 用户调用清空接口
- **THEN** 本人全部会话软删，各 thread 的 checkpoint 数据被删除

### Requirement: 消息历史返回富化来源与推理指标
消息历史接口返回的 assistant 消息 SHALL 直接可供前端渲染：`sources`
每项 SHALL 在既有溯源字段（text/source/score/knowledge_base_id/
chapter_title/document_id/chunk_id）基础上额外包含 `index`（1 起引用
序号）、`document_name`、`kb_name`、`page_start`、`page_end`、
`similarity_percent`（0–100 整数）与 `similarity_level`
（high/medium/low）；`metrics` SHALL 原样返回落库的推理复杂度对象
（reflect_rounds/retrieved_count/reranked_count/input_tokens/
output_tokens/total_tokens/duration_ms/model）。存量旧结构消息 SHALL
原样返回（新字段缺省），不做数据回填。

#### Scenario: 历史消息可直接渲染来源卡片
- **WHEN** 前端加载一条富化后落库的 assistant 消息
- **THEN** 其 sources 每项含引用序号、文档名、知识库名、页码与
  相似度百分比/分级，无需额外接口回查

#### Scenario: 存量消息宽松兼容
- **WHEN** 前端加载本变更之前落库的旧消息
- **THEN** 接口原样返回旧结构（无新字段、metrics 为空），不报错

