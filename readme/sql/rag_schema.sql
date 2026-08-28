-- ============================================================
-- RAG 知识库 + 父子文档表结构 (Parent-Child / Small-to-Big Retrieval)
-- 向量检索由 Qdrant 负责, 本库不存 embedding
-- PG 的职责:
--   1) 知识库/文件夹维度组织文档, 供上传归属和前端浏览
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
--         同理: chat_sessions.id 也由应用端生成, 因其同时作为 LangGraph checkpointer 的 thread_id
-- checkpointer 说明: LangGraph 的 checkpoint 相关表(checkpoints/checkpoint_blobs/checkpoint_writes 等)
--         由 langgraph-checkpoint-postgres 的 setup() 自动创建与演进, 不入本文件手写维护;
--         它们仅服务于图运行时的多轮状态恢复与容错, 业务查询一律走下方 chat_sessions/chat_messages
-- ============================================================

-- ------------------------------------------------------------
-- RAG 相关表统一归属到独立的 rag schema, 与其它业务表隔离
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS rag;

-- ------------------------------------------------------------
-- 0. 文件夹树 rag_folders
--    知识库内部的多级文件夹(如 "技术文档" -> "数据同步" -> "Flink CDC"),
--    每个文件夹归属且仅归属一个知识库, 不能跨知识库移动;
--    parent_id 自引用, 不加外键, 业务层保证存在性、同库约束和防止循环引用
-- ------------------------------------------------------------
CREATE TABLE rag.rag_folders (
    id                UUID PRIMARY KEY DEFAULT uuidv7(),
    dept_id           VARCHAR(64) NOT NULL DEFAULT '', -- 归属组织/部门(逻辑指向 sys_dept.id, 空字符串表示未归属), 由业务层注入
    knowledge_base_id UUID NOT NULL,           -- 逻辑关联 rag.rag_knowledge_bases.id, 业务层保证存在性, 创建后不可变
    parent_id         UUID,                    -- 逻辑关联 rag.rag_folders.id, 同一知识库内自引用, NULL 表示根文件夹
    name              TEXT NOT NULL,
    sort_order        INT NOT NULL DEFAULT 0,  -- 同级排序, 前端展示用

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rag_folders_dept ON rag.rag_folders (dept_id);
CREATE INDEX idx_rag_folders_kb     ON rag.rag_folders (knowledge_base_id);
CREATE INDEX idx_rag_folders_parent ON rag.rag_folders (parent_id);

-- ------------------------------------------------------------
-- 0.1 知识库表 rag_knowledge_bases
--    组织文档的顶层容器, 对应前端"知识库列表"页面
--    与 Qdrant collection 对应, 一个知识库固定绑定一套 embedding 配置
--    (如果后续需要同一知识库内混用多个 embedding provider,
--     再把 embedding_provider/embedding_dim 下放到 rag_documents 级别)
-- ------------------------------------------------------------
CREATE TABLE rag.rag_knowledge_bases (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),

    dept_id             VARCHAR(64) NOT NULL DEFAULT '', -- 归属组织/部门(逻辑指向 sys_dept.id, 空字符串表示未归属), 由业务层注入

    name                TEXT NOT NULL,               -- 知识库名称, 前端展示用
    description         TEXT,

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

CREATE INDEX idx_rag_kb_dept   ON rag.rag_knowledge_bases (dept_id);
CREATE INDEX idx_rag_kb_status   ON rag.rag_knowledge_bases (status) WHERE status != 'deleted';

-- ------------------------------------------------------------
-- 1. 父文档表 rag_documents
--    存放原始文档级信息, 是整个层级结构的顶端 (相当于 level = 最大值)
--    新增 knowledge_base_id, 归属到具体知识库, 供上传归类和浏览过滤
-- ------------------------------------------------------------
CREATE TABLE rag.rag_documents (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),

    dept_id         VARCHAR(64) NOT NULL DEFAULT '', -- 归属组织/部门(逻辑指向 sys_dept.id, 空字符串表示未归属), 由业务层注入

    knowledge_base_id  UUID NOT NULL,          -- 逻辑关联 rag.rag_knowledge_bases.id, 业务层保证存在性
    folder_id       UUID,                       -- 逻辑关联 rag.rag_folders.id, 同一知识库内的文件夹, NULL 表示知识库根目录, 业务层保证存在性与同库一致性

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

CREATE INDEX idx_rag_documents_dept         ON rag.rag_documents (dept_id);
CREATE INDEX idx_rag_documents_kb           ON rag.rag_documents (knowledge_base_id);
CREATE INDEX idx_rag_documents_folder       ON rag.rag_documents (folder_id);
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

    dept_id             VARCHAR(64) NOT NULL DEFAULT '', -- 归属组织/部门(逻辑指向 sys_dept.id, 空字符串表示未归属), 冗余存储所属文档的 dept_id, 由业务层注入

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
CREATE INDEX idx_rag_chunks_dept          ON rag.rag_chunks (dept_id);
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
-- 4. 典型浏览流程 (知识库列表 -> 库内文件夹树 -> 文档列表)
-- ============================================================

-- 4.1 知识库内文件夹树展开 (递归 CTE, 拿到某个根文件夹下所有子文件夹, 前端做侧边栏树)
-- WITH RECURSIVE folder_tree AS (
--     SELECT id, parent_id, name, sort_order, 0 AS depth
--     FROM rag.rag_folders
--     WHERE knowledge_base_id = :kb_id AND id = :root_folder_id
--
--     UNION ALL
--
--     SELECT f.id, f.parent_id, f.name, f.sort_order, t.depth + 1
--     FROM rag.rag_folders f
--     JOIN folder_tree t ON f.parent_id = t.id
-- )
-- SELECT * FROM folder_tree ORDER BY depth, sort_order;

-- 4.2 某知识库下的文档列表 (分页浏览)
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

-- ------------------------------------------------------------
-- 6. AI 问答会话表 chat_sessions
--    问答历史的业务事实源(前端会话列表/历史/统计均查本表, 不读 checkpoint);
--    id 由应用端(uuid_utils.compat.uuid7)生成, 同时作为 LangGraph checkpointer 的 thread_id;
--    问答历史为个人数据: 查询一律按 user_id 等值收敛(检索来源已由消息级 kb_ids 确立, 与部门无关)
-- ------------------------------------------------------------
CREATE TABLE rag.chat_sessions (
    id                UUID PRIMARY KEY DEFAULT uuidv7(),  -- 应用端生成, 兼作 checkpointer thread_id; 默认值仅兜底
    user_id           VARCHAR(64) NOT NULL,    -- 属主(用户 32 位 hex 标识), 会话仅本人可见
    title             TEXT NOT NULL DEFAULT '新对话', -- 首轮问答后由 rewrite_model 生成一句摘要(失败回落首问截断)
    message_count     INT NOT NULL DEFAULT 0,  -- 冗余计数, 业务层在写入消息时同步更新
    last_message_at   TIMESTAMPTZ,             -- 最后一条消息时间, 列表倒序排序用; 也是 checkpoint TTL 清理的判断基准
    status            VARCHAR(20) NOT NULL DEFAULT 'active', -- 常态 'active'; 删除为物理删除(连同 chat_messages), 'deleted' 仅历史软删遗留

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()   -- 业务层在 UPDATE 时显式赋值
);

CREATE INDEX idx_chat_sessions_user    ON rag.chat_sessions (user_id, status);
CREATE INDEX idx_chat_sessions_last_at ON rag.chat_sessions (last_message_at);

-- ------------------------------------------------------------
-- 7. AI 问答消息表 chat_messages
--    展示级消息快照(含来源/思考/状态), 与 checkpointer 的图状态快照双轨分离;
--    kb_ids 为消息级检索范围快照(存在 user 消息上, 仅溯源, 不约束后续轮次);
--    sequence 为会话内单调序号, UNIQUE 保障并发写入时顺序可靠;
--    status 生命周期: generating(占位) -> done / stopped(用户停止) / failed(异常),
--    服务重启时残留 generating 统一清扫为 failed
-- ------------------------------------------------------------
CREATE TABLE rag.chat_messages (
    id                UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id        UUID NOT NULL,           -- 逻辑关联 rag.chat_sessions.id, 业务层保证存在性
    role              VARCHAR(20) NOT NULL,    -- 'user'/'assistant', 业务层校验
    content           TEXT NOT NULL DEFAULT '',-- 消息正文; assistant 生成中为已产出的部分内容
    thinking          TEXT,                    -- 思考/检索进展文本(assistant)
    sources           JSONB NOT NULL DEFAULT '[]'::jsonb, -- 来源快照(assistant, 结构同 SSE sources 事件, 含引用序号/文档名/库名/页码/相似度分级)
    kb_ids            JSONB,                   -- 消息级检索范围快照(user 消息, hex 无连字符列表)
    metrics           JSONB,                   -- 推理复杂度(仅 assistant 消息: 检索轮数/候选量/token 用量/耗时/模型)
    sequence          INT NOT NULL,            -- 会话内单调序号, 从 1 开始
    status            VARCHAR(20) NOT NULL DEFAULT 'done', -- 'generating'/'done'/'stopped'/'failed'
    error             TEXT,                    -- 失败原因(status='failed' 时填写)

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, sequence)
);

CREATE INDEX idx_chat_messages_session ON rag.chat_messages (session_id, sequence);
CREATE INDEX idx_chat_messages_status  ON rag.chat_messages (status) WHERE status = 'generating';
-- ------------------------------------------------------------
-- 8. 实体桥接索引 (entity-bridge-index 变更)
--    倒排: 实体 -> 文档列表; 通用实体由库内文档频率统计判定(非词表);
--    查询期两跳遍历(实体链接 -> 直达 -> 共现桥扩展)的存储底座;
--    按 kb 全量重建(幂等覆盖), 删除两表即完整回滚
-- ------------------------------------------------------------
CREATE TABLE rag.entity_index_entities (
    kb_id      UUID NOT NULL,             -- 逻辑关联 rag_knowledge_bases.id
    entity     VARCHAR(256) NOT NULL,     -- 归一化实体串(小写化)
    doc_freq   INT NOT NULL DEFAULT 0,    -- 覆盖文档数
    is_generic BOOLEAN NOT NULL DEFAULT false, -- doc_freq/库文档数 > 阈值
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (kb_id, entity)
);

CREATE TABLE rag.entity_index_postings (
    kb_id       UUID NOT NULL,            -- 逻辑关联 rag_knowledge_bases.id
    entity      VARCHAR(256) NOT NULL,    -- 对应 entity_index_entities.entity
    document_id UUID NOT NULL,            -- 逻辑关联 rag_documents.id

    PRIMARY KEY (kb_id, entity, document_id)
);

-- 倒排查表: 按实体取文档列表(主键已覆盖); 按文档取实体(共现统计/构建校验)
CREATE INDEX idx_entity_postings_doc ON rag.entity_index_postings (kb_id, document_id);
-- 非通用实体过滤视图加速(可选)
CREATE INDEX idx_entity_entities_nongeneric ON rag.entity_index_entities (kb_id, entity) WHERE is_generic = false;

-- ------------------------------------------------------------
-- 9. 实体关系索引 (agentic-relation-retrieval 变更)
--    离线 LLM 从"含 >=2 个已索引实体的叶块"抽取类型化关系与桥接事实句,
--    供 entity_relation_lookup 工具按实体查询; 在线零 LLM;
--    进度表支撑断点续建与幂等; 回滚 = 删两表
-- ------------------------------------------------------------
CREATE TABLE rag.entity_index_relations (
    id            UUID PRIMARY KEY DEFAULT uuidv7(),  -- 与 ORM 定义对齐（唯一行标识）
    kb_id         UUID NOT NULL,            -- 逻辑关联 rag_knowledge_bases.id
    head_entity   VARCHAR(256) NOT NULL,    -- 归一化实体串(小写化)
    tail_entity   VARCHAR(256) NOT NULL,
    relation      VARCHAR(256) NOT NULL,    -- 自由文本关系短语(无词表约束)
    fact_text     TEXT NOT NULL DEFAULT '', -- 承载关系的原文句子
    chunk_id      UUID NOT NULL,            -- 来源叶块(逻辑关联 rag_chunks.id)
    document_id   UUID NOT NULL,            -- 来源文档(逻辑关联 rag_documents.id)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_entity_relations_head ON rag.entity_index_relations (kb_id, head_entity);
CREATE INDEX idx_entity_relations_tail ON rag.entity_index_relations (kb_id, tail_entity);

CREATE TABLE rag.entity_index_extract_progress (
    kb_id    UUID NOT NULL,
    chunk_id UUID NOT NULL,
    status   VARCHAR(16) NOT NULL DEFAULT 'done',  -- 'done' / 'failed'
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (kb_id, chunk_id)
);
