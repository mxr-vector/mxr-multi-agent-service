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
