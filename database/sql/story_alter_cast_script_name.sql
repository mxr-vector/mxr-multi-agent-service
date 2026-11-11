-- ============================================================
-- 增量 DDL：出演角色绑定当前剧本称呼（幂等）
--
--   story.story_project_assets 增加 script_name：
--     仅 asset_type='character' 有意义，记录角色库角色在当前剧本中的称呼；
--     导入关键帧时按该称呼/角色名自动匹配出场角色。
--
-- 注意：ORM 已映射新列，存量库须先执行本脚本再启动服务，否则
--      出演角色相关查询会因缺列报错。
-- ============================================================

ALTER TABLE story.story_project_assets
    ADD COLUMN IF NOT EXISTS script_name VARCHAR(100);

COMMENT ON COLUMN story.story_project_assets.script_name IS
    'asset_type=character 时: 该角色在当前剧本中的称呼(自动绑定关键帧出场角色用)';
