# draw-diagram-editing Specification

## Purpose
TBD - created by archiving change add-draw-diagram. Update Purpose after archive.
## Requirements
### Requirement: Mermaid 前端预览
前端 SHALL 使用 mermaid.js 在绘图页面画布区渲染图表预览：流式生成过程中按节流策略尝试渲染中间态，渲染失败静默容忍不打断流；流结束后以完整 Mermaid 源为准渲染最终预览。渲染最终失败时 MUST 展示 Mermaid 源码并提供重新生成入口。

#### Scenario: 流式过程中的预览
- **WHEN** SSE 正在推送包含 Mermaid 代码块的增量
- **THEN** 前端按节流间隔尝试渲染当前累积的 Mermaid 内容，语法不完整导致的渲染失败不产生错误提示

#### Scenario: 最终渲染失败兜底
- **WHEN** 流结束后完整的 Mermaid 源仍无法被 mermaid.js 渲染
- **THEN** 画布区展示源码文本与错误说明，并提供"重新生成"操作

### Requirement: drawio embed 编辑器集成
前端 SHALL 通过 iframe 加载自托管 drawio 实例（地址来自 `DRAWIO_EMBED_URL` 配置，URL 参数含 `embed=1&proto=json&spin=1` 且隐藏内置按钮组），并以 postMessage JSON 协议交互：收到 `{event:'init'}` 后发送 load；Mermaid 版本经 `descriptor:{format:'mermaid', wrap:true}` 加载，编辑过的版本以其 drawio XML（或内嵌 XML 的 PNG）加载。宿主 MUST 校验消息来源 `event.origin` 与 drawio 实例源一致，来源不符的消息一律丢弃。

#### Scenario: 从 Mermaid 版本进入编辑
- **WHEN** 用户对一个 AI 生成的图表版本点击"编辑"
- **THEN** 前端打开 drawio 编辑弹窗，待 init 事件后以 mermaid descriptor（wrap:true）加载该版本源码，编辑器呈现可编辑图形

#### Scenario: 从已编辑版本再次进入编辑
- **WHEN** 用户对一个用户编辑产生的图表版本点击"编辑"
- **THEN** 前端以该版本存储的 drawio XML（或 xmlpng 文件）加载编辑器，图形与上次保存一致

#### Scenario: 非法来源消息被丢弃
- **WHEN** 页面收到 origin 与 drawio 实例源不一致的 message 事件
- **THEN** 前端忽略该消息，不触发任何保存或加载行为

### Requirement: 编辑保存产生新版本
用户在编辑器中确认保存时，前端 SHALL 通过 `{action:'export', format:'xml'}` 与 `{action:'export', format:'xmlpng'}` 取回当前图的 drawio XML 与内嵌 XML 的 PNG 预览，一并提交后端；后端 MUST 创建一条 `source_type=user` 的新图表版本（`parent_id` 指向本次编辑的基线版本），对既有版本记录不做任何覆盖更新。XML 入库前 MUST 通过基本格式与长度校验。

#### Scenario: 保存编辑结果
- **WHEN** 用户在 drawio 编辑弹窗点击保存
- **THEN** 系统新增一条 user 来源的图表版本（含 drawio XML 与 xmlpng 预览文件引用，parent_id 为基线版本 ID），基线版本记录保持不变

#### Scenario: 放弃编辑
- **WHEN** 用户关闭编辑弹窗且未保存
- **THEN** 系统不产生任何新版本记录

#### Scenario: 非法 XML 被拒绝
- **WHEN** 提交的 drawio XML 无法通过格式校验或超出长度限制
- **THEN** 后端拒绝保存并返回统一错误响应，不产生版本记录

### Requirement: 图表版本链
图表版本 SHALL 以 append-only 链式组织：每个版本记录 `source_type`（ai/user）、`parent_id`（基线版本，AI 首版为空）、Mermaid 源（AI 版本必有）、drawio XML 与预览文件（用户编辑版本必有）。系统 MUST 提供按会话/图表查询版本链的能力；AI 基于旧 Mermaid 源再生成产生的新版本不包含用户对其他版本的手工编辑，该行为为预期而非数据丢失。

#### Scenario: 版本链查询
- **WHEN** 用户查看某图表的历史版本
- **THEN** 系统按 parent_id 链与时间顺序返回全部版本（含来源类型与预览引用），任意版本可被重新查看或作为编辑基线

#### Scenario: AI 再生成与手工编辑并存
- **WHEN** 用户在手工编辑版本 v2 存在的情况下要求 AI 继续修改图表
- **THEN** 系统基于 AI 版本的 Mermaid 源生成新版本 v3（不含 v2 的手工编辑），v2 仍完整保留在版本链中可随时查看与编辑

