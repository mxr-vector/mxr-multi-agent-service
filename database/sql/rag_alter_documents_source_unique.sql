-- ------------------------------------------------------------
-- 存量库迁移：为 rag.rag_documents 增加 (knowledge_base_id, source_uri) 唯一约束
-- （软删行除外）。新库直接执行最新 rag_schema.sql 即可，无需本脚本。
--
-- 背景：上传链路按 (kb, source_uri) find-then-insert 判重，无唯一约束时
-- 并发上传同一文件会产生重复文档（计数翻倍、重传残留旧副本）。
--
-- 注意：CONCURRENTLY 不能在事务块内执行，请以 psql 单独逐条执行。
-- ------------------------------------------------------------

-- 1. 清理存量重复：同 (kb, source_uri) 仅保留版本最高的一条，其余软删
--    （软删与文档块的清理口径一致，Qdrant 孤儿点可忽略：检索按 chunk id 关联，
--    软删文档的分块仍在其向量集合内，如需彻底清理请对该文档走一次删除链路）
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY knowledge_base_id, source_uri
               ORDER BY version DESC, created_at DESC
           ) AS rn
    FROM rag.rag_documents
    WHERE source_uri IS NOT NULL AND status != 'deleted'
)
UPDATE rag.rag_documents d
SET status = 'deleted', updated_at = now()
FROM ranked r
WHERE d.id = r.id AND r.rn > 1;

-- 2. 建唯一索引（CONCURRENTLY 不锁写，适合在线执行）
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_rag_documents_kb_source
    ON rag.rag_documents (knowledge_base_id, source_uri)
    WHERE status != 'deleted';
