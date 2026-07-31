-- ============================================================
-- 系统管理表结构 (字典/参数/用户/角色/部门/菜单)
-- 本模块为纯管理数据底座: 用户/角色/菜单当前仅做 CRUD 管理,
-- 登录(JWT)、菜单驱动导航、perms 鉴权、data_scope 数据权限由后续变更接入
-- 约束说明: 保留 NOT NULL / UNIQUE 等基础完整性约束;
--          移除外键约束(关联关系由业务层保证)、触发器(updated_at 由业务层显式赋值)、
--          以及 CHECK 约束(取值范围校验放业务层, 避免不同数据库方言差异导致迁移困难)
-- id 生成: 使用 PostgreSQL 18 内置的 uuidv7() (要求 PG >= 18), 时间有序 UUID,
--         写入 B-tree 主键索引时局部性好, 对外序列化统一为 32 位无连字符 hex
-- 说明: 系统管理数据为全局管理底座, 不携带租户/部门隔离字段;
--       username/role_key/type/key 等业务键均为全局唯一
-- ============================================================

-- ------------------------------------------------------------
-- 系统管理相关表统一归属到独立的 sys schema, 与 rag 等业务表隔离
-- ------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS sys;

-- ------------------------------------------------------------
-- 1. 字典类型表 sys_dict_type
--    "有哪些字典"(如 用户性别/菜单状态), type 为业务键(如 'sys_sex'),
--    字典数据通过 dict_type 字符串关联本表 type, 修改 type 时业务层级联更新
-- ------------------------------------------------------------
CREATE TABLE sys.sys_dict_type (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    name        VARCHAR(100) NOT NULL,        -- 字典名称, 如 '用户性别'
    type        VARCHAR(100) NOT NULL,        -- 字典类型键, 如 'sys_sex', 全局唯一
    status      VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active'/'disabled', 业务层校验
    remark      TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (type)
);

-- ------------------------------------------------------------
-- 2. 字典数据表 sys_dict_data
--    每个字典类型下的枚举项(label/value), 以 dict_type 字符串关联
--    sys_dict_type.type(免 join, 消费场景为前端下拉框按 type 取数)
-- ------------------------------------------------------------
CREATE TABLE sys.sys_dict_data (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    dict_type   VARCHAR(100) NOT NULL,        -- 逻辑关联 sys.sys_dict_type.type, 业务层保证存在性
    label       VARCHAR(100) NOT NULL,        -- 展示文案, 如 '男'
    value       VARCHAR(100) NOT NULL,        -- 存储值, 如 '0'
    sort_order  INT NOT NULL DEFAULT 0,       -- 同类型内排序
    is_default  BOOLEAN NOT NULL DEFAULT FALSE, -- 是否默认选项
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    remark      TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sys_dict_data_type   ON sys.sys_dict_data (dict_type);

-- ------------------------------------------------------------
-- 3. 参数配置表 sys_config
--    键值对运行参数, key 全局唯一; is_builtin 为内置参数, 禁止删除(允许改 value)
-- ------------------------------------------------------------
CREATE TABLE sys.sys_config (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    name        VARCHAR(100) NOT NULL,        -- 参数名称, 如 '用户初始密码'
    key         VARCHAR(100) NOT NULL,        -- 参数键, 如 'sys.user.init_password', 全局唯一
    value       TEXT,                         -- 参数值
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE, -- 内置参数删除保护
    remark      TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (key)
);

-- ------------------------------------------------------------
-- 3.1 模型配置表 sys_model_config
--    每行一个模型角色(chat/rewrite/visual/rerank), role 全局唯一;
--    一行对应前端一张配置卡片; is_builtin 内置行禁止删除(允许改值);
--    api_key 落盘明文, 查询接口返回掩码(脱敏在 service 层)
-- ------------------------------------------------------------
CREATE TABLE sys.sys_model_config (
    id           UUID PRIMARY KEY DEFAULT uuidv7(),
    role         VARCHAR(20) NOT NULL,          -- 'chat'/'rewrite'/'visual'/'rerank', 全局唯一
    name         VARCHAR(100) NOT NULL,         -- 卡片标题(中文名), 如 '对话模型'
    model_name   VARCHAR(200) NOT NULL,         -- 模型名
    api_url      TEXT NOT NULL,                 -- 接口地址(OpenAI 兼容 base_url)
    api_key      TEXT NOT NULL,                 -- 凭证, 落盘明文, 响应掩码
    provider     VARCHAR(50),                   -- provider 标识, 目前仅 rerank 使用
    timeout      INT,                           -- 单请求超时(秒), 目前 chat/visual 使用
    max_retries  INT,                           -- 失败重试次数, 目前 chat/visual 使用
    extra        JSONB,                         -- 角色特有参数兜底
    is_builtin   BOOLEAN NOT NULL DEFAULT TRUE, -- 内置行删除保护
    remark       TEXT,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (role)
);

-- ------------------------------------------------------------
-- 4. 部门表 sys_dept
--    parent_id 自引用树(NULL 表示顶级部门), 不加外键,
--    存在性/防环由业务层保证(复刻 rag_folders 模式)
-- ------------------------------------------------------------
CREATE TABLE sys.sys_dept (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    parent_id   UUID,                         -- 逻辑关联 sys.sys_dept.id 自引用, NULL 为顶级部门
    name        VARCHAR(100) NOT NULL,
    sort_order  INT NOT NULL DEFAULT 0,       -- 同级排序
    leader      VARCHAR(100),                 -- 负责人
    status      VARCHAR(20) NOT NULL DEFAULT 'active',

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sys_dept_parent ON sys.sys_dept (parent_id);

-- ------------------------------------------------------------
-- 5. 用户表 sys_user
--    密码只存 bcrypt 哈希(业务层负责哈希与校验, 响应中永不返回);
--    dept_id 单字段关联部门(一人一主部门); username 全局唯一
-- ------------------------------------------------------------
CREATE TABLE sys.sys_user (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    username    VARCHAR(64) NOT NULL,         -- 登录名, 全局唯一
    password    VARCHAR(100) NOT NULL,        -- bcrypt 哈希, 永不明文/永不出现在响应
    nickname    VARCHAR(100),                 -- 显示名
    dept_id     UUID,                         -- 逻辑关联 sys.sys_dept.id, 业务层保证存在性
    email       VARCHAR(100),
    phone       VARCHAR(20),
    avatar      VARCHAR(200),                 -- 头像资源标识, 前端展示用
    status      VARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active'/'disabled', 本阶段仅数据标记
    remark      TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (username)
);

CREATE INDEX idx_sys_user_dept   ON sys.sys_user (dept_id);

-- ------------------------------------------------------------
-- 6. 角色表 sys_role
--    role_key 全局唯一(如 'admin'); data_scope 本阶段仅存储不参与过滤
-- ------------------------------------------------------------
CREATE TABLE sys.sys_role (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    name        VARCHAR(100) NOT NULL,        -- 角色名称, 如 '管理员'
    role_key    VARCHAR(100) NOT NULL,        -- 角色权限键, 如 'admin', 全局唯一
    data_scope  VARCHAR(20) NOT NULL DEFAULT 'all', -- 'all'/'dept'/'dept_and_child'/'self', 仅存储
    sort_order  INT NOT NULL DEFAULT 0,
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    remark      TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (role_key)
);

-- ------------------------------------------------------------
-- 7. 菜单表 sys_menu
--    parent_id 自引用树; menu_type 三种类型一步到位:
--    'dir'    目录, 仅组织层级
--    'menu'   页面菜单, path/name/component 对应前端路由
--    'button' 按钮权限项, 仅 perms 有意义(本阶段只存储不鉴权)
--    component 存前端组件键(如 'system-user'), 由前端映射为真实组件
-- ------------------------------------------------------------
CREATE TABLE sys.sys_menu (
    id          UUID PRIMARY KEY DEFAULT uuidv7(),
    parent_id   UUID,                         -- 逻辑关联 sys.sys_menu.id 自引用, NULL 为顶级
    menu_type   VARCHAR(20) NOT NULL,         -- 'dir'/'menu'/'button', 业务层校验
    name        VARCHAR(100),                 -- 前端路由名, 如 'system-user' (button 为空)
    path        VARCHAR(200),                 -- 路由路径, 如 '/system/user' (button 为空)
    component   VARCHAR(100),                 -- 前端组件键, 由前端 viewModules 映射 (dir/button 为空)
    label       VARCHAR(100) NOT NULL,        -- 菜单显示名, 如 '用户管理'
    icon        VARCHAR(100),                 -- 图标键, 对应前端 NAV_ICON_ASSET
    perms       VARCHAR(100),                 -- 权限标识, 如 'system:user:delete', 本阶段仅存储
    visible     BOOLEAN NOT NULL DEFAULT TRUE, -- 是否在导航中展示
    sort_order  INT NOT NULL DEFAULT 0,
    status      VARCHAR(20) NOT NULL DEFAULT 'active',

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sys_menu_parent ON sys.sys_menu (parent_id);

-- ------------------------------------------------------------
-- 8. 用户-角色关联表 sys_user_role (N:M, 联合主键, 无独立 id)
--    分配采用全量覆盖语义: 先按 user_id 清空再批量插入, 同一事务内完成
-- ------------------------------------------------------------
CREATE TABLE sys.sys_user_role (
    user_id     UUID NOT NULL,                -- 逻辑关联 sys.sys_user.id
    role_id     UUID NOT NULL,                -- 逻辑关联 sys.sys_role.id

    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX idx_sys_user_role_role ON sys.sys_user_role (role_id);

-- ------------------------------------------------------------
-- 9. 角色-菜单关联表 sys_role_menu (N:M, 联合主键, 无独立 id)
--    分配采用全量覆盖语义: 先按 role_id 清空再批量插入, 同一事务内完成
-- ------------------------------------------------------------
CREATE TABLE sys.sys_role_menu (
    role_id     UUID NOT NULL,                -- 逻辑关联 sys.sys_role.id
    menu_id     UUID NOT NULL,                -- 逻辑关联 sys.sys_menu.id

    PRIMARY KEY (role_id, menu_id)
);

CREATE INDEX idx_sys_role_menu_menu ON sys.sys_role_menu (menu_id);

