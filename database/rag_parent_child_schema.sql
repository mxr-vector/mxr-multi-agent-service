-- ============================================================
-- RAG 父子文档表结构 (Parent-Child / Small-to-Big Retrieval)
-- 向量检索由 Qdrant 负责, 本表不存 embedding
-- PG 的职责:
--   1) 存储完整的子块/父块/父文档内容, 供 Qdrant 检索命中后回写给对话模型做上下文
--   2) 存储章节标题、页码等结构信息, 供前端展示"匹配到第几章/第几页"
-- 关联方式: rag_chunks.id 与 Qdrant point id 保持一致(或在 Qdrant payload 中存 rag_chunks.id),
--          Qdrant 检索命中后, 用命中的 id 回查本表拿完整内容和结构信息
-- 约束说明: 保留 NOT NULL / UNIQUE 等基础完整性约束;
--          移除外键约束(关联关系由业务层保证)、触发器(updated_at 由业务层显式赋值)、
--          以及 CHECK 约束(取值范围校验放业务层, 避免不同数据库方言差异导致迁移困难)
-- id 生成: 使用 PostgreSQL 18 内置的 uuidv7() (要求 PG >= 18), 时间有序 UUID,
--         相比 gen_random_uuid()(UUID v4, 完全随机)写入 B-tree 主键索引时局部性更好,
--         减少索引页分裂, 大批量写入场景下性能明显更优, 同时仍保持全局唯一, 可直接作为 Qdrant point id
-- ============================================================

-- ------------------------------------------------------------
-- 1. 父文档表 rag_documents
--    存放原始文档级信息, 是整个层级结构的顶端 (相当于 level = 最大值)
-- ------------------------------------------------------------
CREATE TABLE rag_documents (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),

    -- 来源信息, 便于溯源和增量同步判断是否需要重新入库
    source_uri      TEXT,                       -- 原始文件路径 / URL / DB 表名等
    source_system   VARCHAR(50),                -- 来源系统标识, 如 'confluence' / 'oracle_msgupcenter' / 'manual_upload'
    title           TEXT,
    doc_type        VARCHAR(50),                -- 'pdf' / 'markdown' / 'html' / 'db_row' 等

    -- 全文, 大文档可选择只存摘要 + 外部对象存储路径, 避免行过大
    content         TEXT,

    content_hash    CHAR(64),                   -- sha256(content), 用于判断源文件是否变更, 避免重复切块
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 作者、部门、标签、权限范围等, 用于检索后过滤

    status          VARCHAR(20) NOT NULL DEFAULT 'active',  -- 取值 'active'/'reindexing'/'deleted', 由业务层校验(不用 CHECK, 便于跨库迁移)
    version         INT NOT NULL DEFAULT 1,     -- 每次重新切块/更新 +1, 配合下面 chunks.document_version 做灰度重建索引

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()   -- 由业务层在 UPDATE 时显式赋值, 不再用触发器自动维护
);

CREATE INDEX idx_rag_documents_source_hash ON rag_documents (source_uri, content_hash);
CREATE INDEX idx_rag_documents_metadata_gin ON rag_documents USING GIN (metadata);
CREATE INDEX idx_rag_documents_status ON rag_documents (status) WHERE status != 'deleted';

-- ------------------------------------------------------------
-- 2. 父子块表 rag_chunks
--    自引用设计: 同一张表既存"检索用的小子块", 也存"合并后的父块"
--    level = 0            -> 最小检索单元, 对应 Qdrant 里的一个向量点(id 与 Qdrant point id 对应)
--    level = 1, 2, ...    -> 逐级向上合并的父块, 不进 Qdrant, 只用于回写更大范围的上下文
--    parent_chunk_id IS NULL 且 level 达到该文档最大层级 -> 该层直接对应 rag_documents.content
--
--    document_id / parent_chunk_id 不加外键约束: 关联关系(级联删除、存在性校验)由业务层保证
-- ------------------------------------------------------------
CREATE TABLE rag_chunks (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),  -- 与 Qdrant point id 保持一致, 用于命中后回查

    document_id         UUID NOT NULL,          -- 逻辑关联 rag_documents.id, 业务层保证存在性
    parent_chunk_id     UUID,                   -- 逻辑关联 rag_chunks.id (自引用), 业务层保证存在性
    document_version    INT NOT NULL,           -- 冗余存储 rag_documents.version, 用于重建索引时新旧版本并存/切换

    level               SMALLINT NOT NULL DEFAULT 0,  -- 0=叶子子块(已入 Qdrant), 数字越大代表范围越大
    chunk_index         INT NOT NULL,                 -- 同一 document_id + level 内的顺序号, 用于还原原文顺序

    content             TEXT NOT NULL,          -- 完整文本, Qdrant 命中后靠这里回写给对话模型
    token_count         INT,                    -- 生成时计算好, 供上下文预算控制使用, 避免运行时重复分词
    char_start          INT,                    -- 相对上一级(父块或原文)的字符偏移, 用于溯源/高亮
    char_end            INT,

    -- 章节/页码信息, 用于前端展示"匹配到第几章/第几页"
    chapter_title       TEXT,                   -- 所属章节/标题, 如 "第三章 数据同步架构"
    page_start          INT,                    -- 起始页码 (来源于 PDF/Word 等分页文档时填写)
    page_end            INT,                    -- 结束页码, 跨页的 chunk 用 start/end 区间表示

    content_hash        CHAR(64),               -- 子块级去重/变更判断

    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 表名、字段名、来源系统等其他结构化信息

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, document_version, level, chunk_index)
);

-- 常规查询索引 (无向量索引, 向量检索在 Qdrant 侧)
CREATE INDEX idx_rag_chunks_document      ON rag_chunks (document_id, document_version);
CREATE INDEX idx_rag_chunks_parent        ON rag_chunks (parent_chunk_id);
CREATE INDEX idx_rag_chunks_level         ON rag_chunks (level);
CREATE INDEX idx_rag_chunks_metadata_gin  ON rag_chunks USING GIN (metadata);

-- ============================================================
-- 3. 典型写入模式 (以 2 级结构为例: 子块 level=0, 父块直接是文档本身)
-- ============================================================
--
-- 1) 先插入 rag_documents, 拿到 document_id / version
-- 2) 按 level=0 批量插入子块, parent_chunk_id 留空 (表示父级就是 rag_documents 本身),
--    同时把生成的 rag_chunks.id 作为 point id 写入 Qdrant, payload 里带上 document_id/chapter_title/page 等
--    (embedding 向量本身只存 Qdrant, 不落 PG)
-- 3) 如果需要中间层 (例如"章节"级父块), 先插入 level=1 的章节块,
--    再插入 level=0 子块时把 parent_chunk_id 指向对应的章节块 id
--
-- 增量同步建议 (对应你在 Oracle CDC 里已经很熟悉的思路):
-- - 用 content_hash 判断源文档是否变化, 未变化的文档跳过重新切块和向量化
-- - 重新切块时不要直接 DELETE 旧 chunk, 而是新 document_version 写入新一批 chunk 和新的 Qdrant point,
--   索引构建完成后再把旧版本 chunk 和旧 Qdrant point 批量删除, 避免检索服务读到"半新半旧"的状态

-- ============================================================
-- 4. 典型检索流程: Qdrant 做向量检索 -> PG 回查完整上下文和章节/页码
-- ============================================================

-- 4.1 第一阶段 (在 Qdrant 侧完成, 非 SQL): 用 query embedding 在 Qdrant 里做 ANN 检索,
--     拿到一批命中的 point id (即 rag_chunks.id)

-- 4.2 第二阶段: 用命中的 id 回查 PG, 拿完整内容 + 章节/页码 (给前端展示用)
-- SELECT id, document_id, chapter_title, page_start, page_end, content
-- FROM rag_chunks
-- WHERE id = ANY(:matched_chunk_ids);

-- 4.3 第三阶段: 如需给对话模型更完整的上下文, 递归回溯到父级 (或直接 join rag_documents)
-- 多级场景用递归 CTE:
--
-- WITH RECURSIVE ancestor AS (
--     SELECT c.id, c.document_id, c.parent_chunk_id, c.level, c.content, 0 AS depth
--     FROM rag_chunks c
--     WHERE c.id = ANY(:matched_chunk_ids)          -- 上一步 Qdrant 检索命中的子块 id 列表
--
--     UNION ALL
--
--     SELECT p.id, p.document_id, p.parent_chunk_id, p.level, p.content, a.depth + 1
--     FROM rag_chunks p
--     JOIN ancestor a ON p.id = a.parent_chunk_id
-- )
-- SELECT DISTINCT ON (document_id)                  -- 多个命中子块可能属于同一父级, 去重
--     document_id, parent_chunk_id, level, content
-- FROM ancestor
-- WHERE parent_chunk_id IS NULL                      -- 回溯到顶层父块
-- ORDER BY document_id, depth DESC;
--
-- 简单两级场景 (子块的父级就是文档本身) 直接 join documents 即可, 不需要递归:
--
-- SELECT DISTINCT d.id, d.title, d.content
-- FROM rag_chunks c
-- JOIN rag_documents d ON d.id = c.document_id
-- WHERE c.id = ANY(:matched_chunk_ids);