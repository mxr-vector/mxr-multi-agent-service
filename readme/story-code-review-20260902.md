# Story 模块代码审查报告

- **日期**：2026-09-02
- **级别**：max（逐行核验全部范围内文件）
- **范围**：`routers/story/`、`service/story/`、`database/story/`、`entity/story/`、`database/sql/story_schema.sql`、`database/sql/base_seed.sql`（story 相关部分），以及 `multi-agent-ui/src/{api,views}/story/` 全部新增文件
- **结论**：报告 **17** 项问题（高危 5、中危 8、低危 4）；另排查 2 项疑点后排除（见文末）

> 说明：审查过程中部分并行发现子代理的结果因一次 API 流错误中断而丢失，以下全部条目均经对范围内文件的直接逐行核验确认，未采信任何未经验证的转述。#16、#17 来自被删行为专项审计（针对本次变更中删除文件/字段所放弃行为的等价性核查），同样经逐行核验。

## 发现总览

| # | 位置 | 类别 | 严重度 | 摘要 |
|---|------|------|--------|------|
| 1 | `routers/story/video.py:152` | 正确性/安全 | 高 | 封面上传先写盘后鉴权，失败遗留孤儿文件 |
| 2 | `service/story/keyframe.py:334` | 数据完整性 | 高 | `character_art_id` 未校验存在性与归属 |
| 3 | `service/story/keyframe.py:170` | 数据完整性 | 高 | `script_id` 未校验项目归属 |
| 4 | `service/story/project.py:181` | 正确性 | 高 | 改名重写路径中所有同名段；move 静默覆盖 |
| 5 | `service/story/project.py:142` | 正确性 | 高 | 先搬文件后提交，commit 失败即图片 404 |
| 6 | `service/story/character.py:213` | 正确性/竞态 | 中 | 改名无行锁，与上传竞态覆盖立绘文件 |
| 7 | `service/story/script.py:48` | 正确性/竞态 | 中 | 并发保存版本号冲突，UNIQUE 违反返回 500 |
| 8 | `service/story/character.py:512` | 错误处理 | 中 | 选择列表传重复 id 触发 UNIQUE 返回 500 |
| 9 | `database/story/project.py:67` | 契约破坏 | 中 | `?status=deleted` 可列出软删项目 |
| 10 | `service/story/storage.py:44` | 安全 | 高 | 立绘可猜命名暴露在无鉴权 public 挂载 |
| 11 | `service/story/video.py:46` | 约定 | 低 | `ENV.get` 违反配置约定，env 键未入 `.env.sample` |
| 12 | `service/story/character.py:421` | 效率 | 低 | 卡司列表 N+1，前端再串行 30 次 detail |
| 13 | `service/story/export.py:66` | 效率 | 低 | 导出快照嵌套 N+1，锁窗口被拉长 |
| 14 | `multi-agent-ui/src/views/story/character/index.vue:34` | 一致性 | 低 | 手写防抖重复造轮子且缺卸载清理 |
| 15 | `database/story/character.py:116` | 死代码 | 低 | `touch_art_count` 无调用方；扩展名白名单三份拷贝 |
| 16 | `database/story/character.py:127` | 正确性 | 中 | 关键帧引用计数不含软删豁免，角色永久不可删 |
| 17 | `service/story/character.py:286` | 竞态 | 中 | `delete_art`/`set_primary_art` 无行锁，与上传并发致计数/主图漂移 |

## 详细发现

### 高危

#### 1. 封面上传先写盘后鉴权，失败遗留孤儿文件

- **位置**：`routers/story/video.py:152`
- **问题**：`upload_video_cover` 在 `VideoService.set_cover` 校验视频归属**之前**就把上传字节写入磁盘，失败路径无任何清理。
- **触发场景**：任意已认证用户向 `POST /story/videos/{id}/cover` 传他人的 video_id（或垃圾 id）：字节已写入 `data/story/video-cover-upload/<uuid>.<ext>`，随后 `set_cover` 在另一会话抛 `bad_except('视频不存在')` —— 请求失败但文件永久遗留磁盘，反复调用可占满磁盘。`VideoService.register` 对同类情况有回滚清理，此接口没有。
- **修复建议**：先在写盘前完成归属校验（或在同一事务/会话内校验后再落盘）；至少补齐与 `VideoService.register` 一致的失败清理逻辑。

#### 2. `character_art_id` 未校验存在性与归属

- **位置**：`service/story/keyframe.py:334`
- **问题**：`_replace_characters` 原样持久化 `character_art_id`，未校验存在性、归属及与角色的一致性（仅校验了 `character_id`）。
- **触发场景**：`PUT /story/keyframes/{id}/characters` 时把 `character_art_id` 设为不存在的 id、其他角色的立绘或他人的立绘 id：该值照常入库；keyframe 详情与导出 payload 随即携带无法解析的悬空/跨用户引用，写入时无任何报错。
- **修复建议**：写入前校验 art 存在、属于当前用户，且 `character_art.character_id == entry.character_id`。

#### 3. `script_id` 未校验项目归属

- **位置**：`service/story/keyframe.py:170`
- **问题**：`KeyframeService.create/update` 接受 `script_id` 但不校验其属于本项目（或本项目所有者），白名单直接透传进 `StoryKeyframe`。
- **触发场景**：`POST /story/projects/{id}/keyframes`（或 `PUT /story/keyframes/{id}`）时 `script_id` 指向其他项目或其他用户的剧本：keyframe 永久携带指向外部项目的来源链接。对比：`VideoService.register` 会校验 keyframe/script/export_package 与 `project_id` 的对应关系。
- **修复建议**：仿照 `VideoService.register`，校验 `script.project_id == project_id` 后再写入。

#### 4. 项目改名重写路径中所有同名段；move 静默覆盖

- **位置**：`service/story/project.py:181`
- **问题**：`_relocate_keyframe_images` 会重写路径中**所有**等于旧项目目录名的段（而非仅项目名那一段），且 `shutil.move` 会静默覆盖已存在的目标。
- **触发场景**：项目 `P` 下存在同名 keyframe `P`（路径 `story/keyframes/P/P/f.png`）：项目改名为 `Q` 后两段都被改写成 `story/keyframes/Q/Q/f.png`，而该 keyframe 并未改名 —— DB 路径与规范布局（`_keyframe_image_directory` 计算的 `story/keyframes/Q/P/…`）不一致；若目标已存在同名文件，`shutil.move` 无警告覆盖。
- **修复建议**：只改写与项目名段精确对应的那一段，或按 `_keyframe_image_directory` 规范布局重新计算目标路径；move 前检查目标已存在时报错/跳过，不要静默覆盖。

#### 5. 先搬文件后提交，commit 失败即图片 404

- **位置**：`service/story/project.py:142`
- **问题**：项目改名在 `commit` 之前就把 keyframe 图片搬到磁盘新位置，commit 失败会让 DB 路径指向旧位置。
- **触发场景**：`update()` 先执行 `_relocate_keyframe_images`（经 `to_thread` 真实 `shutil.move`）再 `session.commit()`；若 commit 失败（连接断开、其他字段触发约束），文件已在新目录而 `story_keyframes.image_file` 仍是旧路径 —— 该项目所有 keyframe 图片 404 且无修复路径。
- **修复建议**：把文件搬迁延迟到 commit 成功之后（事务后钩子/提交后再执行），或 commit 失败时回滚文件移动。

#### 10. 立绘可猜命名暴露在无鉴权 public 挂载

- **位置**：`service/story/storage.py:44`
- **问题**：角色立绘以可猜测命名（`story/characters/<角色名>/<角色名>_<n>.png`）存放在无鉴权的 public 静态挂载下，且无用户命名空间，存在跨用户泄露风险。
- **触发场景**：`infer.py` 把 `ENV.upload_dir` 挂载到 `{BASE_URL}/public/files` 且 `TokenAuthMiddleware` 豁免 `/public` —— 任何未认证方只要得知角色名（跨租户同名是常态）即可枚举 `<角色名>_1..n.png` 拿到该用户的立绘；视频/封面用的是不可猜的 uuid 名，只有角色/keyframe 的按名布局可预测。
- **修复建议**：存储路径加用户命名空间（`story/characters/<user_id>/…`）或文件名 uuid 化，对齐视频/封面的策略；如需保留原名访问，走受鉴权保护的下载接口。

### 中危

#### 6. 角色改名无行锁，与上传竞态覆盖立绘文件

- **位置**：`service/story/character.py:213`
- **问题**：角色改名（`_relocate_art_files`）未用 `add_art` 那样的行锁，并发改名+上传可能分配相同序号并让 `shutil.move` 覆盖立绘文件。
- **触发场景**：`update()` 经 `repo.get` 读取（无 FOR UPDATE），而 `add_art` 恰恰用 `get_for_update` 来串行化此类写入；改名基于目录快照计算已用序号，与并发上传创建的 `<name>_4.png` 交错后，改名把某张立绘移动到 `<new_name>_4`，`shutil.move` 静默覆盖刚上传的文件（O_EXCL 保护只存在于 `write_seq_file`，rename 路径没有）。
- **修复建议**：`update()` 改用 `get_for_update` 与 `add_art` 串行化；rename 路径的 move 采用不覆盖语义（目标存在即报错）。

#### 7. 并发保存剧本版本号冲突，返回 500

- **位置**：`service/story/script.py:48`
- **问题**：`ScriptService.save` 无行锁地计算 `next_version`，并发保存违反 `UNIQUE(project_id, version)` 并以泛化 500 暴露。
- **触发场景**：同一项目两个连续「保存新版本」请求都读到 `max(version)=N`，双双插入 `version=N+1`；第二次 flush 抛 asyncpg UniqueViolation，无任何 handler 捕获 —— 客户端收到「服务器内部错误」而非业务错误，也没有重试。
- **修复建议**：对 project 行加 `FOR UPDATE` 串行化版本分配；将 IntegrityError 映射为「版本冲突，请重试」类业务错误。

#### 8. 选择列表传重复 id 触发 UNIQUE 返回 500

- **位置**：`service/story/character.py:512`
- **问题**：`set_art_selection`（及 keyframe `set_selection`）插入请求 id 时不做去重，重复 id 触发 `UNIQUE(project_id, asset_type, asset_id)` 并返回未处理 500。
- **触发场景**：`PUT /story/projects/{id}/art-selection` 传 `art_ids=[A, A]`：第一个 `add()` flush 出 `(project, 'character_art', A)`，第二个违反 UNIQUE 抛 IntegrityError，被全局 handler 渲染成「服务器内部错误」而非校验错误。`PUT /story/projects/{id}/keyframe-selection` 传重复 keyframe id 同理。
- **修复建议**：入参保序去重（`dict.fromkeys`），或将 IntegrityError 映射为「存在重复选择项」校验提示。

#### 9. `?status=deleted` 可列出软删项目

- **位置**：`database/story/project.py:67`
- **问题**：`GET /story/projects` 接受未校验的 `status` 查询参数，`status=deleted` 可列出软删项目，破坏删除契约「软删项目（列表不可见，资产行保留）」。
- **触发场景**：`ProjectRepository.list` 在传入任意 status 时应用等值过滤，路由未加白名单直接透传原始参数，收窄后的默认范围被静默绕过。
- **修复建议**：路由层用 `Literal`/枚举白名单限定 `status` 取值集合（不含 `deleted`）。

#### 16. 关键帧引用计数不含软删豁免，角色永久不可删

> 来源：被删行为专项审计。

- **位置**：`database/story/character.py:127`（`keyframe_ref_count`）
- **问题**：角色删除的两个守卫对软删项目不对称 —— `casting_project_count`（`database/story/project.py:541`）联表 `StoryProject` 排除 `status='deleted'`，而 `keyframe_ref_count` 直接统计 `story_keyframe_characters`，无项目状态过滤。
- **触发场景**：用户创建角色 C、加入卡司、挂到某个 keyframe，然后软删该项目（`service/story/project.py:207` 保留 keyframe 行；`_PROJECT_STATUS = {"active","archived"}` 白名单拒绝 `deleted`，不存在恢复接口）：此后 `DELETE /story/characters/{C}` 永远失败，报「角色被 1 个关键帧引用，请先解除引用」，而引用它的项目在 UI 不可见、无法重开或编辑 —— 角色成为无补救路径的死库存。卡司守卫刻意做了软删豁免，关键帧守卫没有。
- **修复建议**：`keyframe_ref_count` 联表 `StoryProject` 同样排除 `status='deleted'`，与卡司守卫对齐。

#### 17. `delete_art`/`set_primary_art` 无行锁，与上传并发致计数/主图漂移

> 来源：被删行为专项审计。

- **位置**：`service/story/character.py:286`（对照 `delete_art` :355、`set_primary_art` :336）
- **问题**：立绘维护的行锁不对称 —— `add_art` 经 `get_for_update`（SELECT … FOR UPDATE）串行化，而 `delete_art` 与 `set_primary_art` 走 `_assert_owned`（`repo.get`，无锁）。并发时后提交一方的 UPDATE 会用旧状态覆盖新算出的 `art_count`/`avatar`/`is_primary`。
- **触发场景**：角色仅有一张立绘 A（主图、头像）。客户端 1 调 `delete_art(A)`，客户端 2 同时调 `add_art(B)`：客户端 2 锁行读到 `db_count=1`（A 未删），插入 B（`is_first=False`）并置 `art_count=2`；客户端 1（无锁）删除 A，算出 `art_count=0`、`avatar_file=None`，其 UPDATE 等待客户端 2 的锁释放后提交 —— 终态：B 存在但 `art_count=0`、无任何主立绘、`avatar_file` 为 NULL。卡片显示「立绘 0」，导出兜底「主立绘」（`service/story/export.py:67`）静默丢失该角色参考图。两个 `add_art` 并发无此问题（双方都加锁），只有 delete/set_primary 绕过了锁。
- **修复建议**：`delete_art`/`set_primary_art` 改用 `get_for_update` 取角色行，与 `add_art` 相同的串行化路径；删除/置主的重算逻辑置于锁内。

### 低危

#### 11. `ENV.get` 违反配置约定，env 键未入 `.env.sample`

- **位置**：`service/story/video.py:46`
- **问题**：模块级 `ENV.get("VIDEO_UPLOAD_MAX_SIZE_MB", "500")` 违反 CLAUDE.md 约定（「Add settings as `@property` on `ENV_CONFIG` backed by `self.require(...)` so missing keys fail loudly. Never call `os.getenv` in feature code.」），且该键未收录进 `env/.env.sample` —— 这是仓库特性代码中唯一一处 `ENV.get()`。
- **触发场景**：运维把 `VIDEO_UPLOAD_MAX_SIZE_MB=100` 写错文件或拼错键名 —— 不会报任何错（其他所有设置都经 `require()` fail-loudly）；代价是静默的 500MB 上传上限，以及一个会被后续设置照抄的约定破坏。
- **修复建议**：改为 `ENV_CONFIG` 的 `@property` + `require()`，键加入 `env/.env.sample`。

#### 12. 卡司列表 N+1，前端再串行 detail 放大

- **位置**：`service/story/character.py:421`
- **问题**：`CastingService.list` 存在 N+1（每个 art 一次 `get`、每个角色一次 `get`），尽管 `CharacterRepository.get_many` 已存在；前端 `CastingPanel.loadCasting` 又对每个卡司成员串行调 `characterApi.detail` 只为取 arts。
- **触发场景**：30 个卡司角色、60 张已选立绘的项目，一次请求约 91 次串行 DB 往返（asset 行 + 每个 art 的 `art_repo.get` + 每行的 `char_repo.get`），再加 30 次 HTTP detail 调用。
- **修复建议**：list 接口用现有批量 getter 内嵌 arts/characters，前端去掉逐个 detail 调用。

#### 13. 导出快照嵌套 N+1，锁窗口被拉长

- **位置**：`service/story/export.py:66`
- **问题**：`ExportService.export` 用嵌套 N+1 循环构建快照（每个 asset 行查 character、每角色查 arts、每 keyframe 查 kfc、每 kfc 查 character）。
- **触发场景**：导出含 20 个卡司角色（各 5 张立绘）、50 个已选 keyframe、每 keyframe 2 个角色的项目：单事务内串行执行 1+20+20+50+100 次查询。
- **修复建议**：用 `get_many`、现成的 `list_by_keyframes` 做批量加载，压缩到约 5 次查询并缩短锁窗口。

#### 14. 手写防抖重复造轮子且缺卸载清理

- **位置**：`multi-agent-ui/src/views/story/character/index.vue:34`（`projects/index.vue` 同）
- **问题**：两个新列表页手写 keyword 防抖（含 `window.setTimeout` ref），而 `multi-agent-ui/src/composables/useDebouncedKeyword.ts` 已封装同样逻辑，且丢失了其中的 `onBeforeUnmount` 清理；另在 4+ 个视图本地重定义 `formatDate`，而 `utils/format.ts::formatDateTime` 已存在。
- **触发场景**：输入关键词后 300ms 内离开页面，仍会在已卸载组件上触发 `loadCharacters`/`loadProjects`（浪费请求、卸载后写状态）。
- **修复建议**：改用 `useDebouncedKeyword`；日期格式化统一走 `utils/format.ts`。

#### 15. 死代码 `touch_art_count`；扩展名白名单三份拷贝

- **位置**：`database/story/character.py:116`
- **问题**：`touch_art_count` 无调用方（服务层用 `count_by_character` + `update_fields`）；`_ART_IMAGE_EXTENSIONS`（`routers/story/character.py:28`）、`_KEYFRAME_IMAGE_EXTENSIONS`（`routers/story/keyframe.py:23` 与 `service/story/keyframe.py:67`）、`COVER_IMAGE_EXTENSIONS` 是同一白名单的多份私有拷贝，新增格式时只改其一就会静默分叉。
- **修复建议**：删除 `touch_art_count`；白名单常量收进 `service/story/storage.py` 单处定义。

## 已排查并排除的疑点

| 疑点 | 结论 |
|------|------|
| 角色详情弹窗陈旧数据 | 排除。`CharacterDetailDialog.vue:75-83` 在 `watch(visible)` 中先重置 `detail.value = null` 再加载；`KeyframePanel.vue` 已有 `castDialogToken` 守卫，无陈旧渲染机制。 |
| art-selection 归属校验缺失 | 排除。卡司成员必然属于当前用户（cast 成员身份蕴含用户归属），归属校验成立。 |

### 被删行为专项审计通过项

针对本次变更删除的文件/字段（旧 `story-keyframe`、`story-script` 前端页面、`story_characters.project_id`、`story_character_arts.project_id`、`(project_id, role_type)` 索引等），以下不变量已确认重新建立或本就无影响，不构成发现：

- **project_id 字段删除**：全库无任何残留的按 project_id 访问角色/立绘的代码，访问均收敛到 user_id/character_id 维度；`openspec/changes/story-ia-refactor/design.md` 明确「未上线，无生产迁移」，无迁移缺口。
- **被删页面路由与菜单**：`multi-agent-ui/src` 与 SQL 种子中无对被删组件 key / 菜单 UUID 的残留引用；vue-router 静态路由 `story/projects/index` 与动态参数路由 `story/projects/:id` 排序正确（`router/index.ts:92` vs `:118-125`），不冲突。
- **菜单种子**：`base_seed.sql` 无被删 UUID 的 `sys_role_menu` 行；保留的两个 story 菜单未授权给任何角色与被删前一致（既有种子模式），菜单列表接口本就不按角色过滤。
- **资产行计数（recount_assets）覆盖**：所有影响计数的变更点均已重算（script 保存、keyframe 增删/归档、卡司增删、立绘选择、视频注册/删除、delete_art 跨项目重算）；项目软删保留行且无恢复接口，不存在计数陈旧路径。
- **role_type 索引删除**：`role_type` 在 story 后端无任何 WHERE 使用（仅存储/展示），丢索引不引起扫描退化。

## 修复优先级建议

1. **立即修复**（数据丢失/安全）：#1、#10、#4、#5 —— 涉及磁盘增长、跨用户泄露、文件与 DB 状态不一致。
2. **随本次迭代修复**（数据完整性/健壮性）：#2、#3、#6、#7、#8、#9、#16、#17 —— 校验补齐与并发串行化，改动面小。
3. **择机清理**：#11、#12、#13、#14、#15 —— 约定对齐与效率优化，不阻塞功能。
