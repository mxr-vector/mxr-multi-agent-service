-- ============================================================
-- story-ai-workspace 增量 DDL（幂等，可重复执行）
--
--   1) 会话域三表建表（存量库若已随 story_schema.sql 建齐则跳过）：
--      story_sessions / story_messages / story_generation_tasks
--   2) story.story_projects 新增 AI 创作参数列：
--        style_key         最近一次生成使用的视频风格 key（风格注册表）
--        production_params 最近一次生成的制作参数（画幅/集数/基调等）
--      两列均可空，缺省行为不变；PG 9.6+ 支持 ADD COLUMN IF NOT EXISTS，天然幂等。
--
-- 注意：ORM 已映射三表与新列，存量库须先执行本脚本再启动服务，
-- 否则 story 既有接口（项目列表/详情等）会因缺列报错。
-- ============================================================

-- ------------------------------------------------------------
-- 1. 生成会话表 story_sessions
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS story.story_sessions (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    title               TEXT,                        -- 会话标题（如"剧本初稿"）, 可空
    type                VARCHAR(30) NOT NULL DEFAULT 'general', -- 'general'/'script'/'character'/'character_art'/'keyframe'
    message_count       INT NOT NULL DEFAULT 0,      -- 冗余计数, 业务层写消息时同步维护
    last_message_at     TIMESTAMPTZ,                 -- 最后消息时间, 列表排序用
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_story_sessions_project      ON story.story_sessions (project_id);
CREATE INDEX IF NOT EXISTS idx_story_sessions_project_type ON story.story_sessions (project_id, type);

-- ------------------------------------------------------------
-- 2. 会话消息表 story_messages（只追加 + assistant 占位终态更新）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS story.story_messages (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id          UUID NOT NULL,               -- 逻辑关联 story.story_sessions.id
    role                VARCHAR(20) NOT NULL,        -- 'user'/'assistant'/'system'
    kind                VARCHAR(30) NOT NULL DEFAULT 'general', -- 'general'/'script'/'character'/'art'/'keyframe'
    content             TEXT NOT NULL DEFAULT '',    -- user: 指令文本; assistant: 生成结果全文或描述
    image_file          VARCHAR(500),                -- 生成图片存储相对路径(data/ 下); 无图为 NULL
    prompt              TEXT,                        -- 生成提示词(再生成时复用), 可空
    params              JSONB,                       -- 生成参数(模型/尺寸/seed 等), 可空
    sequence            INT NOT NULL,                -- 会话内单调序号
    status              VARCHAR(20) NOT NULL DEFAULT 'done', -- 'generating'/'done'/'stopped'/'failed'
    error               TEXT,                        -- failed 时的错误信息
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_story_messages_session         ON story.story_messages (session_id);
CREATE INDEX IF NOT EXISTS idx_story_messages_session_created ON story.story_messages (session_id, created_at);

-- ------------------------------------------------------------
-- 3. 生成任务表 story_generation_tasks（AI 生成过程统一追踪）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS story.story_generation_tasks (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    session_id          UUID,                        -- 发起会话(逻辑关联 story.story_sessions.id), 可空
    task_type           VARCHAR(30) NOT NULL,        -- 'script'/'character'/'character_art'/'keyframe'/'image'
    target_type         VARCHAR(30),                 -- 'project'/'script'/'character'/'character_art'/'keyframe'
    target_id           UUID,                        -- 目标资产 id, 与 target_type 配套
    provider            VARCHAR(100),                -- 模型服务商(openai/硅基流动/...)
    model               VARCHAR(200),                -- 模型名
    prompt              TEXT,                        -- 正向提示词
    negative_prompt     TEXT,                        -- 负向提示词
    params              JSONB,                       -- 生成参数(尺寸/seed/采样器等)
    status              VARCHAR(20) NOT NULL DEFAULT 'pending', -- 'pending'/'queued'/'generating'/'succeeded'/'failed'/'cancelled'
    progress            SMALLINT NOT NULL DEFAULT 0, -- 0-100 进度(生成中轮询展示)
    result_text         TEXT,                        -- 成功产出文本(剧本/角色人设等)
    result_image_file   VARCHAR(500),                -- 成功产出图片相对路径(data/ 下)
    error_code          VARCHAR(100),                -- 失败错误码
    error_message       TEXT,                        -- 失败错误信息
    started_at          TIMESTAMPTZ,                 -- 任务开始时间
    finished_at         TIMESTAMPTZ,                 -- 任务结束时间
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_story_generation_tasks_project        ON story.story_generation_tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_story_generation_tasks_project_status ON story.story_generation_tasks (project_id, status);
CREATE INDEX IF NOT EXISTS idx_story_generation_tasks_target         ON story.story_generation_tasks (target_type, target_id);

-- ------------------------------------------------------------
-- 4. story_projects 新增 AI 创作参数列
-- ------------------------------------------------------------
ALTER TABLE story.story_projects
    ADD COLUMN IF NOT EXISTS style_key VARCHAR(50);

ALTER TABLE story.story_projects
    ADD COLUMN IF NOT EXISTS production_params JSONB;
