# system-menu-management Specification

## Purpose

提供系统的菜单树管理能力：目录/菜单/按钮三种类型节点的增删改查、
`parent_id` 自引用树的防环校验、删除守卫（子节点与角色绑定），以及扁平
列表供前端组树。`perms` 本阶段仅存储；schema 内置可重复执行的"系统管理"
菜单种子数据。

## Requirements

### Requirement: 菜单树管理
系统 SHALL 提供菜单（`sys.sys_menu`）的创建、查询、更新、删除接口；菜单为 `parent_id` 自引用树结构；`menu_type` MUST 支持 `dir`/`menu`/`button` 三种类型；字段含 `path`、`name`（路由名）、`component`（前端组件键）、`label`、`icon`、`perms`、`visible`、`sort_order`、`status`；本阶段 `perms` 仅存储，不参与鉴权；对外 ID MUST 为 32 位无连字符 hex；菜单表 MUST NOT 含 `tenant_id` 字段。

#### Scenario: 创建目录与菜单
- **WHEN** 先创建 menu_type=dir 的节点，再以其为 parent_id 创建 menu_type=menu 的子节点
- **THEN** 两条记录均持久化成功，子节点 parent_id 指向目录节点

#### Scenario: 创建按钮权限项
- **WHEN** 以 menu_type=button、perms=`system:user:delete` 在某菜单节点下创建
- **THEN** 记录持久化成功且 perms 字段被完整保存

#### Scenario: 非法 menu_type 被拒绝
- **WHEN** 创建时 menu_type 不属于 dir/menu/button
- **THEN** 系统通过 `bad_except` 返回统一失败响应

### Requirement: 菜单防环校验
更新菜单 `parent_id` 时，系统 MUST 校验新父节点不是该菜单自身或其任意后代。

#### Scenario: 移动到自身后代被拦截
- **WHEN** 将菜单 M 的 parent_id 更新为 M 的子孙菜单
- **THEN** 系统拒绝更新并返回明确错误信息

### Requirement: 菜单删除守卫
删除菜单时，系统 MUST 校验其下无子菜单且未被任何角色绑定（`sys_role_menu`），否则拒绝删除。

#### Scenario: 删除有子菜单的节点被拦截
- **WHEN** 删除的菜单存在子节点
- **THEN** 系统拒绝删除并返回明确错误信息

#### Scenario: 删除被角色绑定的菜单被拦截
- **WHEN** 删除的菜单在 `sys_role_menu` 中存在关联
- **THEN** 系统拒绝删除并返回明确错误信息

### Requirement: 菜单扁平列表
菜单列表接口 SHALL 返回扁平结构（支持 keyword、status、menu_type 服务端过滤），按 sort_order 排序，树形结构由前端组装。

#### Scenario: 扁平列表供前端组树
- **WHEN** 请求菜单列表
- **THEN** 返回含 id、parent_id、menu_type、path、component、label、icon、perms、sort_order 等字段的扁平数组

### Requirement: 菜单种子数据
`database/system_schema.sql` SHALL 内置可重复执行的种子数据：一个"系统管理"`dir` 节点及其下用户、角色、部门、菜单、字典、参数六个 `menu` 子节点，`component` 存前端组件键。

#### Scenario: 重复执行种子脚本不产生重复数据
- **WHEN** system_schema.sql 的种子 INSERT 被执行两次
- **THEN** sys_menu 中系统管理相关节点仅存在一份（ON CONFLICT DO NOTHING）
