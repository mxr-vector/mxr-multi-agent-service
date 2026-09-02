<script setup lang="ts">
/**
 * 角色库：用户级角色列表（跨项目复用），详情管理立绘与出演情况。
 */
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  characterApi,
  storyFileUrl,
  type StoryCharacterVO,
  type StoryCharacterPayload,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";
import { useDebouncedKeyword } from "@/composables/useDebouncedKeyword";
import Pagination from "@/components/ui/Pagination.vue";
import CharacterFormDialog from "./CharacterFormDialog.vue";
import CharacterDetailDialog from "./CharacterDetailDialog.vue";

const ROLE_LABEL: Record<string, string> = {
  protagonist: "主角",
  supporting: "配角",
  antagonist: "反派",
  npc: "NPC",
  other: "其他",
};

// —— 列表状态 ——
const loading = ref(false);
const list = ref<StoryCharacterVO[]>([]);
const page = ref(1);
const size = ref(24);
const total = ref(0);

async function loadCharacters() {
  loading.value = true;
  try {
    const res = await characterApi.list({
      page: page.value,
      size: size.value,
      keyword: keyword.value || undefined,
    });
    list.value = res.data?.items ?? [];
    total.value = res.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

// 关键词 300ms 防抖（复用共享 composable，含卸载清理），重置到第一页
const keyword = useDebouncedKeyword(() => {
  page.value = 1;
  loadCharacters();
});

onMounted(loadCharacters);

// —— 新建/编辑 ——
const formVisible = ref(false);
const formSubmitting = ref(false);
const editing = ref<StoryCharacterVO | null>(null);

function openCreate() {
  editing.value = null;
  formVisible.value = true;
}

function openEdit(character: StoryCharacterVO) {
  editing.value = character;
  formVisible.value = true;
}

async function handleSubmit(payload: StoryCharacterPayload) {
  formSubmitting.value = true;
  try {
    if (editing.value) {
      await characterApi.update(editing.value.id, payload);
      ElMessage.success("角色已更新");
    } else {
      await characterApi.create(payload);
      ElMessage.success("角色已创建");
    }
    formVisible.value = false;
    await loadCharacters();
  } finally {
    formSubmitting.value = false;
  }
}

// —— 详情 ——
const detailVisible = ref(false);
const detailId = ref<string | null>(null);

function openDetail(character: StoryCharacterVO) {
  detailId.value = character.id;
  detailVisible.value = true;
}

// —— 删除 ——
async function handleDelete(character: StoryCharacterVO) {
  const confirmed = await confirmDanger(
    `确定删除角色「${character.name}」吗？其全部立绘将一并删除。`
  );
  if (!confirmed) return;
  try {
    await characterApi.remove(character.id);
    ElMessage.success("角色已删除");
    await loadCharacters();
  } catch {
    // 后端错误（如被出演/关键帧引用）已由响应拦截器统一提示
  }
}
</script>

<template>
  <div class="story-character-page list-page">
    <div class="page-toolbar">
      <div class="toolbar-left">
        <h2 class="page-title">角色库</h2>
        <span class="page-desc">角色与立绘归属个人，可在多个项目间复用。</span>
      </div>
      <div class="toolbar-right">
        <el-input v-model="keyword" placeholder="搜索角色名" clearable class="search-input" />
        <el-button type="primary" @click="openCreate">新建角色</el-button>
      </div>
    </div>

    <div class="list-panel">
      <div v-loading="loading" class="list-scroll">
        <div v-if="list.length" class="card-grid">
          <div
            v-for="character in list"
            :key="character.id"
            class="character-card"
            @click="openDetail(character)"
          >
            <el-avatar
              :size="64"
              :src="storyFileUrl(character.avatar_file) || undefined"
              class="card-avatar"
            >
              {{ character.name.slice(0, 1) }}
            </el-avatar>
            <div class="card-name">{{ character.name }}</div>
            <div class="card-meta">
              <el-tag v-if="character.role_type" size="small" type="info">
                {{ ROLE_LABEL[character.role_type] ?? character.role_type }}
              </el-tag>
              <span class="card-count">立绘 {{ character.art_count }}</span>
            </div>
            <div class="card-actions" @click.stop>
              <el-button size="small" link @click="openEdit(character)">编辑</el-button>
              <el-button size="small" link type="danger" @click="handleDelete(character)">
                删除
              </el-button>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!loading" description="还没有角色，点击右上角新建" :image-size="110" />
      </div>
      <div class="list-footer">
        <Pagination
          v-model:page="page"
          v-model:size="size"
          :total="total"
          :page-sizes="[12, 24, 48, 96]"
          @change="loadCharacters"
        />
      </div>
    </div>

    <CharacterFormDialog
      v-model:visible="formVisible"
      :record="editing"
      :submitting="formSubmitting"
      @submit="handleSubmit"
    />
    <CharacterDetailDialog
      v-model:visible="detailVisible"
      :character-id="detailId"
      @changed="loadCharacters"
    />
  </div>
</template>

<style scoped>
.story-character-page {
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
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  padding: 4px;
}
.character-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 12px 10px;
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition:
    box-shadow 0.2s,
    border-color 0.2s;
}
.character-card:hover {
  border-color: #526ae2;
  box-shadow: 0 4px 14px rgba(82, 106, 226, 0.12);
}
.card-avatar {
  margin-bottom: 8px;
}
.card-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.card-count {
  font-size: 12px;
  color: #7d879a;
}
.card-actions {
  margin-top: 6px;
}
</style>
