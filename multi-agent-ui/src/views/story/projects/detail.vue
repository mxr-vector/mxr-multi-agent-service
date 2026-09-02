<script setup lang="ts">
/**
 * 项目工作区：项目详情 + 子视图 tabs（概览/剧本/关键帧/出演角色/视频成品/导出包）。
 * 子视图标识进 URL query（?tab=keyframe）支持深链接；项目不存在统一失败提示。
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { ArrowLeft } from "@element-plus/icons-vue";
import {
  projectApi,
  storyFileUrl,
  type StoryProjectDetailVO,
  type StoryProjectPayload,
} from "@/api/story";
import ProjectFormDialog from "./ProjectFormDialog.vue";
import OverviewPanel from "./components/OverviewPanel.vue";
import ScriptPanel from "./components/ScriptPanel.vue";
import KeyframePanel from "./components/KeyframePanel.vue";
import CastingPanel from "./components/CastingPanel.vue";
import VideoPanel from "./components/VideoPanel.vue";
import ExportPanel from "./components/ExportPanel.vue";

const route = useRoute();
const router = useRouter();
const projectId = computed(() => String(route.params.id ?? ""));

const TAB_KEYS = [
  "overview",
  "script",
  "keyframe",
  "casting",
  "video",
  "export",
  "session",
] as const;
type TabKey = (typeof TAB_KEYS)[number];

const activeTab = computed<TabKey>({
  get: () => {
    const query = String(route.query.tab ?? "");
    return (TAB_KEYS as readonly string[]).includes(query) ? (query as TabKey) : "overview";
  },
  set: (value) => {
    router.replace({ path: route.path, query: { ...route.query, tab: value } });
  },
});

const loading = ref(false);
const notFound = ref(false);
const project = ref<StoryProjectDetailVO | null>(null);

async function loadProject() {
  if (!projectId.value) return;
  loading.value = true;
  try {
    const res = await projectApi.detail(projectId.value);
    project.value = res.data;
    notFound.value = false;
  } catch {
    notFound.value = true;
    project.value = null;
  } finally {
    loading.value = false;
  }
}

onMounted(loadProject);
watch(projectId, loadProject);

function goBack() {
  router.push("/story/projects/index");
}

// —— 编辑项目 ——
const editVisible = ref(false);
const editSubmitting = ref(false);

async function handleEditSubmit(payload: StoryProjectPayload) {
  editSubmitting.value = true;
  try {
    await projectApi.update(projectId.value, payload);
    ElMessage.success("项目已更新");
    editVisible.value = false;
    await loadProject();
  } finally {
    editSubmitting.value = false;
  }
}
</script>

<template>
  <div class="story-workspace list-page">
    <div v-loading="loading" class="workspace-body">
      <template v-if="project">
        <div class="workspace-head">
          <el-button :icon="ArrowLeft" text @click="goBack">返回</el-button>
          <div class="head-cover">
            <el-image
              v-if="project.cover_image"
              :src="storyFileUrl(project.cover_image)"
              fit="cover"
              class="cover-image"
            />
            <div v-else class="cover-placeholder">{{ project.title.slice(0, 1) }}</div>
          </div>
          <div class="head-main">
            <div class="head-title">
              {{ project.title }}
              <el-tag v-if="project.status === 'archived'" size="small">已归档</el-tag>
            </div>
            <div class="head-desc">{{ project.description || "暂无故事设定" }}</div>
            <div class="head-stats">
              <span>剧本 {{ project.script_count }}</span>
              <span>出演角色 {{ project.character_count }}</span>
              <span>选中立绘 {{ project.art_count }}</span>
              <span>关键帧 {{ project.keyframe_count }}</span>
              <span>视频 {{ project.video_count }}</span>
            </div>
          </div>
          <div class="head-actions">
            <el-button @click="editVisible = true">编辑项目</el-button>
          </div>
        </div>

        <el-tabs v-model="activeTab" class="workspace-tabs">
          <el-tab-pane label="概览" name="overview">
            <OverviewPanel v-if="activeTab === 'overview'" :project="project" />
          </el-tab-pane>
          <el-tab-pane label="剧本" name="script">
            <ScriptPanel
              v-if="activeTab === 'script'"
              :project-id="projectId"
              @changed="loadProject"
            />
          </el-tab-pane>
          <el-tab-pane label="关键帧" name="keyframe">
            <KeyframePanel
              v-if="activeTab === 'keyframe'"
              :project-id="projectId"
              @changed="loadProject"
            />
          </el-tab-pane>
          <el-tab-pane label="出演角色" name="casting">
            <CastingPanel
              v-if="activeTab === 'casting'"
              :project-id="projectId"
              @changed="loadProject"
            />
          </el-tab-pane>
          <el-tab-pane label="视频成品" name="video">
            <VideoPanel
              v-if="activeTab === 'video'"
              :project-id="projectId"
              @changed="loadProject"
            />
          </el-tab-pane>
          <el-tab-pane label="导出包" name="export">
            <ExportPanel v-if="activeTab === 'export'" :project-id="projectId" />
          </el-tab-pane>
          <el-tab-pane label="生成会话" name="session">
            <el-empty description="生成会话功能建设中" :image-size="100" />
          </el-tab-pane>
        </el-tabs>

        <ProjectFormDialog
          v-model:visible="editVisible"
          :record="project"
          :submitting="editSubmitting"
          @submit="handleEditSubmit"
        />
      </template>
      <el-empty v-else-if="notFound" description="项目不存在或已被删除">
        <el-button type="primary" @click="goBack">返回项目列表</el-button>
      </el-empty>
    </div>
  </div>
</template>

<style scoped>
.story-workspace {
  padding: 16px 20px;
}
.workspace-body {
  min-height: 300px;
}
.workspace-head {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 12px;
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
}
.head-cover {
  width: 120px;
  height: 80px;
  border-radius: 8px;
  overflow: hidden;
  background: #eef1f8;
  flex-shrink: 0;
}
.cover-image {
  width: 100%;
  height: 100%;
  display: block;
}
.cover-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  color: #aab4c5;
}
.head-main {
  flex: 1;
  min-width: 0;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 600;
  color: #1f2d3d;
}
.head-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #7d879a;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.head-stats {
  display: flex;
  gap: 14px;
  margin-top: 8px;
  font-size: 12px;
  color: #4b5563;
}
.workspace-tabs {
  margin-top: 12px;
}
</style>
