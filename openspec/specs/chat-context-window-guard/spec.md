# chat-context-window-guard Specification

## Purpose
保证发送给对话模型的输入（系统提示、历史摘要/消息、工具结果）始终不超过其可用输入预算；并在会话内容占比过高时先压缩旧历史为摘要、保留最近原文，避免请求因超限失败，也避免长会话早期信息被整体丢弃。

## Requirements

### Requirement: 可用输入预算
系统 SHALL 以 `可用输入预算 = context_window − max_output_tokens` 计算对话模型的输入空间：`context_window` 与 `max_output_tokens` 均取自 chat 模型配置行（`sys_model_config.context_window` 与 `extra.max_output`，后者由字典 `model_max_output` 提供档位；`extra.max_output` 未配置时取该字典第一项（`sort_order` 升序）作为缺省）。系统 MUST NOT 再依赖全局标量 `CHAT_MAX_OUTPUT_TOKENS`。

#### Scenario: 预算按差值计算
- **WHEN** `context_window` 为 200000、`extra.max_output` 为 8192
- **THEN** 可用输入预算为 200000 − 8192 = 191808 token

#### Scenario: 输出上限语义
- **WHEN** chat 模型配置行 `context_window` 为 200000 且 `extra.max_output` 为 8192
- **THEN** 发出的模型请求 `max_tokens` 为 8192，`context_window` 仅参与输入预算计算，不得作为输出上限下发

### Requirement: 80% 触发压缩总结
每轮问答开始时，系统 SHALL 估算本轮输入 token（系统提示 + 已有历史摘要 + 历史消息 + 本轮问题），并在工具循环的每次模型调用前保持预算兜底。当估算值超过可用输入预算的 80% 时，系统 SHALL 用 rewrite/compression 角色把较早历史压缩为摘要，保留最近一段原文（默认占可用预算 40%），并将「较早对话摘要 + 最近原文」注入系统提示；未超过阈值时 SHALL NOT 触发压缩。

#### Scenario: 超过 80% 触发压缩
- **WHEN** 本轮输入估算为 160000 token、可用输入预算为 191808 token（占比 > 80%）
- **THEN** 较早历史被 rewrite 角色压缩为摘要，最近原文保留，摘要与原文一并注入系统提示

#### Scenario: 未超过 80% 不压缩
- **WHEN** 本轮输入估算为 100000 token、可用输入预算为 191808 token
- **THEN** 历史保持原文注入，不调用压缩模型

#### Scenario: 压缩失败降级
- **WHEN** 压缩模型调用失败（上游异常/超时）
- **THEN** 系统记录告警，回退到从最旧按预算裁剪，本轮请求正常发出，不得因压缩失败阻断问答

### Requirement: 摘要持久化与 checkpoint 同步
系统 SHALL 将压缩得到的摘要保存在该 thread 的图状态（`history_summary`）并在后续每轮注入系统提示；被压缩的旧消息 MUST 经消息删除机制从该 thread 的 checkpoint messages 中移除。业务表 `rag.chat_messages` SHALL 保持完整历史，MUST NOT 受压缩/裁剪影响。

#### Scenario: 摘要跨轮保留
- **WHEN** 上一轮触发压缩并把旧消息移出 checkpoint
- **THEN** 后续轮次的系统提示仍包含该摘要，直到下一次压缩更新它

#### Scenario: 业务表历史完整
- **WHEN** checkpoint 消息被压缩/删除
- **THEN** 业务表 `rag.chat_messages` 中该会话的完整历史仍可查询

### Requirement: 预算兜底裁剪
压缩未触发或失败时，系统 SHALL 按如下优先级裁剪：历史消息从最旧开始丢弃直至预算内（条数窗口 `CHAT_HISTORY_MAX_MESSAGES` 继续作为格式化上限）；工具结果消息超预算时 SHALL 按预算截断或丢弃较早轮次的结果；系统提示与本轮问题 MUST NOT 被裁剪。预算检查 SHALL 在每次模型调用前执行，工具循环内多轮调用同样受检。预算不足以容纳系统提示与本轮问题时，系统 SHALL 记录告警并尽力发送。

#### Scenario: 历史超预算从旧丢弃
- **WHEN** 历史消息估算超预算且未触发/无法完成压缩
- **THEN** 最早的旧消息被丢弃，保留最近消息直至预算内

#### Scenario: 工具结果超预算截断
- **WHEN** 单轮检索结果消息使输入超预算
- **THEN** 工具结果消息被截断到预算内，不丢弃系统提示与本轮问题

#### Scenario: 工具循环内持续受检
- **WHEN** 工具循环中每轮追加工具结果后输入重新超预算
- **THEN** 后续每次模型调用前均重新执行预算检查与裁剪

### Requirement: token 估算可复用
系统 SHALL 在每次模型调用前估算输入 token 消耗。估算结果 SHALL 按模型名复用（同一模型名不重复加载编码器）；未知模型名时 SHALL 使用保守的通用估算，不得因估算失败阻断请求。

#### Scenario: 同模型名复用估算
- **WHEN** 同一模型名连续多轮问答
- **THEN** token 估算编码器只初始化一次，后续复用

#### Scenario: 未知模型名回落通用估算
- **WHEN** chat 模型名无法映射到已知 tokenizer
- **THEN** 使用保守的通用估算，请求正常发出