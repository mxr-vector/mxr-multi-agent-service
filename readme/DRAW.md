# Draw 系统

## 1. 先决条件

1. 配置 VISUAL_* 多模态模型（VISUAL_MODEL_NAME / VISUAL_API_URL / VISUAL_API_KEY，需支持 vision，如 step-3.7-flash）
2. 部署 drawio 并配置

```bash
podman run -d \
  --name drawio \
  --restart unless-stopped \
  -p 8080:8080 \
  jgraph/drawio
```

1. drawio 实例地址由后端运行参数 `DRAWIO_EMBED_URL` 提供（`sys.sys_config` 白名单参数，种子见 `database/sql/base_seed.sql`，可在前端模型配置页「运行参数」中修改；如 `http://localhost:8080`，同时作为 postMessage origin 校验基准）
2. 执行绘图模块建表：`database/draw_schema.sql`（draw schema 下会话/消息/图表版本三表）
3. 系统菜单已内置 AI 绘图菜单（`database/system_schema.sql` 种子，component 键 `draw`）；需为对应角色授权可见

## 2. 设计要点


正在开发中....

- 多模态模型仅输出 Mermaid：前端 mermaid.js 实时预览；点击「在 drawio 中编辑」经 embed 模式（`descriptor:{format:'mermaid',wrap:true}`）载入编辑器
- 图表版本链 append-only：AI 生成与 drawio 编辑保存均产生新版本（`parent_id` 指向基线），不覆盖旧版本
- export-server 为二期能力：一期预览由前端编辑器 `export xmlpng` 产出（内嵌 XML 的 PNG，单文件既是预览又可重载编辑）
