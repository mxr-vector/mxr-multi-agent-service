# draw-diagram-generation Specification

## Purpose
TBD - created by archiving change add-draw-diagram. Update Purpose after archive.
## Requirements
### Requirement: 绘图会话管理
系统 SHALL 提供独立于 chat 问答的绘图会话：用户可创建绘图会话，会话归属当前登录用户；会话及其消息、图表版本记录以 UUIDv7 无连字符格式作为主键，并复用通用字段基类（创建/更新时间等）。

#### Scenario: 创建绘图会话
- **WHEN** 已登录用户在绘图页面发起首次提问或上传图片
- **THEN** 系统创建一条归属该用户的绘图会话并返回会话 ID，后续消息挂载于该会话

#### Scenario: 查询会话历史
- **WHEN** 用户进入绘图页面并选择某个自己拥有的历史会话
- **THEN** 系统按时间顺序返回该会话的消息记录（含各消息关联的图表版本引用）

### Requirement: 多模态输入
系统 SHALL 支持文本提问与图片上传两种输入。图片上传 MUST 复用既有上传守卫（格式白名单与大小限制），仅接受图片类型；上传成功后图片以文件形式存储于绘图子目录，消息记录保存其引用。

#### Scenario: 纯文本提问
- **WHEN** 用户仅输入文本描述（如"画一个订单处理流程图"）
- **THEN** 系统将文本作为用户消息提交生成流程

#### Scenario: 上传图片重绘
- **WHEN** 用户上传一张符合白名单与大小限制的图片（可附带文字说明）
- **THEN** 系统保存图片文件、在消息中记录图片引用，并将图片与文字一并提交多模态模型

#### Scenario: 上传非法文件被拒绝
- **WHEN** 用户上传的文件类型不在图片白名单内或超出大小限制
- **THEN** 系统拒绝上传并按统一响应格式返回明确错误信息

### Requirement: VISUAL 多模态模型调用
系统 SHALL 通过独立的 `VISUAL_MODEL_NAME` / `VISUAL_API_URL` / `VISUAL_API_KEY` 环境变量组（`ENV_CONFIG` property 模式，缺失即启动失败）配置多模态模型，并经 `langchain_openai.ChatOpenAI` 以 OpenAI 兼容多模态消息（text + image_url）调用。图片 MUST 以 base64 data URI 形式进入 image_url。

#### Scenario: 多模态消息构造
- **WHEN** 生成请求包含图片
- **THEN** 系统将图片读取为 base64 data URI，与文本一同构造多模态消息发送至 VISUAL 端点

#### Scenario: VISUAL 服务不可达
- **WHEN** VISUAL 端点连接失败或超时
- **THEN** 系统按既有异常处理规范返回统一错误响应，错误信息明确指示 VISUAL 服务不可达，不影响其他模块

### Requirement: Mermaid 输出约定
系统提示词 SHALL 约束模型仅输出 Mermaid 代码块（限定受支持图型：flowchart、sequenceDiagram、classDiagram、stateDiagram、erDiagram 等）；后端 MUST 从模型回复中提取 Mermaid 代码块并做基础校验（代码块存在、图型声明合法），提取结果作为 AI 图表版本的 `mermaid_source` 落库。

#### Scenario: 正常提取 Mermaid
- **WHEN** 模型回复包含合法的 Mermaid 代码块
- **THEN** 系统提取代码块内容，创建一条 `source_type=ai` 的图表版本记录并关联到本次回复消息

#### Scenario: 回复中无有效 Mermaid
- **WHEN** 模型回复不包含可识别的 Mermaid 代码块
- **THEN** 系统保存文本回复但不创建图表版本，前端提示生成失败并提供重新生成入口

### Requirement: SSE 流式返回
系统 SHALL 以与既有 chat 问答一致的 SSE 流式格式返回生成过程：文本增量逐步下发，流结束时下发本次生成的图表版本标识；客户端断开时 MUST 按既有 asyncio 取消规范终止上游模型调用。

#### Scenario: 流式生成
- **WHEN** 生成请求被受理
- **THEN** 系统以 SSE 逐步推送模型输出增量，结束事件中携带消息 ID 与图表版本 ID（如有）

#### Scenario: 客户端中断
- **WHEN** SSE 连接在生成过程中被客户端断开
- **THEN** 系统取消进行中的模型调用并释放资源，不产生残留的未完成版本记录

