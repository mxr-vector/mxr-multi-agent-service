# system-dictionary-management Specification

## Purpose

提供系统的数据字典管理能力：字典类型（`type` 键全局唯一、真分页、
有数据时禁止删除）与字典数据（以 `dict_type` 字符串关联、支持排序与默认项）
的增删改查，以及修改类型键时对其下字典数据的同事务级联更新。

## Requirements

### Requirement: 字典类型管理
系统 SHALL 提供字典类型（`sys.sys_dict_type`）的创建、查询、更新、删除接口；`type` 键 MUST 全局唯一；对外 ID MUST 为 32 位无连字符 hex；字典类型表 MUST NOT 含 `tenant_id` 字段。

#### Scenario: 创建字典类型
- **WHEN** 以 name、type（如 `sys_sex`）、status、remark 调用创建接口
- **THEN** 系统持久化记录并返回含 hex 格式 id 的完整字典类型

#### Scenario: type 键重复被拒绝
- **WHEN** 创建或更新时 type 键与已有记录冲突
- **THEN** 系统通过 `bad_except` 返回统一失败响应，不写入数据

#### Scenario: 删除有数据的字典类型被拦截
- **WHEN** 删除的字典类型下仍存在字典数据
- **THEN** 系统拒绝删除并返回明确错误信息

### Requirement: 字典类型真分页列表
字典类型列表接口 SHALL 在服务端执行过滤（keyword 模糊匹配 name/type、status 过滤）与分页，返回的 total MUST 为过滤后的总数。

#### Scenario: 关键字过滤分页
- **WHEN** 以 keyword、page、size 请求列表
- **THEN** 返回匹配的当前页数据且 total 等于过滤后总条数

### Requirement: 字典数据管理
系统 SHALL 提供字典数据（`sys.sys_dict_data`）的创建、查询、更新、删除接口；字典数据以 `dict_type` 字符串关联字典类型；支持 `sort_order` 排序与 `is_default` 默认项标记。

#### Scenario: 创建字典数据
- **WHEN** 以 dict_type、label、value、sort_order 等调用创建接口
- **THEN** 系统校验 dict_type 对应的字典类型存在后持久化并返回记录

#### Scenario: 按类型查询字典项
- **WHEN** 以 dict_type 查询字典数据列表
- **THEN** 返回该类型下的字典项并按 sort_order 升序排列

### Requirement: 修改类型键级联更新
更新字典类型的 type 键时，系统 SHALL 在同一事务内级联更新其下所有字典数据的 `dict_type` 字段。

#### Scenario: 类型键变更后数据仍可按新键查询
- **WHEN** 将字典类型的 type 从 `sys_sex` 改为 `sys_gender`
- **THEN** 原有字典数据全部随之更新，按 `sys_gender` 查询可得到完整字典项
