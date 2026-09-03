-- ============================================================
-- Story 剧本生成平台表结构 (最终版, 合并 story_schema.sql v1 + story_schema_v3.sql)
--
-- 业务模型 (项目为聚合根 + 用户级角色库):
--   产品闭环: 本地备料(角色/剧本/关键帧) -> 外部视频网站生成 -> 视频成品回收到项目
--   角色库 (用户级, 跨项目复用)
--     角色 Character                    —— 结构化人设(profile) + 视觉风格(style)
--       └── 角色立绘 Character Art      —— 外部视频平台的角色参考资产
--   项目 Project
--     ├── 剧情/剧本 Script          —— 生成/编辑的剧本文本, 视频大模型核心文本输入
--     ├── 出演角色                  —— 编排登记引用角色库角色(选择 + 顺序)
--     ├── 关键帧 Keyframe          —— 故事关键场景(画面提示词/参考图/镜头描述), 视频大模型视觉输入
--     ├── 视频成品 Video           —— 外部视频网站生成的单镜头片段, 回收登记与溯源
--     ├── 生成会话 Session         —— AI 生成过程与消息流(可追溯, 确认后才沉淀资产)
--     ├── 生成任务 Generation Task —— 统一追踪 script/character/art/keyframe 等 AI 任务
--     ├── 资产编排 Project Asset   —— 表达"项目当前要使用"哪些资产(出演登记 + 选择 + 导出顺序)
--     └── 导出包 Export Package    —— 按项目内容整理成可直接复制给外部视频模型网站的不可变快照
--
-- 设计目标:
--   1. 项目是聚合根, 剧本/关键帧等资产查询一律按 project_id 收敛;
--      角色库归属用户(仅本人可见), 跨项目复用, 项目通过编排表登记出演
--   2. AI 生成过程(会话/消息/任务)与正式资产分离; 删除会话(连同消息)即丢弃
--      该会话下未保存的生成结果
--   3. 角色支持结构化人设 + 视觉风格(style 是"角色长期视觉一致性"核心配置) + 多版立绘
--   4. 剧情支持多版本, is_current 标记项目当前使用版本, 单点维护
--   5. 关键帧支持场景描述/画面提示词/参考图/关联角色, 作为视频生成的视觉锚点
--   6. 生成任务统一追踪 image/script/keyframe 等 AI 任务的状态与进度
--   7. 导出包为不可变快照, 统一为"角色+剧本+关键帧"单一格式(不做平台模板),
--      整理项目内容后可直接复制到外部视频大模型网站
--   8. 视频成品按单镜头片段粒度回收登记, 溯源关键帧/剧本/导出包;
--      系统不做视频生成, 整集装配发生在外部剪辑环节
--
-- 相对 v3 的主要调整:
--   - 删除 story_projects.current_script_id/current_export_id:
--     "当前剧本"由 story_scripts.is_current 单点维护, 避免双写漂移;
--     最新导出包可由 story_export_packages 按 version 派生
--   - 删除 story_keyframes.is_selected: 与 story_project_assets 编排层职责重复,
--     关键帧是否参与导出统一走编排表
--   - 删除被 UNIQUE/PK 约束完全覆盖的冗余索引
--   - 图片路径字段统一 VARCHAR(500)(关键帧/导出包路径层级较深)
--   - 视图 story_project_export_source 改为按 is_current 关联
--
-- 本轮 (story-ia-refactor) 主要调整:
--   - story_characters 归属从项目改为用户级: 移除 project_id, 新增 user_id,
--     角色跨项目复用; "项目出演哪些角色"由 story_project_assets
--     (asset_type='character') 登记, 引用而非拷贝
--   - story_projects 增加 video_count 冗余计数; character_count 语义改为出演角色数
--   - 新增 story.story_videos: 视频成品单镜头片段登记
--     (keyframe/script/export_package 溯源, 封面默认抽视频首帧)
--   - 视图 story_project_asset_stats 角色/立绘计数改为编排表口径, 并补视频计数
--
-- 约束说明: 与项目其它 schema(rag/sys/draw)一致 —— 保留 NOT NULL/UNIQUE 基础约束;
--          无外键/无触发器/无 CHECK, 关联关系与取值范围由业务层保证;
--          updated_at 由业务层显式赋值, 不加触发器
-- id 生成: PostgreSQL 18 内置 uuidv7() 默认值兜底; 业务 id 由应用端
--          (uuid_utils.compat.uuid7)生成并显式传入
-- ============================================================

-- ------------------------------------------------------------
-- 剧本相关表统一归属到独立的 story schema, 与其它业务表隔离
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS story;

-- ============================================================
-- 1. 项目
-- ============================================================
-- ------------------------------------------------------------
-- 1. 剧本项目表 story_projects
--    独立实例: 归属当前登录用户, 仅本人可见;
--    一个项目 = 一个作品, 承载剧本/角色/立绘/关键帧等全部资产;
--    冗余计数为列表展示与排序用, 业务层增删资产时同步维护
-- ------------------------------------------------------------
CREATE TABLE story.story_projects (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    user_id             VARCHAR(64) NOT NULL,           -- 属主(用户 32 位无连字符 hex)
    title               TEXT NOT NULL DEFAULT '新剧本', -- 项目标题, 前端列表展示用
    description         TEXT,                           -- 故事设定/需求描述(剧本生成的输入), 可空
    cover_image         VARCHAR(500),                   -- 项目封面图存储相对路径(data/ 下), 可空

    -- AI 创作参数(story-ai-workspace 增量, 业务层每次生成后回写, 再次生成时作默认值)
    style_key           VARCHAR(50),                    -- 最近一次生成使用的视频风格 key(风格注册表), 可空
    production_params   JSONB,                          -- 最近一次生成的制作参数(画幅/集数/基调等), 可空

    -- 冗余统计(业务层维护)
    script_count        INT NOT NULL DEFAULT 0,         -- 剧本版本数
    character_count     INT NOT NULL DEFAULT 0,         -- 出演角色数(编排表 asset_type='character')
    art_count           INT NOT NULL DEFAULT 0,         -- 选中立绘数(编排表 asset_type='character_art')
    keyframe_count      INT NOT NULL DEFAULT 0,         -- 关键帧数
    video_count         INT NOT NULL DEFAULT 0,         -- 视频成品数
    session_count       INT NOT NULL DEFAULT 0,         -- 生成会话数
    generation_count    INT NOT NULL DEFAULT 0,         -- AI 生成任务数
    last_generated_at   TIMESTAMPTZ,                    -- 最近生成时间, 列表排序用

    status              VARCHAR(20) NOT NULL DEFAULT 'active', -- 'active'/'archived'/'deleted', 业务层校验

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_projects_user   ON story.story_projects (user_id);
CREATE INDEX idx_story_projects_status ON story.story_projects (user_id, status);

-- ============================================================
-- 2. 生成会话
-- ============================================================
-- ------------------------------------------------------------
-- 2. 生成会话表 story_sessions
--    承载一次创作过程的生成历史: AI 生成结果默认全部保留在会话内,
--    用户选择"保存到项目"后才沉淀为资产; 删除会话(连同消息)即丢弃
--    该会话下未保存的生成结果;
--    type 标记会话类型, 便于按类型收敛历史记录
-- ------------------------------------------------------------
CREATE TABLE story.story_sessions (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    title               TEXT,                        -- 会话标题(如"剧本初稿"、"主角立绘"), 可空
    type                VARCHAR(30) NOT NULL DEFAULT 'general', -- 'general'/'script'/'character'/'character_art'/'keyframe'
    message_count       INT NOT NULL DEFAULT 0,      -- 冗余计数, 业务层写消息时同步维护
    last_message_at     TIMESTAMPTZ,                 -- 最后消息时间, 列表排序用

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_sessions_project      ON story.story_sessions (project_id);
CREATE INDEX idx_story_sessions_project_type ON story.story_sessions (project_id, type);

-- ============================================================
-- 3. 会话消息
-- ============================================================
-- ------------------------------------------------------------
-- 3. 会话消息表 story_messages
--    不可变追加 + assistant 占位终态更新模型;
--    只记录对话/生成过程, 不等同于正式资产;
--    kind 区分消息产出类型: 'script'(剧本生成) / 'character'(角色生成) /
--    'art'(立绘生成) / 'keyframe'(关键帧生成) / 'general'(一般对话);
--    assistant 消息可携带生成结果: content(剧本文本/描述) 与 image_file(生成图片);
--    prompt 记录生成提示词(再生成时复用), params 预留生成参数
-- ------------------------------------------------------------
CREATE TABLE story.story_messages (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    session_id          UUID NOT NULL,               -- 逻辑关联 story.story_sessions.id
    role                VARCHAR(20) NOT NULL,        -- 'user'/'assistant'/'system'
    kind                VARCHAR(30) NOT NULL DEFAULT 'general', -- 'general'/'script'/'character'/'art'/'keyframe'
    content             TEXT NOT NULL DEFAULT '',    -- user: 指令文本; assistant: 生成结果全文(剧本)或描述
    image_file          VARCHAR(500),                -- 生成图片存储相对路径(data/ 下); 无图为 NULL
    prompt              TEXT,                        -- 生成提示词(再生成时复用), 可空
    params              JSONB,                       -- 生成参数(模型/尺寸/seed 等), 可空
    sequence            INT NOT NULL,                -- 会话内单调序号
    status              VARCHAR(20) NOT NULL DEFAULT 'done', -- 'generating'/'done'/'stopped'/'failed'
    error               TEXT,                        -- failed 时的错误信息

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, sequence)
);

CREATE INDEX idx_story_messages_session         ON story.story_messages (session_id);
CREATE INDEX idx_story_messages_session_created ON story.story_messages (session_id, created_at);

-- ============================================================
-- 4. AI 生成任务
-- ============================================================
-- ------------------------------------------------------------
-- 4. 生成任务表 story_generation_tasks
--    将"AI 生成过程"从消息中独立出来, 统一追踪并支持前端进度展示;
--    task_type: 'script'(剧本) / 'character'(角色人设) / 'character_art'(立绘) /
--               'keyframe'(关键帧) / 'image'(通用生图, 如封面/概念图);
--    target_type/target_id: 任务产出去向(project/script/character/character_art/keyframe);
--    异步生成时 status 流转: 'pending' -> 'queued' -> 'generating' -> 'succeeded'/'failed'/'cancelled'
-- ------------------------------------------------------------
CREATE TABLE story.story_generation_tasks (
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

CREATE INDEX idx_story_generation_tasks_project        ON story.story_generation_tasks (project_id);
CREATE INDEX idx_story_generation_tasks_project_status ON story.story_generation_tasks (project_id, status);
CREATE INDEX idx_story_generation_tasks_target         ON story.story_generation_tasks (target_type, target_id);

-- ============================================================
-- 5. 剧情/剧本资产
-- ============================================================
-- ------------------------------------------------------------
-- 5. 剧本资产表 story_scripts
--    确认保存到项目的剧本: 完整剧本文本(视频大模型输入), 多版本并存;
--    version 项目内递增(如 v1 = AI 初稿, v2 = 用户修改, v3 = 再生成);
--    is_current 标记项目当前使用版本, 是"当前剧本"的唯一事实来源
--    (业务层切换时先复位再置位, 不做数据库唯一约束);
--    source_message_id / generation_task_id 追溯产出本版本的会话消息与生成任务
-- ------------------------------------------------------------
CREATE TABLE story.story_scripts (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    version             INT NOT NULL,                -- 项目内剧本版本号(从 1 递增)
    title               TEXT,                        -- 剧本标题, 可空(缺省取项目标题)
    content             TEXT NOT NULL,               -- 完整剧本文本
    source              VARCHAR(20) NOT NULL DEFAULT 'ai', -- 'ai'(生成)/'user'(手动编辑)/'upload'(上传)
    source_message_id   UUID,                        -- 来源会话消息(逻辑关联 story.story_messages.id), 手动编辑为 NULL
    generation_task_id  UUID,                        -- 来源生成任务(逻辑关联 story.story_generation_tasks.id), 可空
    is_current          BOOLEAN NOT NULL DEFAULT FALSE, -- 是否为项目当前使用版本

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (project_id, version)
);

CREATE INDEX idx_story_scripts_project         ON story.story_scripts (project_id);
CREATE INDEX idx_story_scripts_project_current ON story.story_scripts (project_id, is_current);

-- ============================================================
-- 6. 角色资产
-- ============================================================
-- ------------------------------------------------------------
-- 6. 角色表 story_characters
--    用户级角色库: 角色归属当前登录用户, 仅本人可见, 可被多个项目复用
--    (项目通过 story_project_assets 登记 asset_type='character' 出演, 引用而非拷贝);
--    角色来源: AI 从剧本/设定抽取或用户手工创建;
--    profile 为结构化人设(JSONB: 性格/身份/背景/年龄/身高 等), AI 归档结果;
--    style 为角色视觉风格(JSONB: 发型/服饰/画风/材质/色彩/镜头偏好 等),
--    是"角色长期视觉一致性"的核心配置, 供立绘/关键帧生图时复用;
--    appearance_prompt 为图像模型生成角色形象时的外观描述, 可拼接进生图提示词;
--    avatar_file 为角色列表头像(通常为主立绘的缩略图);
--    role_type 为默认角色分类(戏内角色属性, 跨项目可能不同, v1 留角色表)
-- ------------------------------------------------------------
CREATE TABLE story.story_characters (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    user_id             VARCHAR(64) NOT NULL,        -- 属主(用户 32 位无连字符 hex)
    name                VARCHAR(100) NOT NULL,       -- 角色名
    role_type           VARCHAR(50),                 -- 'protagonist'/'supporting'/'antagonist'/'npc'/'other'
    profile             JSONB NOT NULL DEFAULT '{}', -- 结构化人设(性格/身份/背景/年龄/身高等), AI 归档或用户编辑
    style               JSONB NOT NULL DEFAULT '{}', -- 视觉风格(发型/服饰/画风/材质/色彩/镜头偏好等)
    appearance_prompt   TEXT,                        -- 角色外观描述(供生图模型复用), 可空
    negative_prompt     TEXT,                        -- 负向提示词, 可空
    avatar_file         VARCHAR(500),                -- 头像图存储相对路径(data/ 下), 可空
    art_count           INT NOT NULL DEFAULT 0,      -- 冗余计数: 该角色立绘数

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_characters_user ON story.story_characters (user_id);

-- ============================================================
-- 7. 角色立绘资产
-- ============================================================
-- ------------------------------------------------------------
-- 7. 角色立绘表 story_character_arts
--    一个角色的多版立绘(换装/换表情/多角度/全身半身等);
--    立绘随角色归属用户(角色库全局化后不再按项目冗余), 项目维度经出演登记展开;
--    is_primary 标记角色的主立绘(标准形象, 一个角色建议至少保留 1 张);
--    source: 'upload'(用户上传创建) / 'ai'(图像模型生成);
--    image_file 必填, prompt/negative_prompt 为生成提示词(AI 生成时记录, 可复用于再生成);
--    status 预留 AI 生成占位: 'generating' -> 'done'/'failed'
-- ------------------------------------------------------------
CREATE TABLE story.story_character_arts (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    character_id        UUID NOT NULL,               -- 逻辑关联 story.story_characters.id
    name                VARCHAR(100),                -- 立绘名(如"常服正面"), 可空
    image_file          VARCHAR(500) NOT NULL,       -- 立绘图片存储相对路径(data/ 下)
    image_width         INT,                         -- 图片宽(px), 生成成功时回填
    image_height        INT,                         -- 图片高(px), 生成成功时回填
    art_type            VARCHAR(30) NOT NULL DEFAULT 'full_body', -- 'full_body'/'half_body'/'face'/'action'/'reference'/'other'
    source              VARCHAR(20) NOT NULL DEFAULT 'upload', -- 'upload'/'ai'
    prompt              TEXT,                        -- 生成提示词(AI 生成时记录), 可空
    negative_prompt     TEXT,                        -- 负向提示词, 可空
    params              JSONB,                       -- 生成参数(模型/尺寸/seed 等), 可空
    generation_task_id  UUID,                        -- 来源生成任务(逻辑关联 story.story_generation_tasks.id), 可空
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE, -- 是否为角色主立绘
    status              VARCHAR(20) NOT NULL DEFAULT 'done',    -- 'generating'/'done'/'failed'(预留 AI 生成用)
    error               TEXT,                        -- failed 时的错误信息

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_arts_character         ON story.story_character_arts (character_id);
CREATE INDEX idx_story_arts_character_primary ON story.story_character_arts (character_id, is_primary);

-- ============================================================
-- 8. 关键帧资产
-- ============================================================
-- ------------------------------------------------------------
-- 8. 关键帧表 story_keyframes
--    关键帧不是简单的一张图片, 而是"视频生成的视觉锚点":
--      - 对应剧情(script_id)与章节/场景/镜头编号(scene_no/shot_no)
--      - 场景/画面/镜头/光线/风格五段式描述, 供拼装视频模型提示词
--      - 正向/负向提示词(图片模型生成用)
--      - 参考图列表(reference_images JSONB, 可引用角色立绘或其他图片)
--      - 最终生成图(image_file, 图片模型产出)
--    status: 'draft'(仅编排未生成) -> 'generating' -> 'done'/'failed';
--    'archived' 归档不参与统计与导出;
--    关键帧是否参与导出由 story_project_assets 编排层统一决定(见第 10 节)
-- ------------------------------------------------------------
CREATE TABLE story.story_keyframes (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    script_id           UUID,                        -- 关联剧本版本(逻辑关联 story.story_scripts.id), 可空
    chapter_no          INT,                         -- 章节序号
    scene_no            INT,                         -- 项目内场景序号(第几个关键场景)
    shot_no             INT,                         -- 同一场景下镜头编号
    name                VARCHAR(200),                -- 关键帧名称(如"决战-全景-01"), 可空
    scene_description   TEXT,                        -- 当前场景发生了什么
    visual_description  TEXT,                        -- 画面应该长什么样
    camera_description  TEXT,                        -- 景别/机位/焦段/运动方向
    lighting_description TEXT,                       -- 光线/时间/氛围
    style_description   TEXT,                        -- 视觉风格(与角色/项目风格保持一致)
    prompt              TEXT NOT NULL,               -- 正向提示词(图片模型生成输入)
    negative_prompt     TEXT,                        -- 负向提示词
    reference_images    JSONB NOT NULL DEFAULT '[]', -- [{"type":"character","character_id":"...","image_file":"..."},{"type":"image","image_file":"..."}]
    image_file          VARCHAR(500),                -- 最终生成图存储相对路径(data/ 下), 未生成为 NULL
    image_width         INT,                         -- 图片宽(px)
    image_height        INT,                         -- 图片高(px)
    params              JSONB,                       -- 生成参数(模型/尺寸/seed 等)
    generation_task_id  UUID,                        -- 来源生成任务(逻辑关联 story.story_generation_tasks.id), 可空
    status              VARCHAR(20) NOT NULL DEFAULT 'draft', -- 'draft'/'generating'/'done'/'failed'/'archived'

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- 同一场景下镜头编号唯一; scene_no/shot_no 可空时由业务层保证唯一
    UNIQUE (project_id, scene_no, shot_no)
);

CREATE INDEX idx_story_keyframes_project ON story.story_keyframes (project_id);
CREATE INDEX idx_story_keyframes_script  ON story.story_keyframes (script_id);

-- ============================================================
-- 9. 关键帧关联角色
-- ============================================================
-- ------------------------------------------------------------
-- 9. 关键帧角色关联表 story_keyframe_characters
--    一个关键帧可出现多个角色, 一个角色也会出现在多个关键帧;
--    同时记录: character_art_id = 当前镜头实际使用的角色参考立绘,
--    character_prompt = 当前镜头中对角色的局部描述(如"愤怒的表情")
-- ------------------------------------------------------------
CREATE TABLE story.story_keyframe_characters (
    keyframe_id         UUID NOT NULL,               -- 逻辑关联 story.story_keyframes.id
    character_id        UUID NOT NULL,               -- 逻辑关联 story.story_characters.id
    character_art_id    UUID,                        -- 使用的角色参考立绘(逻辑关联 story.story_character_arts.id), 可空
    role                VARCHAR(30),                 -- 'main'/'secondary'/'background'
    character_prompt    TEXT,                        -- 当前镜头中对角色的局部描述
    sequence            INT NOT NULL DEFAULT 0,      -- 镜头内角色出场顺序(0 起)

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (keyframe_id, character_id)
);

CREATE INDEX idx_story_keyframe_characters_character ON story.story_keyframe_characters (character_id);

-- ============================================================
-- 10. 项目资产选择/编排
-- ============================================================
-- ------------------------------------------------------------
-- 10. 项目资产编排表 story_project_assets
--    "属于项目"与"项目当前要使用"是两个概念:
--    各资产表只表达归属, 本表表达编排(当前选用了哪些资产 + 导出顺序);
--    asset_type='character' 为出演登记: 引用用户级角色库中的角色(引用而非拷贝),
--    表达"本项目选用了哪些角色", sort_order 为出演顺序;
--    例如项目有 8 个剧本版本 / 5 张角色立绘 / 30 个关键帧, 导出给视频模型时
--    只选择: 当前剧本(story_scripts.is_current 单点维护, 无需重复登记) +
--            角色 A 第 2 张立绘 + 关键帧 1,2,4,8(在本表按 sort_order 排序);
--    剧本如需编排多个版本参与导出, 也可在本表登记 asset_type='script'
-- ------------------------------------------------------------
CREATE TABLE story.story_project_assets (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    asset_type          VARCHAR(30) NOT NULL,        -- 'script'/'character'/'character_art'/'keyframe'
    asset_id            UUID NOT NULL,               -- 对应资产表 id
    sort_order          INT NOT NULL DEFAULT 0,      -- 导出/展示顺序
    is_selected         BOOLEAN NOT NULL DEFAULT TRUE, -- 是否参与导出

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (project_id, asset_type, asset_id)
);

CREATE INDEX idx_story_project_assets_project ON story.story_project_assets (project_id, asset_type, is_selected);

-- ============================================================
-- 11. 外部视频模型输入包
-- ============================================================
-- ------------------------------------------------------------
-- 11. 导出包表 story_export_packages
--    用于"整理项目内容后, 直接复制到外部视频大模型网站":
--    每次导出形成不可变快照, 避免资产变更污染历史导出记录;
--    payload 为统一结构化 JSON(资产引用 + 编排结果), 前端据此转换成
--    文本 Prompt / Markdown / JSON / 纯文本 Copy;
--    prompt_text / copy_text / markdown_text 为已整理好的可直接复制文本,
--    按目标平台模板重排, 满足"无脑复制"场景;
--    version 按 (project_id, export_type) 递增, 保留全部历史导出
-- ------------------------------------------------------------
CREATE TABLE story.story_export_packages (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    name                VARCHAR(200) NOT NULL,       -- 导出包名称
    export_type         VARCHAR(30) NOT NULL DEFAULT 'video_input', -- 'video_input'/'script'/'keyframe'/'character'/'custom'
    target_platform     VARCHAR(100),                -- 外部视频大模型平台名(如"可灵""即梦"), 仅记录输出目标, 不代表本地部署
    script_id           UUID,                        -- 导出所用的剧本版本(逻辑关联 story.story_scripts.id), 可空
    payload             JSONB NOT NULL DEFAULT '{}', -- 结构化快照(资产引用 + 编排结果)
    prompt_text         TEXT NOT NULL DEFAULT '',    -- 已整理好的最终可复制文本
    copy_text           TEXT,                        -- 前端一键复制使用的纯文本(可与 prompt_text 相同, 或按平台模板重排)
    markdown_text       TEXT,                        -- Markdown 排版文本
    template_version    VARCHAR(50),                 -- 导出时采用的模板/编排规则版本
    version             INT NOT NULL DEFAULT 1,      -- (project_id, export_type) 内递增

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (project_id, export_type, version)
);

-- ============================================================
-- 12. 视频成品
-- ============================================================
-- ------------------------------------------------------------
-- 12. 视频成品表 story_videos
--     承接"成品回收"环节: 用户在外部视频生成网站产出的视频, 以单镜头片段
--     粒度登记回项目; 系统不做视频生成, 也不建模"整集"装配(剪辑在外部完成);
--     keyframe_id 为主溯源轴(一帧可多条重抽), script_id / export_package_id
--     并列保留溯源; episode_no 语义放宽为可选分组/排序号;
--     cover_file 默认由服务端抽取视频首帧, 抽帧失败留空由用户手动上传;
--     target_platform 为自由文本备注(导出格式统一, 不做平台字典)
-- ------------------------------------------------------------
CREATE TABLE story.story_videos (
    id                  UUID PRIMARY KEY DEFAULT uuidv7(),
    project_id          UUID NOT NULL,               -- 逻辑关联 story.story_projects.id
    keyframe_id         UUID,                        -- 主溯源: 来源关键帧(逻辑关联 story.story_keyframes.id), 可空
    script_id           UUID,                        -- 溯源: 基于剧本版本(逻辑关联 story.story_scripts.id), 可空
    export_package_id   UUID,                        -- 溯源: 使用的导出包(逻辑关联 story.story_export_packages.id), 可空
    title               TEXT,                        -- 片段标题(如"决战-镜头03"), 可空
    episode_no          INT,                         -- 语义放宽: 集号/分组/排序号, 可空
    video_file          VARCHAR(500) NOT NULL,       -- 视频存储相对路径(data/ 下)
    cover_file          VARCHAR(500),                -- 封面(默认抽视频首帧), 可空
    duration_ms         INT,                         -- 时长(毫秒), 可空
    file_size           BIGINT,                      -- 文件字节数, 可空
    width               INT,                         -- 视频宽(px), 可空
    height              INT,                         -- 视频高(px), 可空
    target_platform     VARCHAR(100),                -- 生成平台自由文本备注(可灵/即梦/...), 可空
    external_task_id    VARCHAR(200),                -- 外部平台任务号(回溯用), 可空
    status              VARCHAR(20) NOT NULL DEFAULT 'done', -- 'draft'/'done', 业务层校验
    remark              TEXT,                        -- 备注(如"第二次重抽版本"), 可空

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_story_videos_project  ON story.story_videos (project_id);
CREATE INDEX idx_story_videos_keyframe ON story.story_videos (keyframe_id);

-- ============================================================
-- 13. 项目当前导出资产视图
-- ============================================================
-- ------------------------------------------------------------
-- 13. 视图 story_project_export_source
--    供后端/前端快速获取"当前项目要发送给外部视频模型网站的内容";
--    仅提供基础聚合, 真正 prompt 的拼装由应用层按模板生成
-- ------------------------------------------------------------
CREATE VIEW story.story_project_export_source AS
SELECT
    p.id AS project_id,
    p.title AS project_title,
    p.description AS project_description,
    s.id AS script_id,
    s.version AS script_version,
    s.title AS script_title,
    s.content AS script_content
FROM story.story_projects p
LEFT JOIN story.story_scripts s
       ON s.project_id = p.id
      AND s.is_current = TRUE;

-- ============================================================
-- 14. 项目资产统计视图
-- ============================================================
-- ------------------------------------------------------------
-- 14. 视图 story_project_asset_stats
--    按 project_id 聚合各资产真实数量, 用于对账项目表冗余计数字段;
--    角色数/立绘数按编排表口径(出演登记/选中立绘), 与项目表计数语义一致
-- ------------------------------------------------------------
CREATE VIEW story.story_project_asset_stats AS
SELECT
    p.id AS project_id,
    COALESCE(s.script_count, 0) AS script_count,
    COALESCE(pa.character_count, 0) AS character_count,
    COALESCE(pa.art_count, 0) AS art_count,
    COALESCE(k.keyframe_count, 0) AS keyframe_count,
    COALESCE(v.video_count, 0) AS video_count
FROM story.story_projects p

LEFT JOIN (
    SELECT project_id, COUNT(*) AS script_count
    FROM story.story_scripts
    GROUP BY project_id
) s ON s.project_id = p.id

LEFT JOIN (
    SELECT project_id,
           COUNT(*) FILTER (WHERE asset_type = 'character') AS character_count,
           COUNT(*) FILTER (WHERE asset_type = 'character_art') AS art_count
    FROM story.story_project_assets
    GROUP BY project_id
) pa ON pa.project_id = p.id

LEFT JOIN (
    SELECT project_id, COUNT(*) AS keyframe_count
    FROM story.story_keyframes
    WHERE status <> 'archived'
    GROUP BY project_id
) k ON k.project_id = p.id

LEFT JOIN (
    SELECT project_id, COUNT(*) AS video_count
    FROM story.story_videos
    GROUP BY project_id
) v ON v.project_id = p.id;
