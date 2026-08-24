# rag-retrieval-eval Specification

## Purpose

提供 RAG 检索质量的离线评测工具链：以带证据片段的中文问答数据集为语料建库，通过双管线（纯混合检索 / 完整 RAG 子图）批量执行采样查询，产出 Recall@K、Precision@K、MRR 指标与可复现的报告，用于度量检索质量与 rerank 增益，且不触碰生产代码与业务数据。

## Requirements

### Requirement: 评测数据集导入专用知识库

评测系统 SHALL 支持将评测数据集（CSV，含 `pageid`/`title`/`content`/`question` 等字段）按页面（`pageid`）聚合为文档导入一个专用评测知识库，并通过项目的标准摄取链路（解析 → 两级切块 → 块树持久化 → dense+sparse 向量化）完成建库。评测知识库 SHALL 与业务知识库隔离（独立 Qdrant 集合），并支持在评测结束后整体删除（含 PG 记录与向量点）。建库过程任一阶段失败 SHALL 抛出明确错误并保持已落库数据一致（不产生半库状态遗留检索）。

#### Scenario: 聚合建库完成

- **WHEN** 数据集 CSV 完整下载且解析成功
- **THEN** 评测知识库包含按页面聚合的全部文档，每篇文档的叶块已完成向量化并可被混合检索召回

#### Scenario: 建库失败不产生半库

- **WHEN** 建库中途发生下载/解析/向量化失败
- **THEN** 建库进程以明确错误退出，且不会残留部分向量点可被后续评测检索命中

### Requirement: gold 基准表双口径生成

评测系统 SHALL 为每个 `question` 生成两种口径的 gold 映射：严格口径映射到 chunk 级（chunk 文本经规范化后包含该条 `content` 的叶块集合）；宽松口径映射到文档级（该条 `pageid` 聚合出的文档）。两条口径 SHALL 同时生成并持久化，供指标计算阶段分别使用。

#### Scenario: content 命中叶块

- **WHEN** 某条记录的 `content` 完整出现在一个或多个已建库叶块的文本中
- **THEN** 这些叶块的 id 进入该 `question` 的严格口径 gold 集合

#### Scenario: content 无任何叶块包含

- **WHEN** 某条记录的 `content` 未被任何叶块文本包含（如句子被切块边界截断）
- **THEN** 该 `question` 严格口径 gold 为空集，宽松口径仍按 `pageid` 映射到对应文档

### Requirement: 分层采样测试集

评测系统 SHALL 从数据集全部 `question` 中按 `title` 分层抽样生成测试集（默认 1000 条），抽样随机种子固定，并把抽样清单（question 与所属 title）持久化，保证评测可复现。

#### Scenario: 同种子复现采样

- **WHEN** 以相同随机种子两次执行采样
- **THEN** 两次产出的测试集 question 清单完全一致

### Requirement: 双管线查询执行

评测系统 SHALL 对测试集中每条 `question` 依次执行两条检索管线并记录完整候选排序与得分：纯检索管线（dense+sparse 混合召回，候选池规模上限）与完整子图管线（含反思多轮与重排序，输出重排后 top-k 候选）。单条查询任一步骤失败 SHALL 仅将该 query 标记为失败并跳过，不得中断整体评测。

#### Scenario: 单条查询失败跳过

- **WHEN** 某条 query 在任一管线中抛出异常（如向量化服务不可用）
- **THEN** 该 query 在对应管线的结果中标记为 failed，其余 query 继续执行，最终报告注明失败数量

### Requirement: 检索指标计算

评测系统 SHALL 对每条成功执行的 query 计算 Recall@K、Precision@K 与 MRR，K 取值集合固定为 {1, 3, 5, 10} 外加系统当前 `rag_final_top_k` 配置值；指标 SHALL 按严格/宽松双口径 × 纯检索/完整子图双管线分别宏平均，并同时输出各指标的标准差。

#### Scenario: 指标表含双管线对比

- **WHEN** 评测执行完成
- **THEN** 汇总指标表对每个口径同时呈现纯检索与完整子图两列指标，可直观对比重排序带来的增益或损耗

### Requirement: 评测报告输出

评测系统 SHALL 输出两类产物：JSON 明细（每条 query 的 gold 集合、两管线候选排名、命中位置与 MRR 贡献）与 Markdown 汇总报告（指标表、K 曲线、失败 query 计数与 MRR=0 的失败案例抽样示例）。两类产物 SHALL 写入评测目录的 results 子目录。

#### Scenario: 报告含失败案例抽样

- **WHEN** 汇总报告生成
- **THEN** 报告包含若干条 MRR=0 的 query 及其返回候选片段，便于人工分析检索失败原因

### Requirement: 评测披露逐跳覆盖

v3 评测 SHALL 在现有 Recall@K、Bridge Recall 和 Hop Success Rate 之外，记录每个 query 的执行跳数、每跳查询、每跳候选数、每跳 gold 覆盖和导航是否有效。汇总报告 SHALL 按题型与跳数分层展示这些指标，并保留无 wiki 单轮基线。

#### Scenario: 多跳覆盖可诊断

- **WHEN** 多跳评测运行完成
- **THEN** 明细能指出失败发生在初始锚点召回、后续跳召回还是最终裁剪，报告同时展示最终 Hop Success Rate

#### Scenario: Wiki 无效样本单独披露

- **WHEN** wiki 命中页面但页面没有问题相关实体或成员指针
- **THEN** 该 query 标记为导航无效并进入降级分组，不与有效导航样本混合解释

### Requirement: 多跳目标阈值可复现

评测 SHALL 提供固定数据、固定候选预算和固定随机种子的多跳验收口径；在该口径下，标注型两跳样本的 Hop Success Rate@10 SHALL 以 0.80 作为优化目标，同时报告样本数、失败数、延迟和在线 LLM 调用数，禁止只报告达到阈值的子集。

#### Scenario: 阈值报告完整

- **WHEN** 评测命令完成
- **THEN** 报告明确显示是否达到 0.80 目标及其完整分母，并列出与单轮基线的差值

#### Scenario: 评测失败不伪造达标

- **WHEN** 有 query 超时、工具异常或 gold 缺失
- **THEN** 这些 query 被单独计数，不从分母中静默删除以制造 0.80 以上结果

### Requirement: LongBench 文档导航字段可复现

LongBench 评测建库 SHALL 保留原始 passage 标题、来源 query 标识和可用于导航的实体元数据；文档映射指纹 SHALL 包含这些字段的版本，字段规则变化时必须重建或明确拒绝复用旧映射。

#### Scenario: 主题页可区分 passage

- **WHEN** 评测 wiki 从 LongBench 文档生成主题页
- **THEN** 页面标题、实体或关键词能够引用 passage 的原始标题/实体，而不是只有哈希文档 id 和数据集通用描述

#### Scenario: 旧建库自动失效

- **WHEN** 文档标题保留规则或 gold/建库版本发生变化
- **THEN** 旧 doc map 不被静默复用，评测要求重建或显式指定兼容版本

### Requirement: 评测披露实体扩展贡献

多跳评测 SHALL 在逐跳归因中披露实体扩展通道的贡献：最终 top-k 命中中来自实体扩展候选的 gold 占比、实体链接成功率（问题可链接实体的 query 占比）、扩展候选进入终排的比例。诊断口径 SHALL 能区分三类失败：问题实体不可链接、链接成功但扩展候选未进 top-k、扩展候选进池但被终排裁掉。

#### Scenario: 扩展贡献可诊断

- **WHEN** 多跳评测运行完成
- **THEN** 报告包含实体扩展贡献三项指标与三类失败归因计数

#### Scenario: 无实体索引时的披露

- **WHEN** 评测运行时实体索引不存在或关闭
- **THEN** 报告如实披露扩展通道未启用，指标按既有口径计算
