# system-dept-management Specification

## Purpose

提供系统的部门树管理能力：`parent_id` 自引用树结构的增删改查、
父部门存在性校验、防环校验、删除守卫（子部门与归属用户），以及扁平
列表供前端组树。

## Requirements

### Requirement: 部门树管理
系统 SHALL 提供部门（`sys.sys_dept`）的创建、查询、更新、删除接口；部门为 `parent_id` 自引用树结构（NULL 表示顶级部门），无外键，存在性与防环由业务层保证；对外 ID MUST 为 32 位无连字符 hex；部门表 MUST NOT 含 `tenant_id` 字段。

#### Scenario: 创建子部门
- **WHEN** 以 name、parent_id、sort_order、leader、status 调用创建接口
- **THEN** 系统校验父部门存在后持久化并返回部门信息

#### Scenario: 父部门不存在被拒绝
- **WHEN** 创建或更新时 parent_id 指向不存在的部门
- **THEN** 系统通过 `bad_except` 返回统一失败响应

### Requirement: 部门防环校验
更新部门 `parent_id` 时，系统 MUST 校验新父节点不是该部门自身或其任意后代，防止树中出现环。

#### Scenario: 移动到自身后代被拦截
- **WHEN** 将部门 A 的 parent_id 更新为 A 的子孙部门
- **THEN** 系统拒绝更新并返回明确错误信息

### Requirement: 部门删除守卫
删除部门时，系统 MUST 校验其下无子部门且无关联用户（`sys_user.dept_id`），否则拒绝删除。

#### Scenario: 删除有子部门的节点被拦截
- **WHEN** 删除的部门存在子部门
- **THEN** 系统拒绝删除并返回明确错误信息

#### Scenario: 删除有用户的部门被拦截
- **WHEN** 删除的部门仍有用户归属
- **THEN** 系统拒绝删除并返回明确错误信息

### Requirement: 部门扁平列表
部门列表接口 SHALL 返回扁平结构（支持 keyword、status 服务端过滤），树形结构由前端组装。

#### Scenario: 扁平列表供前端组树
- **WHEN** 请求部门列表
- **THEN** 返回含 id、parent_id、name、sort_order 等字段的扁平数组，前端可据此组装树
