-- ============================================================
-- RAG 知识库 + 父子文档表结构 (Parent-Child / Small-to-Big Retrieval)
-- 向量检索由 Qdrant 负责, 本库不存 embedding
-- PG 的职责:
--   1) 知识库/分类维度组织文档, 供上传归属和前端浏览
--   2) 存储完整的子块/父块/父文档内容, 供 Qdrant 检索命中后回写给对话模型做上下文
--   3) 存储章节标题、页码等结构信息, 供前端展示"匹配到第几章/第几页"
-- 关联方式: rag_chunks.id 与 Qdrant point id 保持一致(或在 Qdrant payload 中存 rag_chunks.id),
--          Qdrant 检索命中后, 用命中的 id 回查本表拿完整内容和结构信息
-- 约束说明: 保留 NOT NULL / UNIQUE 等基础完整性约束;
--          移除外键约束(关联关系由业务层保证)、触发器(updated_at 由业务层显式赋值)、
--          以及 CHECK 约束(取值范围校验放业务层, 避免不同数据库方言差异导致迁移困难)
-- id 生成: 使用 PostgreSQL 18 内置的 uuidv7() (要求 PG >= 18), 时间有序 UUID,
--         相比 gen_random_uuid()(UUID v4, 完全随机)写入 B-tree 主键索引时局部性更好,
--         减少索引页分裂, 大批量写入场景下性能明显更优, 同时仍保持全局唯一, 可直接作为 Qdrant point id
--         例外: rag_knowledge_bases.id 由应用端(uuid_utils.compat.uuid7)生成并显式传入,
--         以便同一事务内由 id 派生 qdrant_collection(形如 kb_{id.hex}_v1); 上方 uuidv7() 默认值保留作为兜底
-- ============================================================

-- ------------------------------------------------------------
-- RAG 相关表统一归属到独立的 rag schema, 与其它业务表隔离
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS rag;

-- ------------------------------------------------------------
-- 0. 分类树 rag_categories
--    支持多级分类(如 "技术文档" -> "数据同步" -> "Flink CDC"),
--    parent_id 自引用, 不加外键, 业务层保证存在性和防止循环引用
-- ------------------------------------------------------------
CREATE TABLE rag.rag_categories (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default', -- 多租户隔离标识, 由业务层从上下文注入(缺省 'default')
    parent_id   UUID,                    -- 逻辑关联 rag.rag_categories.id, NULL 表示根分类
    name        TEXT NOT NULL,
    sort_order  INT NOT NULL DEFAULT 0,  -- 同级排序, 前端展示用

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rag_categories_tenant ON rag.rag_categories (tenant_id);
CREATE INDEX idx_rag_categories_parent ON rag.rag_categories (parent_id);

-- ------------------------------------------------------------
-- 0.1 知识库表 rag_knowledge_bases
--    组织文档的顶层容器, 对应前端"知识库列表"页面
--    与 Qdrant collection 对应, 一个知识库固定绑定一套 embedding 配置
--    (如果后续需要同一知识库内混用多个 embedding provider,
--     再把 embedding_provider/embedding_dim 下放到 rag_documents 级别)
-- ------------------------------------------------------------
CREATE TABLE rag.rag_knowledge_bases (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),

    tenant_id           VARCHAR(64) NOT NULL DEFAULT 'default', -- 多租户隔离标识, 由业务层从上下文注入(缺省 'default')

    name                TEXT NOT NULL,               -- 知识库名称, 前端展示用
    description         TEXT,

    category_id         UUID,                        -- 逻辑关联 rag.rag_categories.id, 业务层保证存在性
    icon                VARCHAR(100),                 -- 前端展示用图标/颜色标识

    -- Qdrant 映射: 一个知识库对应一个 collection(不同知识库可用不同 embedding 模型/维度)
    -- 命名规则: 由后端根据 id 派生为 kb_{id.hex}_v1, 前端无感知, 不由用户输入
    qdrant_collection   VARCHAR(200) NOT NULL,
    embedding_provider  VARCHAR(50),                  -- 'vllm_qwen3' / 'dashscope' / 'cohere' 等, 便于检索时选对客户端
    embedding_model     VARCHAR(100),                 -- 具体模型名, 如 'Qwen3-Embedding-0.6B'
    embedding_dim       INT,

    -- 权限范围, 具体校验逻辑放业务层, 这里只存配置
    visibility          VARCHAR(20) NOT NULL DEFAULT 'private', -- 'private'/'department'/'public'
    owner               VARCHAR(100),                -- 创建者/负责人

    -- 统计信息(冗余字段, 由业务层在写入/删除文档时同步更新, 避免前端列表页每次都 COUNT)
    document_count      INT NOT NULL DEFAULT 0,
    total_chunk_count   INT NOT NULL DEFAULT 0,

    status              VARCHAR(20) NOT NULL DEFAULT 'active', -- 'active'/'archived'/'deleted'

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rag_kb_tenant   ON rag.rag_knowledge_bases (tenant_id);
CREATE INDEX idx_rag_kb_category ON rag.rag_knowledge_bases (category_id);
CREATE INDEX idx_rag_kb_status   ON rag.rag_knowledge_bases (status) WHERE status != 'deleted';

-- ------------------------------------------------------------
-- 1. 父文档表 rag_documents
--    存放原始文档级信息, 是整个层级结构的顶端 (相当于 level = 最大值)
--    新增 knowledge_base_id, 归属到具体知识库, 供上传归类和浏览过滤
-- ------------------------------------------------------------
CREATE TABLE rag.rag_documents (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),

    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default', -- 多租户隔离标识, 由业务层从上下文注入(缺省 'default')

    knowledge_base_id  UUID NOT NULL,          -- 逻辑关联 rag.rag_knowledge_bases.id, 业务层保证存在性

    -- 来源信息, 便于溯源和增量同步判断是否需要重新入库
    source_uri      TEXT,                       -- 原始文件路径 / URL / DB 表名等
    source_system   VARCHAR(50),                -- 来源系统标识, 如 'confluence' / 'oracle_msgupcenter' / 'manual_upload'
    title           TEXT,
    doc_type        VARCHAR(50),                -- 'pdf' / 'markdown' / 'html' / 'db_row' 等

    -- 全文, 大文档可选择只存摘要 + 外部对象存储路径, 避免行过大
    content         TEXT,

    content_hash    CHAR(64),                   -- sha256(content), 用于判断源文件是否变更, 避免重复切块
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 作者、部门、标签、权限范围等, 用于检索后过滤

    -- 有效期管理: 用于识别过期内容, 避免检索到已失效的信息
    source_updated_at  TIMESTAMPTZ,              -- 源系统里内容的最后更新时间, 用于判断是否需要重新拉取/重新切块
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 该版本内容的生效起始时间
    valid_until          TIMESTAMPTZ,             -- 过期时间, NULL 表示长期有效; 检索时按 valid_until IS NULL OR valid_until > now() 过滤
    last_verified_at     TIMESTAMPTZ,             -- 最近一次(人工或定时任务)确认内容仍然有效的时间, 用于安排复核

    status          VARCHAR(20) NOT NULL DEFAULT 'active',  -- 取值 'active'/'reindexing'/'deleted', 由业务层校验(不用 CHECK, 便于跨库迁移)
    version         INT NOT NULL DEFAULT 1,     -- 每次重新切块/更新 +1, 配合下面 chunks.document_version 做灰度重建索引

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()   -- 由业务层在 UPDATE 时显式赋值, 不再用触发器自动维护
);

CREATE INDEX idx_rag_documents_tenant       ON rag.rag_documents (tenant_id);
CREATE INDEX idx_rag_documents_kb           ON rag.rag_documents (knowledge_base_id);
CREATE INDEX idx_rag_documents_source_hash  ON rag.rag_documents (source_uri, content_hash);
CREATE INDEX idx_rag_documents_metadata_gin ON rag.rag_documents USING GIN (metadata);
CREATE INDEX idx_rag_documents_status       ON rag.rag_documents (status) WHERE status != 'deleted';
CREATE INDEX idx_rag_documents_valid_until  ON rag.rag_documents (valid_until) WHERE valid_until IS NOT NULL;

-- ------------------------------------------------------------
-- 2. 父子块表 rag_chunks
--    自引用设计: 同一张表既存"检索用的小子块", 也存"合并后的父块"
--    level = 0            -> 最小检索单元, 对应 Qdrant 里的一个向量点(id 与 Qdrant point id 对应)
--    level = 1, 2, ...    -> 逐级向上合并的父块, 不进 Qdrant, 只用于回写更大范围的上下文
--    parent_chunk_id IS NULL 且 level 达到该文档最大层级 -> 该层直接对应 rag_documents.content
--
--    document_id / parent_chunk_id 不加外键约束: 关联关系(级联删除、存在性校验)由业务层保证
-- ------------------------------------------------------------
CREATE TABLE rag.rag_chunks (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),  -- 与 Qdrant point id 保持一致, 用于命中后回查

    tenant_id           VARCHAR(64) NOT NULL DEFAULT 'default', -- 多租户隔离标识, 冗余存储所属文档的 tenant_id, 由业务层注入(缺省 'default')

    document_id         UUID NOT NULL,          -- 逻辑关联 rag.rag_documents.id, 业务层保证存在性
    parent_chunk_id     UUID,                   -- 逻辑关联 rag.rag_chunks.id (自引用), 业务层保证存在性
    document_version    INT NOT NULL,           -- 冗余存储 rag.rag_documents.version, 用于重建索引时新旧版本并存/切换

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
CREATE INDEX idx_rag_chunks_tenant        ON rag.rag_chunks (tenant_id);
CREATE INDEX idx_rag_chunks_document      ON rag.rag_chunks (document_id, document_version);
CREATE INDEX idx_rag_chunks_parent        ON rag.rag_chunks (parent_chunk_id);
CREATE INDEX idx_rag_chunks_level         ON rag.rag_chunks (level);
CREATE INDEX idx_rag_chunks_metadata_gin  ON rag.rag_chunks USING GIN (metadata);

-- ============================================================
-- 3. 典型写入模式
-- ============================================================
--
-- 0) 上传/建库时先确定 knowledge_base_id (前端选择已有知识库, 或创建新知识库拿到 id 和 qdrant_collection)
-- 1) 插入 rag_documents 时带上 knowledge_base_id, 拿到 document_id / version
-- 2) 按 level=0 批量插入子块, parent_chunk_id 留空 (表示父级就是 rag_documents 本身),
--    同时把生成的 rag_chunks.id 作为 point id 写入对应知识库的 Qdrant collection, payload 里带上
--    document_id/knowledge_base_id/chapter_title/page/valid_until 等字段
--    (embedding 向量本身只存 Qdrant, 不落 PG)
-- 3) 如果需要中间层 (例如"章节"级父块), 先插入 level=1 的章节块,
--    再插入 level=0 子块时把 parent_chunk_id 指向对应的章节块 id
-- 4) 写入完成后, 业务层同步更新 rag_knowledge_bases.document_count / total_chunk_count
--
-- 有效期同步注意: valid_until 必须同时写进 Qdrant payload, 并在检索时作为预过滤条件
-- (payload 里 valid_until 为空或 > 当前时间), 而不是等 PG 命中结果出来后再过滤 ——
-- 否则 Qdrant 召回的 top-K 里混有过期内容, PG 一过滤命中数就不够了
-- 文档过期或者 last_verified_at 长期未更新时, 建议由定时任务把对应 chunk 从 Qdrant 中移除或标记不可检索
--
-- 增量同步建议 (对应 Oracle CDC 里的思路):
-- - 用 content_hash 判断源文档是否变化, 未变化的文档跳过重新切块和向量化
-- - 重新切块时不要直接 DELETE 旧 chunk, 而是新 document_version 写入新一批 chunk 和新的 Qdrant point,
--   索引构建完成后再把旧版本 chunk 和旧 Qdrant point 批量删除, 避免检索服务读到"半新半旧"的状态

-- ============================================================
-- 4. 典型浏览流程 (知识库列表 -> 分类树 -> 文档列表)
-- ============================================================

-- 4.1 分类树展开 (递归 CTE, 拿到某个根分类下所有子分类, 前端做级联菜单/侧边栏)
-- WITH RECURSIVE cat_tree AS (
--     SELECT id, parent_id, name, sort_order, 0 AS depth
--     FROM rag.rag_categories
--     WHERE id = :root_category_id
--
--     UNION ALL
--
--     SELECT c.id, c.parent_id, c.name, c.sort_order, t.depth + 1
--     FROM rag.rag_categories c
--     JOIN cat_tree t ON c.parent_id = t.id
-- )
-- SELECT * FROM cat_tree ORDER BY depth, sort_order;

-- 4.2 某分类(含子分类)下的知识库列表
-- SELECT kb.id, kb.name, kb.document_count, kb.total_chunk_count, kb.status
-- FROM rag.rag_knowledge_bases kb
-- WHERE kb.category_id = ANY(:category_ids_in_subtree)   -- 4.1 查出的整棵子树 id 列表
--   AND kb.status != 'deleted'
-- ORDER BY kb.updated_at DESC;

-- 4.3 某知识库下的文档列表 (分页浏览)
-- SELECT id, title, doc_type, status, version, updated_at
-- FROM rag.rag_documents
-- WHERE knowledge_base_id = :kb_id
--   AND status != 'deleted'
-- ORDER BY updated_at DESC
-- LIMIT :page_size OFFSET :offset;

-- ============================================================
-- 5. 典型检索流程: Qdrant 做向量检索 -> PG 回查完整上下文和章节/页码
-- ============================================================

-- 5.1 第一阶段 (在 Qdrant 侧完成, 非 SQL): 根据知识库确定要查询的 collection
--     (SELECT qdrant_collection FROM rag_knowledge_bases WHERE id = :kb_id),
--     用 query embedding 在该 collection 里做 ANN 检索, 拿到一批命中的 point id (即 rag_chunks.id)

-- 5.2 第二阶段: 用命中的 id 回查 PG, 拿完整内容 + 章节/页码 (给前端展示用)
-- SELECT id, document_id, chapter_title, page_start, page_end, content
-- FROM rag.rag_chunks
-- WHERE id = ANY(:matched_chunk_ids);

-- 5.3 第三阶段: 如需给对话模型更完整的上下文, 递归回溯到父级 (或直接 join rag_documents)
-- 多级场景用递归 CTE:
--
-- WITH RECURSIVE ancestor AS (
--     SELECT c.id, c.document_id, c.parent_chunk_id, c.level, c.content, 0 AS depth
--     FROM rag.rag_chunks c
--     WHERE c.id = ANY(:matched_chunk_ids)          -- 上一步 Qdrant 检索命中的子块 id 列表
--
--     UNION ALL
--
--     SELECT p.id, p.document_id, p.parent_chunk_id, p.level, p.content, a.depth + 1
--     FROM rag.rag_chunks p
--     JOIN ancestor a ON p.id = a.parent_chunk_id
-- )
-- SELECT DISTINCT ON (document_id)                  -- 多个命中子块可能属于同一父级, 去重
--     document_id, parent_chunk_id, level, content
-- FROM ancestor
-- WHERE parent_chunk_id IS NULL                      -- 回溯到顶层父块
-- ORDER BY document_id, depth DESC;
--
-- 简单两级场景 (子块的父级就是文档本身) 直接 join documents + knowledge_bases 即可, 不需要递归:
--
-- SELECT DISTINCT d.id, d.title, d.content, kb.name AS knowledge_base_name
-- FROM rag.rag_chunks c
-- JOIN rag.rag_documents d ON d.id = c.document_id
-- JOIN rag.rag_knowledge_bases kb ON kb.id = d.knowledge_base_id
-- WHERE c.id = ANY(:matched_chunk_ids);