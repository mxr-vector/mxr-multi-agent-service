-- ============================================================
-- story-ia-refactor 增量 DDL：精简关键帧字段（幂等）
--
--   story.story_keyframes 只保留 prompt 作为画面描述与出图提示词，
--   移除职责重叠或从未写入的字段：
--     scene_description / visual_description / camera_description
--     lighting_description / style_description
--     negative_prompt         生图链路未消费
--     reference_images        参考图统一由出场角色立绘维护
--     image_width / image_height  从未写入
--     params                  从未写入
--
-- 注意：
--   1. DROP COLUMN 会永久丢弃上述列的数据，执行前请备份生产库。
--      如需留档，可先执行：
--      CREATE TABLE story.story_keyframes_kf_backup AS
--      SELECT id, scene_description, visual_description, camera_description,
--             lighting_description, style_description, negative_prompt,
--             reference_images, image_width, image_height, params
--      FROM story.story_keyframes;
--   2. ORM 已不再映射这些列，存量库执行本脚本前多出的列不影响服务启动；
--      本脚本用于彻底完成物理清理。
-- ============================================================

ALTER TABLE story.story_keyframes
    DROP COLUMN IF EXISTS scene_description,
    DROP COLUMN IF EXISTS visual_description,
    DROP COLUMN IF EXISTS camera_description,
    DROP COLUMN IF EXISTS lighting_description,
    DROP COLUMN IF EXISTS style_description,
    DROP COLUMN IF EXISTS negative_prompt,
    DROP COLUMN IF EXISTS reference_images,
    DROP COLUMN IF EXISTS image_width,
    DROP COLUMN IF EXISTS image_height,
    DROP COLUMN IF EXISTS params;
