-- ============================================================
-- Story 剧本模式表结构 (项目管理 + 剧本资产 + 角色立绘资产)
-- 职责:
--   1) story_projects: 项目管理(独立实例, 聚合根) —— 一个项目包含
--      完整的剧本/角色/立绘资产, 资产查询一律按 project_id 收敛
--   2) story_sessions/story_messages: 生成会话与消息流 —— AI 生成过程
--      的全部结果默认保留在会话内(可追溯); 用户确认后才沉淀为项目资产;
--      删除会话(连同消息)即丢弃该会话下未保存的生成结果
--   3) story_scripts: 剧本资产 —— 完整剧本文本(视频大模型输入),
--      多版本并存, is_current 标记项目当前使用版本
--   4) story_characters/story_character_arts: 角色资产 —— 角色人设
--      (结构化 profile, AI 归档) + 立绘(一个角色可有多版), 立绘来源:
--      'upload'(用户上传创建) / 'ai'(图像模型生成, 后期接入)
-- 约束说明: 与既有 schema 一致 —— 保留 NOT NULL/UNIQUE 基础约束;
--          无外键/无触发器/无 CHECK, 关联关系与取值范围由业务层保证
-- id 生成: PostgreSQL 18 内置 uuidv7() 默认值兜底; 业务 id 由应用端
--          (uuid_utils.compat.uuid7)生成并显式传入
-- ============================================================

-- ------------------------------------------------------------
-- 剧本相关表统一归属到独立的 story schema, 与其它业务表隔离
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS story;

-- ------------------------------------------------------------
-- 1. 剧本项目表 story_projects
--    独立实例: 归属当前登录用户, 仅本人可见;
--    一个项目 = 一个作品, 承载剧本/角色/立绘等全部资产
-- ------------------------------------------------------------
CREATE TABLE story.story_projects (
    id                 UUID PRIMARY KEY DEFAULT uuidv7(),
    user_id            VARCHAR(64) NOT NULL,           -- 属主(用户 32 位无连字符 hex)
    title              TEXT NOT NULL DEFAULT '新剧本', -- 项目标题, 前端列表展示用
    description        TEXT,                           -- 故事设定/需求描述(剧本生成的输入), 可空
    script_count       INT NOT NULL DEFAULT 0,         -- 冗余计数: 剧本版本数
    character_count    INT NOT NULL DEFAULT 0,         -- 冗余计数: 角色数
    art_count          INT NOT NULL DEFAULT 0,         -- 冗余计数: 立绘数
    session_count      INT NOT NULL DEFAULT 0,         -- 冗余计数: 生成会话数
    last_generated_at  TIMESTAMPTZ,                    -- 最近生成时间, 列表排序用
    status             VARCHAR(20) NOT NULL DEFAULT 'active', -- 'active'/'archived'

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_projects_user ON story.story_projects (user_id);

-- ------------------------------------------------------------
-- 2. 生成会话表 story_sessions
--    承载一次创作过程的生成历史: AI 生成结果默认全部保留在会话内,
--    用户选择"保存到项目"后才沉淀为资产; 删除会话(连同消息)即丢弃
--    该会话下未保存的生成结果
-- ------------------------------------------------------------
CREATE TABLE story.story_sessions (
    id               UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id       UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    title            TEXT,                        -- 会话标题(如"剧本初稿"、"主角立绘"), 可空
    message_count    INT NOT NULL DEFAULT 0,      -- 冗余计数, 业务层写消息时同步维护
    last_message_at  TIMESTAMPTZ,                 -- 最后消息时间, 列表排序用

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_sessions_project ON story.story_sessions (project_id);

-- ------------------------------------------------------------
-- 3. 会话消息表 story_messages
--    不可变追加 + assistant 占位终态更新模型;
--    kind 区分消息产出类型: 'script'(剧本生成) / 'art'(立绘生成) / 'general';
--    assistant 消息可携带生成结果: content(剧本文本) 与 image_file(立绘图片);
--    prompt 记录生成提示词, params 预留图像模型生成参数(后期接入 AI 生图)
-- ------------------------------------------------------------
CREATE TABLE story.story_messages (
    id           UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id   UUID NOT NULL,                  -- 逻辑关联 story.story_sessions.id
    role         VARCHAR(20) NOT NULL,           -- 'user'/'assistant'
    kind         VARCHAR(20) NOT NULL DEFAULT 'general', -- 'script'/'art'/'general'
    content      TEXT NOT NULL DEFAULT '',       -- user: 指令文本; assistant: 生成结果全文(剧本)或描述
    image_file   VARCHAR(300),                   -- 立绘图片存储相对路径(data/ 下); 无图为 NULL
    prompt       TEXT,                           -- 生成提示词(立绘/剧本重生成时复用), 可空
    params       JSONB,                          -- 生成参数(模型/尺寸/seed 等, 后期图像模型生成用), 可空
    sequence     INT NOT NULL,                   -- 会话内单调序号
    status       VARCHAR(20) NOT NULL DEFAULT 'done', -- 'generating'/'done'/'stopped'/'failed'
    error        TEXT,                           -- failed 时的错误信息

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, sequence)
);

CREATE INDEX idx_story_messages_session ON story.story_messages (session_id);

-- ------------------------------------------------------------
-- 4. 剧本资产表 story_scripts
--    确认保存到项目的剧本: 完整剧本文本(视频大模型输入), 多版本并存;
--    version 项目内递增, is_current 标记当前使用版本(业务层切换时
--    先复位再置位, 不做数据库唯一约束);
--    source_message_id 追溯产出本版本的会话消息(AI 生成场景)
-- ------------------------------------------------------------
CREATE TABLE story.story_scripts (
    id                 UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id         UUID NOT NULL,           -- 逻辑关联 story.story_projects.id
    version            INT NOT NULL,            -- 项目内剧本版本号(从 1 递增)
    title              TEXT,                    -- 剧本标题, 可空(缺省取项目标题)
    content            TEXT NOT NULL,           -- 完整剧本文本
    source             VARCHAR(20) NOT NULL DEFAULT 'ai', -- 'ai'(生成)/'user'(手动编辑)/'upload'(上传)
    source_message_id  UUID,                    -- 来源会话消息(逻辑关联 story.story_messages.id), 手动编辑为 NULL
    is_current         BOOLEAN NOT NULL DEFAULT FALSE, -- 是否为项目当前使用版本

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (project_id, version)
);

-- ------------------------------------------------------------
-- 5. 角色表 story_characters
--    角色人设: AI 从剧本/设定抽取或用户手工创建;
--    profile 为结构化人设(JSONB, 如 外貌/性格/背景 字段), AI 归档结果
-- ------------------------------------------------------------
CREATE TABLE story.story_characters (
    id           UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id   UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    name         VARCHAR(100) NOT NULL,       -- 角色名
    profile      JSONB NOT NULL DEFAULT '{}', -- 结构化人设(外貌/性格/背景等), AI 归档或用户编辑
    art_count    INT NOT NULL DEFAULT 0,      -- 冗余计数: 该角色立绘数

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_characters_project ON story.story_characters (project_id);

-- ------------------------------------------------------------
-- 6. 角色立绘表 story_character_arts
--    一个角色的多版立绘(换装/换表情/多角度);
--    source: 'upload'(用户上传创建) / 'ai'(图像模型生成, 后期接入);
--    image_file 必填, prompt 为生成提示词(AI 生成时记录, 可复用于再生成);
--    status 预留 AI 生成占位: 'generating' -> 'done'/'failed'
-- ------------------------------------------------------------
CREATE TABLE story.story_character_arts (
    id             UUID PRIMARY KEY DEFAULT uuidv7(),
    character_id   UUID NOT NULL,               -- 逻辑关联 story.story_characters.id
    project_id     UUID NOT NULL,               -- 冗余存储, 便于按项目维度查询立绘
    name           VARCHAR(100),                -- 立绘名(如"常服正面"), 可空
    image_file     VARCHAR(300) NOT NULL,       -- 立绘图片存储相对路径(data/ 下)
    prompt         TEXT,                        -- 生成提示词(AI 生成时记录), 可空
    source         VARCHAR(20) NOT NULL DEFAULT 'upload', -- 'upload'/'ai'
    params         JSONB,                       -- 生成参数(模型/尺寸/seed 等, 后期图像模型生成用), 可空
    status         VARCHAR(20) NOT NULL DEFAULT 'done',    -- 'generating'/'done'/'failed'(预留 AI 生成用)
    error          TEXT,                        -- failed 时的错误信息

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_arts_character ON story.story_character_arts (character_id);
CREATE INDEX idx_story_arts_project   ON story.story_character_arts (project_id);
