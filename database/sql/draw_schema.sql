-- ============================================================
-- Draw 绘图模块表结构 (对话生成 Mermaid + drawio 编辑 + 版本链)
-- 职责:
--   1) draw_sessions/draw_messages: 绘图会话与消息流(独立于 rag.chat_*, 不接入 RAG 检索)
--   2) draw_diagram_versions: 图表版本链, append-only 不可变追加
--      - AI 生成版本(source_type='ai'): 必有 mermaid_source
--      - 用户编辑版本(source_type='user'): 必有 drawio_xml 与 preview_file(内嵌 XML 的 xmlpng)
--      - parent_id 指向编辑/再生成的基线版本, AI 首版为 NULL; 无覆盖更新, 无冲突提示
-- 约束说明: 与 rag_parent_child_schema.sql 一致 —— 保留 NOT NULL/UNIQUE 基础约束;
--          无外键/无触发器/无 CHECK, 关联关系与取值范围由业务层保证
-- id 生成: PostgreSQL 18 内置 uuidv7() 默认值兜底; 会话 id 由应用端
--         (uuid_utils.compat.uuid7)生成并显式传入, 与 rag.chat_sessions 约定一致
-- ============================================================

-- ------------------------------------------------------------
-- 绘图相关表统一归属到独立的 draw schema, 与其它业务表隔离
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS draw;

-- ------------------------------------------------------------
-- 1. 绘图会话表 draw_sessions
--    归属当前登录用户, 仅本人可见(查询一律按 user_id 等值收敛)
-- ------------------------------------------------------------
CREATE TABLE draw.draw_sessions (
    id               UUID PRIMARY KEY DEFAULT uuidv7(),
    user_id          VARCHAR(64) NOT NULL,           -- 属主(用户 32 位无连字符 hex)
    title            TEXT NOT NULL DEFAULT '新绘图', -- 首问截断生成, 前端列表展示用
    message_count    INT NOT NULL DEFAULT 0,         -- 冗余计数, 业务层写消息时同步维护
    last_message_at  TIMESTAMPTZ,                    -- 最后消息时间, 列表排序用
    status           VARCHAR(20) NOT NULL DEFAULT 'active', -- 'active'/'deleted'

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_draw_sessions_user ON draw.draw_sessions (user_id);

-- ------------------------------------------------------------
-- 2. 绘图消息表 draw_messages
--    不可变追加 + assistant 占位终态更新模型(对齐 rag.chat_messages);
--    user 消息可携带上传图片引用(image_file); assistant 消息生成成功后
--    通过 draw_diagram_versions.message_id 反向关联本消息产出的图表版本
-- ------------------------------------------------------------
CREATE TABLE draw.draw_messages (
    id           UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id   UUID NOT NULL,                  -- 逻辑关联 draw.draw_sessions.id
    role         VARCHAR(20) NOT NULL,           -- 'user'/'assistant'
    content      TEXT NOT NULL DEFAULT '',       -- user: 提问文本; assistant: 模型回复全文
    image_file   VARCHAR(300),                   -- user 消息上传图片的存储相对路径(data/ 下), 无图为 NULL
    sequence     INT NOT NULL,                   -- 会话内单调序号
    status       VARCHAR(20) NOT NULL DEFAULT 'done', -- 'generating'/'done'/'stopped'/'failed'
    error        TEXT,                           -- failed 时的错误信息

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, sequence)
);

CREATE INDEX idx_draw_messages_session ON draw.draw_messages (session_id);

-- ------------------------------------------------------------
-- 3. 图表版本表 draw_diagram_versions (append-only 版本链)
--    每次 AI 生成/用户编辑保存均插入新行, 不做覆盖更新;
--    parent_id 自引用构成版本链, 业务层保证存在性与同会话约束
-- ------------------------------------------------------------
CREATE TABLE draw.draw_diagram_versions (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id      UUID NOT NULL,               -- 逻辑关联 draw.draw_sessions.id, 冗余存储便于按会话查版本链
    message_id      UUID,                        -- 产出本版本的 assistant 消息(逻辑关联 draw.draw_messages.id); 用户编辑版本为 NULL
    parent_id       UUID,                        -- 基线版本(逻辑自引用), AI 首版为 NULL
    source_type     VARCHAR(20) NOT NULL,        -- 'ai'(生成)/'user'(drawio 编辑保存)
    mermaid_source  TEXT,                        -- Mermaid 源码: ai 版本必有; user 版本冗余保存其基线的源
    drawio_xml      TEXT,                        -- drawio XML: user 版本必有; ai 版本为 NULL(编辑时经 mermaid descriptor 转换)
    preview_file    VARCHAR(300),                -- 预览文件存储相对路径(data/ 下 xmlpng, 内嵌 XML 可直接重载编辑); ai 版本为 NULL(前端 mermaid.js 实时渲染)

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_draw_versions_session ON draw.draw_diagram_versions (session_id);
CREATE INDEX idx_draw_versions_message ON draw.draw_diagram_versions (message_id);
CREATE INDEX idx_draw_versions_parent  ON draw.draw_diagram_versions (parent_id);
