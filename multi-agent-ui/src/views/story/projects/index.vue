<script setup lang="ts">
/**
 * 项目管理：项目卡片列表，点击进入项目工作区（剧本/关键帧/出演角色/视频成品/导出包）。
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { projectApi, storyFileUrl, type StoryProjectVO, type StoryProjectPayload } from "@/api/story";
import { confirmDanger } from "@/utils/confirm";
import { useDebouncedKeyword } from "@/composables/useDebouncedKeyword";
import { formatDateTime } from "@/utils/format";
import Pagination from "@/components/ui/Pagination.vue";
import ProjectFormDialog from "./ProjectFormDialog.vue";

const router = useRouter();

// —— 列表状态 ——
const loading = ref(false);
const list = ref<StoryProjectVO[]>([]);
const page = ref(1);
const size = ref(24);
const total = ref(0);

async function loadProjects() {
  loading.value = true;
  try {
    const res = await projectApi.list({ page: page.value, size: size.value, keyword: keyword.value || undefined });
    list.value = res.data?.items ?? [];
    total.value = res.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

// 关键词 300ms 防抖（复用共享 composable，含卸载清理），重置到第一页
const keyword = useDebouncedKeyword(() => {
  page.value = 1;
  loadProjects();
});

onMounted(loadProjects);

// —— 新建/编辑 ——
const formVisible = ref(false);
const formSubmitting = ref(false);
const editing = ref<StoryProjectVO | null>(null);

function openCreate() {
  editing.value = null;
  formVisible.value = true;
}

function openEdit(project: StoryProjectVO) {
  editing.value = project;
  formVisible.value = true;
}

async function handleSubmit(payload: StoryProjectPayload) {
  formSubmitting.value = true;
  try {
    if (editing.value) {
      await projectApi.update(editing.value.id, payload);
      ElMessage.success("项目已更新");
    } else {
      await projectApi.create(payload);
      ElMessage.success("项目已创建");
    }
    formVisible.value = false;
    await loadProjects();
  } finally {
    formSubmitting.value = false;
  }
}

// —— 进入工作区 ——
function openWorkspace(project: StoryProjectVO) {
  router.push(`/story/projects/${project.id}`);
}

// —— 删除（软删） ——
async function handleDelete(project: StoryProjectVO) {
  const confirmed = await confirmDanger(`确定删除项目「${project.title}」吗？删除后列表不可见。`);
  if (!confirmed) return;
  try {
    await projectApi.remove(project.id);
    ElMessage.success("项目已删除");
    await loadProjects();
  } catch {
    // 后端错误已由响应拦截器统一提示
  }
}
</script>

<template>
  <div class="story-projects-page list-page">
    <div class="page-toolbar">
      <div class="toolbar-left">
        <h2 class="page-title">项目管理</h2>
        <span class="page-desc">一个项目 = 一部作品：剧本、关键帧、出演角色与视频成品都在这里维护。</span>
      </div>
      <div class="toolbar-right">
        <el-input v-model="keyword" placeholder="搜索项目标题" clearable class="search-input" />
        <el-button type="primary" @click="openCreate">新建项目</el-button>
      </div>
    </div>

    <div class="list-panel">
      <div v-loading="loading" class="list-scroll">
        <div v-if="list.length" class="card-grid">
          <div v-for="project in list" :key="project.id" class="project-card" @click="openWorkspace(project)">
            <div class="card-cover">
              <el-image v-if="project.cover_image" :src="storyFileUrl(project.cover_image)" fit="cover" class="cover-image" />
              <div v-else class="cover-placeholder">{{ project.title.slice(0, 1) }}</div>
              <el-tag v-if="project.status === 'archived'" class="cover-badge" size="small">已归档</el-tag>
            </div>
            <div class="card-body">
              <div class="card-title">{{ project.title }}</div>
              <div class="card-desc">{{ project.description || "暂无故事设定" }}</div>
              <div class="card-stats">
                <span>剧本 {{ project.script_count }}</span>
                <span>角色 {{ project.character_count }}</span>
                <span>关键帧 {{ project.keyframe_count }}</span>
                <span>视频 {{ project.video_count }}</span>
              </div>
              <div class="card-footer">
                <span class="card-time">{{ formatDateTime(project.updated_at) }}</span>
                <span class="card-actions" @click.stop>
                  <el-button size="small" link @click="openEdit(project)">编辑</el-button>
                  <el-button size="small" link type="danger" @click="handleDelete(project)">删除</el-button>
                </span>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!loading" description="还没有项目，点击右上角新建" :image-size="110" />
      </div>
      <div class="list-footer">
        <Pagination
          v-model:page="page"
          v-model:size="size"
          :total="total"
          :page-sizes="[12, 24, 48, 96]"
          @change="loadProjects"
        />
      </div>
    </div>

    <ProjectFormDialog
      v-model:visible="formVisible"
      :record="editing"
      :submitting="formSubmitting"
      @submit="handleSubmit"
    />
  </div>
</template>

<style scoped>
.story-projects-page {
  padding: 16px 20px;
}
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.toolbar-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.page-title {
  margin: 0;
  font-size: 18px;
  color: #1f2d3d;
}
.page-desc {
  font-size: 12px;
  color: #7d879a;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.search-input {
  width: 220px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  padding: 4px;
}
.project-card {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.project-card:hover {
  border-color: #526ae2;
  box-shadow: 0 4px 14px rgba(82, 106, 226, 0.12);
}
.card-cover {
  position: relative;
  height: 120px;
  background: #eef1f8;
}
.cover-image {
  width: 100%;
  height: 100%;
  display: block;
}
.cover-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  color: #aab4c5;
}
.cover-badge {
  position: absolute;
  top: 8px;
  right: 8px;
}
.card-body {
  padding: 10px 12px 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2d3d;
}
.card-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #7d879a;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 32px;
}
.card-stats {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  color: #4b5563;
}
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.card-time {
  font-size: 12px;
  color: #9aa4b2;
}
</style>
