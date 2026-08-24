# entity-bridge-index Specification

## Purpose
TBD - created by archiving change entity-bridge-index. Update Purpose after archive.

## Requirements

### Requirement: 离线实体索引构建

系统 SHALL 在索引期对知识库文档离线抽取实体并构建实体倒排（entity → 文档列表）与一跳共现桥（共享实体的文档关联）。实体抽取 SHALL 优先使用确定性规则（如英语大写短语链），规则未覆盖时 MAY 使用 DB 配置的离线模型兜底；抽取结果 SHALL 不依赖任何硬编码领域词表。索引构建 SHALL 幂等可重建，且 SHALL NOT 修改证据集合与 wiki 主题集合的结构与内容。

#### Scenario: 新库构建实体索引

- **WHEN** 对已完成向量化的知识库触发实体索引构建
- **THEN** 每个文档产出实体集合，倒排与共现桥落独立存储，证据集合不受影响

#### Scenario: 重建幂等

- **WHEN** 对同一知识库重复触发构建
- **THEN** 结果与上次一致，不产生重复实体记录

### Requirement: 通用实体统计过滤

系统 SHALL 以统计判据识别通用实体：实体覆盖的文档占比超过配置阈值（默认 5%）即视为通用，SHALL NOT 进入查询期扩展候选。该判据 SHALL 完全由库内文档频率驱动，SHALL NOT 使用硬编码词表或数据集名单。

#### Scenario: 高频实体被过滤

- **WHEN** 某实体出现在超过阈值比例的库内文档中
- **THEN** 查询期链接到该实体时不产生扩展候选

#### Scenario: 阈值可配置

- **WHEN** 管理员调整通用实体频率阈值
- **THEN** 新阈值在下一次索引构建或配置刷新后生效，无需改代码

### Requirement: 查询期实体链接与扩展

系统 SHALL 在多跳检索中对问题做确定性实体链接：问题实体命中倒排时，SHALL 将倒排直达文档与一跳共现文档作为扩展候选限量并入合并池；最终排序 SHALL 仍由原始问题统一重排决定。实体链接失败（问题无可链接实体）时 SHALL 不扩展、静默回退既有检索路径，SHALL NOT 产生降质候选。查询期 SHALL 零新增 LLM 调用。

#### Scenario: 实体链接成功扩展候选

- **WHEN** 问题实体在倒排中命中且存在共现桥
- **THEN** 扩展候选（限量）进入合并池，与原问题召回一起接受统一终排

#### Scenario: 链接失败优雅降级

- **WHEN** 问题未抽出可链接实体或倒排无命中
- **THEN** 检索路径与无实体索引时完全一致，无额外候选、无报错

#### Scenario: 在线零 LLM

- **WHEN** 实体扩展参与任意查询
- **THEN** 该查询的证据检索在线 LLM 调用数不增加

### Requirement: 实体索引可回滚

实体索引能力 SHALL 可通过配置开关关闭或整体删除索引存储回退：关闭后多跳与单跳检索行为 SHALL 与索引不存在时一致，无残留副作用。

#### Scenario: 关闭开关回退

- **WHEN** 实体索引开关关闭
- **THEN** 检索链路不访问实体索引，行为等价于索引缺失

#### Scenario: 索引缺失容错

- **WHEN** 索引存储不存在或不可用
- **THEN** 检索自动降级为无实体扩展路径，查询不失败
