-- ------------------------------------------------------------
-- 存量库迁移：移除实体索引（entity-bridge-index / agentic-relation-retrieval）
-- 新库直接执行最新 rag_schema.sql 即可，无需本脚本。
--
-- 背景：倒排层（entities/postings）已无在线消费方；关系层仅被默认关闭的
-- entity_relation_lookup 读取，评测无净增益，能力整体下线。
--
-- 注意：破坏性变更，执行前确认数据不再需要或已有备份；不会由代码自动执行。
-- ------------------------------------------------------------

DROP TABLE IF EXISTS rag.entity_index_extract_progress;
DROP TABLE IF EXISTS rag.entity_index_relations;
DROP TABLE IF EXISTS rag.entity_index_postings;
DROP TABLE IF EXISTS rag.entity_index_entities;

-- 构建参数随能力一起下线（运行时配置行）
DELETE FROM sys.sys_config WHERE key = 'ENTITY_GENERIC_DF_PERCENT';
