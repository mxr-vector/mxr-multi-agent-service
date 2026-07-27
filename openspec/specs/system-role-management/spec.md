# system-role-management Specification

## Purpose

提供系统的角色管理能力：角色的增删改查（`role_key` 全局唯一）、
被引用角色的删除守卫、菜单权限全量覆盖绑定与回显查询，以及服务端真分页
列表。`data_scope` 字段本阶段仅作存储。

## Requirements

### Requirement: 角色管理
系统 SHALL 提供角色（`sys.sys_role`）的创建、查询、更新、删除接口；`role_key` MUST 全局唯一；`data_scope` 字段本阶段仅作存储，不参与数据过滤；对外 ID MUST 为 32 位无连字符 hex；角色表 MUST NOT 含 `tenant_id` 字段。

#### Scenario: 创建角色
- **WHEN** 以 name、role_key、data_scope、sort_order、status、remark 调用创建接口
- **THEN** 系统校验 role_key 全局唯一后持久化并返回角色信息

#### Scenario: role_key 重复被拒绝
- **WHEN** 创建或更新时 role_key 与已有角色冲突
- **THEN** 系统通过 `bad_except` 返回统一失败响应

#### Scenario: 删除已被用户引用的角色被拦截
- **WHEN** 删除的角色在 `sys_user_role` 中仍存在关联
- **THEN** 系统拒绝删除并返回明确错误信息

### Requirement: 角色绑定菜单权限
系统 SHALL 提供为角色分配菜单的接口（全量覆盖语义）：以 menu_ids 列表在同一事务内替换该角色在 `sys.sys_role_menu` 中的全部关联；并 SHALL 提供查询角色已绑定菜单 id 列表的接口，供前端菜单树回显勾选。

#### Scenario: 全量覆盖分配菜单
- **WHEN** 以 menu_ids=[M1,M2] 调用分配接口，随后以 menu_ids=[M2,M3] 再次调用
- **THEN** 该角色最终仅绑定菜单 M2、M3

#### Scenario: 查询角色菜单用于回显
- **WHEN** 查询某角色的已绑定菜单
- **THEN** 返回该角色绑定的菜单 id 列表（hex 格式）

#### Scenario: 分配不存在的菜单被拒绝
- **WHEN** menu_ids 中包含不存在的菜单 id
- **THEN** 系统拒绝本次分配并返回明确错误，不产生部分写入

### Requirement: 角色真分页列表
角色列表接口 SHALL 在服务端执行过滤（keyword 模糊匹配 name/role_key、status）与分页，total MUST 为过滤后总数。

#### Scenario: 分页查询
- **WHEN** 以 page、size、keyword 请求列表
- **THEN** 返回当前页数据且 total 准确
