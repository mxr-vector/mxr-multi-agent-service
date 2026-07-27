# system-config-management Specification

## Purpose

提供系统的参数管理能力：系统参数的增删改查（`key` 全局唯一）、
按 key 精确查询参数值、内置参数（`is_builtin`）删除保护，以及服务端
真分页列表。

## Requirements

### Requirement: 系统参数管理
系统 SHALL 提供系统参数（`sys.sys_config`）的创建、查询、更新、删除接口；`key` MUST 全局唯一；对外 ID MUST 为 32 位无连字符 hex；参数表 MUST NOT 含 `tenant_id` 字段。

#### Scenario: 创建参数
- **WHEN** 以 name、key、value、remark 调用创建接口
- **THEN** 系统持久化记录并返回完整参数信息

#### Scenario: key 重复被拒绝
- **WHEN** 创建或更新时 key 与已有参数冲突
- **THEN** 系统通过 `bad_except` 返回统一失败响应

### Requirement: 按 key 查询参数值
系统 SHALL 提供按 `key` 精确查询单个参数的接口，供其他模块与前端读取运行参数。

#### Scenario: 按 key 命中
- **WHEN** 以已存在的 key 查询
- **THEN** 返回该参数的完整信息（含 value）

#### Scenario: key 不存在
- **WHEN** 以不存在的 key 查询
- **THEN** 系统返回明确的未找到错误

### Requirement: 内置参数删除保护
`is_builtin` 为真的参数 SHALL 禁止删除；其 value 允许更新。

#### Scenario: 删除内置参数被拦截
- **WHEN** 对 is_builtin=true 的参数调用删除接口
- **THEN** 系统拒绝删除并返回明确错误信息

### Requirement: 参数真分页列表
参数列表接口 SHALL 在服务端执行过滤（keyword 模糊匹配 name/key）与分页，total MUST 为过滤后总数。

#### Scenario: 分页查询
- **WHEN** 以 page、size、keyword 请求列表
- **THEN** 返回当前页数据且 total 准确
