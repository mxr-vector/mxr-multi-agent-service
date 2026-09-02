<script setup lang="ts">
/**
 * 概览面板：项目基础信息与当前剧本摘要。
 */
import type { StoryProjectDetailVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";

defineProps<{
  project: StoryProjectDetailVO;
}>();
</script>

<template>
  <div class="overview-panel">
    <el-descriptions :column="2" border>
      <el-descriptions-item label="项目标题">{{ project.title }}</el-descriptions-item>
      <el-descriptions-item label="状态">
        {{ project.status === "archived" ? "已归档" : "进行中" }}
      </el-descriptions-item>
      <el-descriptions-item label="创建时间">{{ formatDateTime(project.created_at) }}</el-descriptions-item>
      <el-descriptions-item label="更新时间">{{ formatDateTime(project.updated_at) }}</el-descriptions-item>
      <el-descriptions-item label="当前剧本">
        <template v-if="project.current_script">
          v{{ project.current_script.version }}
          <span v-if="project.current_script.title">《{{ project.current_script.title }}》</span>
          （更新于 {{ formatDateTime(project.current_script.updated_at) }}）
        </template>
        <span v-else class="muted">暂无，请到「剧本」子视图保存</span>
      </el-descriptions-item>
      <el-descriptions-item label="最近生成">{{ formatDateTime(project.last_generated_at) }}</el-descriptions-item>
      <el-descriptions-item label="故事设定" :span="2">
        {{ project.description || "—" }}
      </el-descriptions-item>
    </el-descriptions>

    <div class="overview-tips">
      <h4>推荐工作流</h4>
      <ol>
        <li>在「角色库」维护角色与立绘（跨项目复用）；</li>
        <li>在「出演角色」把角色选入本项目；</li>
        <li>在「剧本」保存并切换当前剧本版本；</li>
        <li>在「关键帧」维护场景提示词与出场角色，并设置导出选择；</li>
        <li>在「导出包」生成统一素材包，复制到外部视频网站生成；</li>
        <li>把外部生成的视频回收到「视频成品」归档。</li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.overview-panel {
  padding: 8px 4px;
}
.muted {
  color: #9aa4b2;
}
.overview-tips {
  margin-top: 18px;
  padding: 12px 16px;
  border-radius: 8px;
  background: #f7f8fc;
  font-size: 13px;
  color: #4b5563;
}
.overview-tips h4 {
  margin: 0 0 8px;
  color: #1f2d3d;
}
.overview-tips ol {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
}
</style>
