<script setup lang="ts">
/**
 * 出演角色面板：从角色库选入角色、排序、移除，以及项目选中立绘（导出使用）。
 */
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  characterApi,
  collectPages,
  projectApi,
  storyFileUrl,
  type StoryCharacterArtVO,
  type StoryCastingVO,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

interface CastItem {
  character: StoryCastingVO;
  arts: StoryCharacterArtVO[];
  selectedArtIds: Set<string>;
}

const loading = ref(false);
const items = ref<CastItem[]>([]);
// 选中立绘是否有改动（驱动保存按钮）
const artDirty = ref(false);

async function loadCasting() {
  loading.value = true;
  try {
    const res = await projectApi.listCasting(props.projectId);
    // 出演列表已内嵌 arts（后端批量装配），无需逐个 detail 放大 N+1
    items.value = (res.data ?? []).map((character) => ({
      character,
      arts: character.arts ?? [],
      selectedArtIds: new Set(character.selected_art_ids ?? []),
    }));
    artDirty.value = false;
  } finally {
    loading.value = false;
  }
}

onMounted(loadCasting);

// —— 添加出演 ——
const addVisible = ref(false);
const addLoading = ref(false);
const library = ref<{ id: string; name: string; avatar_file: string | null; casting: boolean }[]>([]);
const picked = ref<string[]>([]);

async function openAdd() {
  picked.value = [];
  addVisible.value = true;
  addLoading.value = true;
  try {
    const characters = await collectPages((params) => characterApi.list(params));
    const castIds = new Set(items.value.map((item) => item.character.id));
    library.value = characters.map((character) => ({
      id: character.id,
      name: character.name,
      avatar_file: character.avatar_file,
      casting: castIds.has(character.id),
    }));
  } finally {
    addLoading.value = false;
  }
}

async function handleAdd() {
  if (!picked.value.length) {
    ElMessage.warning("请先勾选角色");
    return;
  }
  for (const characterId of picked.value) {
    await projectApi.addCasting(props.projectId, characterId);
  }
  ElMessage.success("出演登记完成");
  addVisible.value = false;
  await loadCasting();
  emit("changed");
}

// —— 移除 ——
async function handleRemove(item: CastItem) {
  const confirmed = await confirmDanger(`确定将「${item.character.name}」移出本项目吗？`);
  if (!confirmed) return;
  try {
    await projectApi.removeCasting(props.projectId, item.character.id);
    ElMessage.success("已移除出演");
    await loadCasting();
    emit("changed");
  } catch {
    // 后端错误已由响应拦截器统一提示
  }
}

// —— 排序（上移/下移） ——
async function move(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= items.value.length) return;
  const ids = items.value.map((item) => item.character.id);
  [ids[index], ids[target]] = [ids[target], ids[index]];
  await projectApi.sortCasting(props.projectId, ids);
  await loadCasting();
}

// —— 立绘选择 ——
function toggleArt(item: CastItem, artId: string) {
  if (item.selectedArtIds.has(artId)) {
    item.selectedArtIds.delete(artId);
  } else {
    item.selectedArtIds.add(artId);
  }
  artDirty.value = true;
}

async function handleSaveArts() {
  const all = items.value.flatMap((item) => [...item.selectedArtIds]);
  await projectApi.setArtSelection(props.projectId, all);
  ElMessage.success("选中立绘已保存");
  await loadCasting();
  emit("changed");
}
</script>

<template>
  <div class="casting-panel">
    <div class="panel-toolbar">
      <span class="panel-hint">出演角色引用角色库（非拷贝）；选中的立绘参与导出，未选择时导出默认使用主立绘。</span>
      <div class="toolbar-actions">
        <el-button v-if="artDirty" type="primary" @click="handleSaveArts">保存选中立绘</el-button>
        <el-button type="primary" @click="openAdd">添加出演角色</el-button>
      </div>
    </div>

    <div v-loading="loading" class="cast-list">
      <el-empty v-if="!items.length && !loading" description="还没有出演角色" :image-size="90" />
      <div v-for="(item, index) in items" :key="item.character.id" class="cast-card">
        <div class="cast-head">
          <el-avatar :size="44" :src="storyFileUrl(item.character.avatar_file) || undefined">
            {{ item.character.name.slice(0, 1) }}
          </el-avatar>
          <div class="cast-meta">
            <div class="cast-name">{{ item.character.name }}</div>
            <div class="cast-sub">立绘 {{ item.arts.length }} 张</div>
          </div>
          <div class="cast-actions">
            <el-button size="small" link :disabled="index === 0" @click="move(index, -1)">上移</el-button>
            <el-button size="small" link :disabled="index === items.length - 1" @click="move(index, 1)">下移</el-button>
            <el-button size="small" link type="danger" @click="handleRemove(item)">移除</el-button>
          </div>
        </div>
        <div class="art-row">
          <div
            v-for="art in item.arts"
            :key="art.id"
            class="art-thumb"
            :class="{ active: item.selectedArtIds.has(art.id) }"
            @click="toggleArt(item, art.id)"
          >
            <el-image :src="storyFileUrl(art.image_file)" fit="cover" class="thumb-image" />
            <span v-if="art.is_primary" class="thumb-badge">主</span>
          </div>
          <span v-if="!item.arts.length" class="muted">该角色暂无立绘</span>
        </div>
      </div>
    </div>

    <!-- 添加出演 -->
    <el-dialog v-model="addVisible" title="添加出演角色" width="560px" destroy-on-close>
      <div v-loading="addLoading" class="library-list">
        <el-empty v-if="!library.length && !addLoading" description="角色库为空，请先到角色库创建" :image-size="80" />
        <el-checkbox-group v-model="picked">
          <div v-for="character in library" :key="character.id" class="library-item">
            <el-checkbox :value="character.id" :disabled="character.casting">
              <span class="library-name">{{ character.name }}</span>
              <span v-if="character.casting" class="muted">（已出演）</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </div>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAdd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.toolbar-actions {
  display: flex;
  gap: 8px;
}
.panel-hint {
  font-size: 12px;
  color: #7d879a;
}
.cast-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}
.cast-card {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  padding: 12px;
}
.cast-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cast-meta {
  flex: 1;
}
.cast-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.cast-sub {
  font-size: 12px;
  color: #7d879a;
}
.art-row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.art-thumb {
  position: relative;
  width: 72px;
  height: 72px;
  border: 2px solid transparent;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
}
.art-thumb.active {
  border-color: #526ae2;
}
.thumb-image {
  width: 100%;
  height: 100%;
  display: block;
}
.thumb-badge {
  position: absolute;
  top: 2px;
  left: 2px;
  padding: 0 4px;
  font-size: 10px;
  color: #fff;
  background: rgba(230, 162, 60, 0.9);
  border-radius: 4px;
}
.muted {
  color: #9aa4b2;
  font-size: 12px;
}
.library-list {
  max-height: 360px;
  overflow: auto;
}
.library-item {
  padding: 4px 0;
}
.library-name {
  margin-left: 4px;
}
</style>
