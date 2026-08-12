# chat-context-window-guard Specification

## Purpose
保证发送给对话模型的输入（历史消息、工具结果、系统提示）始终不超过其最大上下文限制，避免请求因超限失败。

## Requirements
### Requirement: 输入预算守卫
系统 SHALL 保证发送给对话模型的每轮请求（系统提示 + 历史消息 + 本轮问题 + 工具结果）输入 token 不超过输入预算。输入预算 SHALL 由公式 `context_window − 输出预留 − 安全边际` 得出：`context_window` 来自 chat 模型配置行（sys_model_config.context_window），输出预留来自标量运行参数 `CHAT_MAX_OUTPUT_TOKENS`，安全边际为 `context_window` 的固定比例。预算不足以容纳系统提示与本轮问题时，系统 SHALL 记录告警并尽力发送，不得因预算问题静默丢弃本轮问题。

#### Scenario: 预算按公式计算
- **WHEN** `context_window` 为 200000、`CHAT_MAX_OUTPUT_TOKENS` 为 8192、安全边际为 10%
- **THEN** 输入预算为 200000 − 8192 − 20000 = 171808 token

#### Scenario: 超限请求被裁剪
- **WHEN** 历史消息 + 本轮输入估算超过输入预算
- **THEN** 发送给模型的输入被裁剪至预算内，请求正常发出

#### Scenario: 预算不足时降级
- **WHEN** 系统提示与本轮问题的估算已超过输入预算（配置异常）
- **THEN** 系统记录告警日志并尽力发送，本轮问题不被丢弃

### Requirement: 输入裁剪行为
输入超预算时，系统 SHALL 按如下优先级裁剪：历史消息从最旧开始丢弃直至预算内（条数窗口 `CHAT_HISTORY_MAX_MESSAGES` 作为格式化上限继续生效，两者取更严格约束）；工具结果消息超预算时 SHALL 按预算截断或丢弃较早轮次的结果；系统提示与本轮问题 MUST NOT 被裁剪。预算检查 SHALL 在每次模型调用前执行，工具循环内多轮调用同样受检。

#### Scenario: 历史超预算从旧丢弃
- **WHEN** 会话历史消息估算超预算
- **THEN** 最早的旧消息被丢弃，保留最近消息直至预算内

#### Scenario: 工具结果超预算截断
- **WHEN** 单轮检索结果消息使输入超预算
- **THEN** 工具结果消息被截断到预算内，不丢弃系统提示与本轮问题

#### Scenario: 工具循环内持续受检
- **WHEN** 工具循环中每轮追加工具结果后输入重新超预算
- **THEN** 后续每次模型调用前均重新执行预算检查与裁剪

### Requirement: 裁剪结果同步 checkpoint
每轮被裁剪掉的旧消息 SHALL 经消息删除机制同步从该 thread 的 checkpoint messages 中移除，使 checkpoint 保持有界窗口。同步删除 MUST NOT 影响业务表 `rag.chat_messages` 中的完整历史。

#### Scenario: checkpoint 窗口有界
- **WHEN** 长会话多轮问答且每轮均有超预算裁剪
- **THEN** checkpoint 中 messages 的体积保持有界，不随轮次无限增长

#### Scenario: 业务表历史完整
- **WHEN** checkpoint 消息被同步删除
- **THEN** 业务表 `rag.chat_messages` 中该会话的完整历史仍可查询

### Requirement: 输出上限语义
对话模型请求的输出 token 上限（max_tokens）SHALL 由 `CHAT_MAX_OUTPUT_TOKENS` 决定；`context_window` 为输入+输出总上限语义，MUST NOT 作为输出上限下发。

#### Scenario: 模型请求携带正确输出上限
- **WHEN** chat 模型配置行 `context_window` 为 200000 且 `CHAT_MAX_OUTPUT_TOKENS` 为 8192
- **THEN** 发出的模型请求 max_tokens 为 8192，输入预算按 200000 参与计算

### Requirement: token 估算可复用
系统 SHALL 在每次模型调用前估算输入 token 消耗。估算结果 SHALL 按模型名复用（同一模型名不重复加载编码器）；未知模型名时 SHALL 使用保守的通用估算，不得因估算失败阻断请求。

#### Scenario: 同模型名复用估算
- **WHEN** 同一模型名连续多轮问答
- **THEN** token 估算编码器只初始化一次，后续复用

#### Scenario: 未知模型名回落通用估算
- **WHEN** chat 模型名无法映射到已知 tokenizer
- **THEN** 使用保守的通用估算，请求正常发出
