-- ============================================================
-- story-ai-workspace 增量 DDL：按章节生成视频片段（幂等，可重复执行）
--
--   story.story_videos 扩展：
--     video_file           放宽为可空（生成中 queued/generating 尚无文件）
--     source               来源：upload(外部回收) / generated(按章节编排生成)
--     prompt               生成正向提示词
--     negative_prompt      生成负向提示词
--     provider             生成服务商标识（video）
--     model                生成模型名
--     generation_params    生成参数（分辨率/画幅/时长/首帧等）
--     error_message        失败原因
--     新增 (project_id, source, status) 索引：生成面板按来源与状态轮询
--
-- 注意：ORM 已映射新列，存量库须先执行本脚本再启动服务，否则 story 视频
-- 相关接口会因缺列报错。
-- ============================================================

ALTER TABLE story.story_videos
    ALTER COLUMN video_file DROP NOT NULL;

ALTER TABLE story.story_videos
    ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'upload',
    ADD COLUMN IF NOT EXISTS prompt TEXT,
    ADD COLUMN IF NOT EXISTS negative_prompt TEXT,
    ADD COLUMN IF NOT EXISTS provider VARCHAR(100),
    ADD COLUMN IF NOT EXISTS model VARCHAR(200),
    ADD COLUMN IF NOT EXISTS generation_params JSONB,
    ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE INDEX IF NOT EXISTS idx_story_videos_source_status
    ON story.story_videos (project_id, source, status);

COMMENT ON COLUMN story.story_videos.source IS '上传回收(upload) / 按章节编排生成(generated)';
COMMENT ON COLUMN story.story_videos.status IS 'queued / generating / done / failed / cancelled';
