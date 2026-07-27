# system-user-management Specification

## Purpose

提供系统的用户管理能力：用户的增删改查、bcrypt 密码存储与重置、
状态启停、按角色全量覆盖分配，以及服务端真分页列表。用户归属单个部门，
密码永不出现在任何响应中，`username` 全局唯一。

## Requirements

### Requirement: 用户管理
系统 SHALL 提供用户（`sys.sys_user`）的创建、查询、更新、删除接口；`username` MUST 全局唯一；用户可关联单个部门（`dept_id`）；对外 ID MUST 为 32 位无连字符 hex；用户表 MUST NOT 含 `tenant_id` 字段。

#### Scenario: 创建用户
- **WHEN** 以 username、password、nickname、dept_id、email、phone、status 调用创建接口
- **THEN** 系统校验用户名全局唯一后持久化并返回用户信息（不含密码）

#### Scenario: 用户名重复被拒绝
- **WHEN** 创建用户时 username 与已有用户冲突
- **THEN** 系统通过 `bad_except` 返回统一失败响应

### Requirement: 密码 bcrypt 哈希存储
用户密码 MUST 以 bcrypt 哈希形式存储，MUST NOT 明文落库；创建用户时密码必填；普通更新接口 MUST NOT 接受密码字段，密码变更 SHALL 通过独立的重置密码接口完成。

#### Scenario: 创建时密码被哈希
- **WHEN** 创建用户并提供明文密码
- **THEN** 数据库中 password 列为 bcrypt 哈希值，且可被 verify 校验通过

#### Scenario: 重置密码
- **WHEN** 调用重置密码接口并提供新密码
- **THEN** 系统以新的 bcrypt 哈希覆盖原值并更新 updated_at

### Requirement: 密码永不出现在响应中
所有用户查询/列表/创建/更新接口的响应 MUST NOT 包含 password 字段。

#### Scenario: 详情接口不含密码
- **WHEN** 查询用户详情
- **THEN** 响应 JSON 中不存在 password 键

### Requirement: 用户状态启停
系统 SHALL 支持通过更新接口切换用户 `status`（`active`/`disabled`），语义仅为数据标记，本阶段不关联认证行为。

#### Scenario: 停用用户
- **WHEN** 将用户 status 更新为 disabled
- **THEN** 记录更新成功且列表可按 status 过滤查出

### Requirement: 用户分配角色
系统 SHALL 提供为用户分配角色的接口（全量覆盖语义）：以 role_ids 列表替换该用户在 `sys.sys_user_role` 中的全部关联，并 SHALL 提供查询用户已分配角色的能力。

#### Scenario: 全量覆盖分配
- **WHEN** 以 role_ids=[A,B] 调用分配接口，随后以 role_ids=[B,C] 再次调用
- **THEN** 该用户最终仅关联角色 B、C

#### Scenario: 分配不存在的角色被拒绝
- **WHEN** role_ids 中包含不存在的角色 id
- **THEN** 系统拒绝本次分配并返回明确错误，不产生部分写入

### Requirement: 用户真分页列表
用户列表接口 SHALL 在服务端执行过滤（keyword 模糊匹配 username/nickname、dept_id、status）与分页，total MUST 为过滤后总数。

#### Scenario: 按部门过滤分页
- **WHEN** 以 dept_id、page、size 请求列表
- **THEN** 仅返回该部门用户的当前页数据且 total 准确
