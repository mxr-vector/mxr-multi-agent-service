# auth-login Specification

## Purpose

提供真实的用户名/密码登录体系：服务端以 bcrypt 校验密码并签发 JWT（HS256，独立
`JWT_SECRET_KEY`），`TokenAuthMiddleware` 双通道鉴权（静态 `API_SECRET_KEY` 机器
通道与 JWT 用户通道并行有效）；内置幂等的 admin 种子用户；前端提供 `/login`
登录页、全局路由守卫与 401 自动跳转登录的完整 token 生命周期。本服务同时作为
RAG 中间件，机器调用通道的行为保持不变。

## Requirements

### Requirement: 用户名密码登录
系统 SHALL 提供 `POST /public/auth/login` 接口：以 username/password 登录，服务端以 bcrypt 校验 `sys.sys_user.password`，成功后签发 JWT（HS256，含 `user_id`、`username`、`exp`，有效期 12 小时）并连同基础用户信息返回。用户名不存在与密码错误 MUST 返回相同的错误文案；`status` 为 `disabled` 的用户 MUST 被拒绝登录并返回明确提示。登录接口 MUST 免鉴权可达（位于 `/public` 路径下）。

#### Scenario: 登录成功
- **WHEN** 以正确的 username/password 调用登录接口
- **THEN** 返回 JWT token 与用户基础信息（不含 password）

#### Scenario: 密码错误与用户不存在同文案
- **WHEN** 分别以错误密码、不存在的用户名调用登录接口
- **THEN** 两次均通过 `bad_except` 返回统一失败响应，且错误文案一致

#### Scenario: 停用用户被拒绝
- **WHEN** status=disabled 的用户以正确密码登录
- **THEN** 系统拒绝登录并返回账号已停用的明确提示

### Requirement: JWT 签发与验证
JWT MUST 以独立的 `JWT_SECRET_KEY` 环境变量（经 `ENV` 配置属性暴露）作为 HS256 签名密钥，MUST NOT 复用 `API_SECRET_KEY`；过期或签名无效的 JWT MUST 视为未认证。

#### Scenario: 过期 token 被拒绝
- **WHEN** 携带已过期的 JWT 访问受保护接口
- **THEN** 返回 HTTP 401 统一响应体

#### Scenario: 篡改 token 被拒绝
- **WHEN** 携带签名不合法的 JWT 访问受保护接口
- **THEN** 返回 HTTP 401 统一响应体

### Requirement: 双通道请求鉴权
`TokenAuthMiddleware` MUST 支持两种并行有效的凭证：`Authorization: Bearer <API_SECRET_KEY>`（机器调用）或 `Authorization: Bearer <有效 JWT>`（用户登录态），任一通过即放行；两者皆不满足 MUST 返回 HTTP 401。既有 `EXCLUDE_PATHS` 与 `/public*` 白名单行为 MUST 保持不变。JWT 通道验证通过后 SHALL 将用户标识挂载到 `request.state`，供下游读取。

#### Scenario: 静态 key 机器调用仍然可用
- **WHEN** 外部系统以 `Bearer <API_SECRET_KEY>` 调用任意受保护接口
- **THEN** 请求正常放行，行为与改造前一致

#### Scenario: JWT 用户调用放行
- **WHEN** 前端以登录获得的 JWT 调用受保护接口
- **THEN** 请求放行且 `request.state` 可读到当前用户标识

#### Scenario: 无凭证返回 401
- **WHEN** 不带 Authorization 头访问受保护接口
- **THEN** 返回 HTTP 401 统一响应体

### Requirement: 当前用户信息与登出
系统 SHALL 提供 `GET /auth/me` 返回当前 JWT 对应的用户信息（不含 password），以及 `POST /auth/logout` 接口；登出为无状态语义（服务端不维护吊销列表），前端负责清除本地 token。

#### Scenario: 查询当前用户
- **WHEN** 携带有效 JWT 调用 /auth/me
- **THEN** 返回该用户的 id、username、nickname、dept_id 等信息，不含 password

### Requirement: 默认管理员种子用户
`database/system_schema.sql` SHALL 内置可重复执行的管理员种子：username=`admin`、密码 `123456` 的预生成 bcrypt 哈希字面量，使用 `INSERT ... ON CONFLICT (username) DO NOTHING` 保证幂等。

#### Scenario: 种子幂等
- **WHEN** system_schema.sql 被重复执行
- **THEN** sys_user 中 admin 仅存在一条，且可用 admin/123456 登录成功

### Requirement: 前端登录页与路由守卫
前端 SHALL 提供 `/login` 登录页：表单默认填充 admin/123456，MUST NOT 提供注册与验证码；登录成功后 token 存 localStorage 并回跳原目标路由。全局路由守卫 MUST 在无 token 时将非 `/login` 导航重定向到 `/login?redirect=<原路径>`；axios 收到真实 HTTP 401 时 MUST 清除本地 token 并跳转登录页（替代仅弹 toast 的现状）。

#### Scenario: 未登录访问被重定向
- **WHEN** 无 token 状态下访问任意业务页面
- **THEN** 浏览器被重定向到 /login 且携带 redirect 参数

#### Scenario: 登录成功回跳
- **WHEN** 在 /login?redirect=/rag 完成登录
- **THEN** token 写入 localStorage 并跳转到 /rag

#### Scenario: token 失效自动跳登录
- **WHEN** 接口返回 HTTP 401
- **THEN** 前端清除本地 token 并跳转 /login
