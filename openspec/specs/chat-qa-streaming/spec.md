# chat-qa-streaming Specification

## Purpose
TBD - created by archiving change add-ai-chat-qa. Update Purpose after archive.
## Requirements
### Requirement: SSE 流式问答端点
系统 SHALL 提供 `POST /chat/completions` 端点，请求体含 `question`（必填）、
`session_id`（可选，hex 无连字符）、`kb_ids`（可选，hex 列表）、
`use_web_search`（可选）、`reasoning_effort`（可选，思考强度，透传至
对话生成模型；缺省时使用模型工厂默认值）。响应 SHALL 为
`text/event-stream`，每帧 MUST 携带
标准 SSE 三字段 `id`（会话内单调递增的事件序号）、`event`、`data`（JSON）。
事件类型 SHALL 为：`think`（检索/反思进展文本）、`answer`（答案增量 token，
`data.delta`）、`sources`（结构化来源列表）、`done`（终帧，含
`session_id`/`message_id`/`status`）、`error`（错误信息）。`session_id`
缺省时服务端 SHALL 自动创建会话并在流中回传其 id。

#### Scenario: 完整问答流
- **WHEN** 客户端携带有效 `session_id` 与 `question` 发起请求
- **THEN** 依次收到若干 `think` 帧、连续 `answer` 增量帧、一个 `sources` 帧，
  最后收到 `status='done'` 的 `done` 帧，且所有帧的 `id` 单调递增

#### Scenario: 未传 session_id 自动建会话
- **WHEN** 请求体不含 `session_id`
- **THEN** 服务端创建新会话（标题先为占位，首轮完成后由 rewrite_model
  生成摘要回填），流中回传新会话 id，
  且该会话出现在后续会话列表中

#### Scenario: 生成过程出错
- **WHEN** 图执行过程中抛出异常
- **THEN** 客户端收到 `error` 帧后流结束，对应 assistant 消息落库
  `status='failed'` 且记录错误原因

### Requirement: chat 父图编排多轮问答
问答 SHALL 由 chat 父图执行：`condense` 节点在存在对话历史时 MUST 结合
历史将当前问题改写为指代清晰的独立问题（无历史时直通）；`rag_retrieve`
节点 SHALL 在节点函数内调用 RAG 检索子图（显式状态映射，子图不单独挂
checkpointer）；`respond` 节点 SHALL 基于重排序候选流式生成最终答案并
产出结构化 `sources`。父图 SHALL 以 `thread_id = session_id` 挂载
checkpointer 实现跨请求的多轮记忆。图节点 MUST 为 async，模型调用 MUST
使用异步接口，同步检索链路 MUST 经 `asyncio.to_thread` 包装。

#### Scenario: 多轮指代消解
- **WHEN** 会话已有"Flink CDC 是什么"的问答历史，用户追问"它支持哪些数据库？"
- **THEN** condense 节点将其改写为独立问题（如"Flink CDC 支持哪些数据库？"）
  后进入检索，检索命中与 Flink CDC 相关的候选

#### Scenario: 首轮无历史直通
- **WHEN** 新会话的第一条提问进入图
- **THEN** condense 不调用改写模型，原问题直接进入检索

### Requirement: kb 检索范围为消息级且服务端强制过滤
每次提问的检索范围 SHALL 由该请求的 `kb_ids` 经服务端过滤后决定：
显式传入时 SHALL 与当前用户的可见检索范围（visibility × data_scope ×
status='active'，与 `KnowledgeBaseService.list_visible_ids` 同口径）取交集，
不可见 id 与不存在同语义直接剔除，MUST NOT 直达他人 private/已删除/已归档库；
过滤后为空 SHALL 拒绝请求；未传 `kb_ids` 时服务端 SHALL 按当前用户的缺省
可见范围（`KnowledgeBaseService.list_visible_ids`）解析。实际生效的 kb 范围
SHALL 以快照形式存储在该轮 user 消息的 `kb_ids` 字段，仅作溯源，不约束后续
轮次。图运行期（含分层工具 chunk_read / entity_relation_lookup）SHALL 以该
快照覆盖全部检索/读取工具的 `knowledge_base_ids` 入参，杜绝注入的 kb id
越权读取。

#### Scenario: 同一会话不同轮次使用不同知识库
- **WHEN** 第一轮传 `kb_ids=[A]`、第二轮传 `kb_ids=[B]`（均对当前用户可见）
- **THEN** 两轮分别只检索对应知识库，且两条 user 消息各自记录当轮快照

#### Scenario: 显式传入不可见知识库
- **WHEN** 请求携带他人 private 知识库的 id
- **THEN** 该 id 被服务端剔除（与不存在同语义）；全部 id 均不可见时拒绝请求

#### Scenario: 未选库回落缺省可见范围
- **WHEN** 请求未携带 `kb_ids`
- **THEN** 服务端解析当前用户可见的 active 知识库集合作为检索范围并快照

### Requirement: 用户停止生成即刻中止推理
系统 SHALL 提供 `POST /chat/stop/{session_id}`。服务端 MUST 维护
会话级在途生成任务注册表；stop SHALL 通过 asyncio 任务取消传播到底层
模型 HTTP 请求，使推理侧停止生成（非等待节点自然结束）。取消后已生成的
半截内容 SHALL 落库为 `status='stopped'`，流 SHALL 以 `done` 帧
（`status='stopped'`）正常收尾。对无在途任务的会话调用 stop SHALL 幂等成功。

#### Scenario: 生成中停止
- **WHEN** answer 帧输出过程中用户调用 stop
- **THEN** 流在短时间内收到 `status='stopped'` 的 done 帧结束，
  assistant 消息保留已生成的部分内容且状态为 stopped

#### Scenario: 幂等停止
- **WHEN** 会话没有在途生成任务时调用 stop
- **THEN** 返回成功，无副作用

### Requirement: 同会话生成互斥
同一会话同一时刻 MUST 至多一个在途生成任务；在途任务未结束时的新提问
SHALL 被拒绝并提示上一条回答尚未完成。

#### Scenario: 并发提问被拒
- **WHEN** 会话有在途生成任务时再次 POST /chat/completions
- **THEN** 请求以业务异常被拒绝，在途任务不受影响

### Requirement: 崩溃可恢复的写库时序
每轮问答 SHALL 按序落库：先写 user 消息（含 kb_ids 快照），再写
assistant 占位行（`status='generating'`），流正常结束后更新其
内容/thinking/sources 并置 `done`，同时刷新会话的
`message_count`/`last_message_at`。服务启动时 SHALL 清扫残留
`generating` 消息统一置为 `failed`。

#### Scenario: 进程崩溃后的启动清扫
- **WHEN** 生成中途进程崩溃重启
- **THEN** 启动清扫将残留 generating 消息置为 failed，会话历史可正常加载

### Requirement: 来源快照富化与引用序号
问答链路落库与 SSE `sources` 事件输出的来源列表 SHALL 为富化结构：
每项按重排序次序携带 `index`（1 起引用序号），并在既有溯源字段基础上
包含 `document_name`、`kb_name`（落库前按 id 批量回查，单轮至多各一次
IN 查询，禁止逐条 N+1）、`page_start`/`page_end`（检索链从 Qdrant
payload 透传）、`similarity_percent`（rerank 得分转 0–100 整数）与
`similarity_level`（按阈值分级 high/medium/low）。respond 提示词 SHALL
在上下文中为各候选标注对应 [n] 序号，引导答案正文引用角标与
`sources.index` 对应（尽力而为，不作为硬约束校验）。文档或知识库已被
删除时对应名称字段 SHALL 为 None，不得报错。

#### Scenario: sources 事件输出富化结构
- **WHEN** 一轮问答的 SSE 流输出 sources 帧
- **THEN** 每项含 index/document_name/kb_name/page_start/page_end/
  similarity_percent/similarity_level 及全部既有溯源字段

#### Scenario: 名称回查零 N+1
- **WHEN** 单轮问答命中多个文档与知识库的候选
- **THEN** 文档名与库名各以一次批量查询回填，不逐条查询

#### Scenario: 来源实体已删除时宽松降级
- **WHEN** 候选指向的文档或知识库已被删除
- **THEN** 对应 document_name/kb_name 为 None，问答流程不受影响

### Requirement: 推理复杂度采集与回传
每轮问答 SHALL 采集推理复杂度指标并随 assistant 消息落库
（`metrics JSONB`）：`reflect_rounds`/`retrieved_count`/`reranked_count`
来自 RAG 子图终态，`input_tokens`/`output_tokens`/`total_tokens` 来自
respond 模型响应的 usage 元数据（模型未返回时为 None）、`model` 为
当前 chat 模型名、`duration_ms` 为图执行总耗时。SSE `done` 帧 SHALL
携带同结构 `metrics`。用户停止或异常终止时 SHALL 落库已采集到的部分
指标。

#### Scenario: done 帧携带推理指标
- **WHEN** 一轮问答正常完成
- **THEN** done 帧 data 含 metrics（轮数/候选量/token/耗时/模型），
  且与该 assistant 消息落库的 metrics 一致

#### Scenario: usage 缺失时宽松降级
- **WHEN** 模型响应不携带 usage 元数据
- **THEN** token 三项为 None，其余指标正常采集，问答不受影响

#### Scenario: 停止时保留部分指标
- **WHEN** 用户在生成中途停止
- **THEN** stopped 消息的 metrics 保留已采集的检索指标与耗时

