# entity-relation-index Specification

## Purpose
TBD - created by archiving change agentic-relation-retrieval. Update Purpose after archive.

## Requirements

### Requirement: 离线关系与桥接事实抽取

系统 SHALL 在索引期对含 ≥2 个已索引实体的叶块执行离线 LLM 抽取：识别块内实体对之间的类型化关系（自由文本关系短语，不设词表约束）与承载该关系的桥接事实句。抽取结果 SHALL 落 `rag.entity_index_relations`，每条记录 SHALL 携带来源块指针（chunk_id / document_id）与 kb 归属。抽取 SHALL 使用 DB 配置的 chat 角色模型，SHALL NOT 引入新模型角色或硬编码端点。

#### Scenario: 共现实体块产出关系记录

- **WHEN** 某叶块同时包含已索引实体 "Edward Watson" 与 "John Watson"
- **THEN** 抽取产出形如（head=Edward Watson, relation=father, tail=John Watson, fact_text=承载句, chunk_id=来源块）的记录

#### Scenario: 单实体块跳过

- **WHEN** 叶块只含 0 或 1 个已索引实体
- **THEN** 系统不调用 LLM，不产生关系记录（成本控制）

### Requirement: 幂等与断点续建

关系抽取构建 SHALL 幂等：按 (kb, chunk) 粒度记录进度，重复执行跳过已完成块；中断后重跑 SHALL 从断点继续。同库重建 SHALL 先清空该库既有关系记录再写入。构建进度与失败块计数 SHALL 可查询。

#### Scenario: 中断续建

- **WHEN** 构建执行到一半中断后重新启动
- **THEN** 已完成块不重复抽取，构建从断点继续至完成

### Requirement: 关系查询接口

系统 SHALL 提供按实体查询关系的确定性接口：输入实体与库范围，返回该实体参与的关系记录（关系短语、对端实体、事实句、来源块指针），按来源块与关系频次排序并限量。接口 SHALL 零 LLM 调用；关系表缺失或实体无记录时 SHALL 返回空结果（调用方优雅降级）。

#### Scenario: 实体关系查询

- **WHEN** agent 以实体 "John Watson" 调用关系查询
- **THEN** 返回其参与的关系记录（含事实句与来源块指针），不含 LLM 调用

#### Scenario: 无记录降级

- **WHEN** 查询实体无任何关系记录或关系表未构建
- **THEN** 接口返回空结果，不报错、不阻断对话
