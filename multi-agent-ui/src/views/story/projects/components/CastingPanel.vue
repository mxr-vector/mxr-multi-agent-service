<script setup lang="ts">
/**
 * 出演角色面板：从角色库选入角色、排序、移除，以及项目选中立绘（导出使用）。
 */
import { computed, onMounted, ref } from "vue";
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
import Pagination from "@/components/ui/Pagination.vue";

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
const page = ref(1);
const size = ref(10);
const total = computed(() => items.value.length);
const pagedItems = computed(() => {
  const start = (page.value - 1) * size.value;
  return items.value.slice(start, start + size.value);
});
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
const library = ref<{ id: string; name: string; avatar_file: string | null; casting: boolean }[]>(
  []
);
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
  try {
    for (const characterId of picked.value) {
      await projectApi.addCasting(props.projectId, characterId);
    }
    ElMessage.success("出演登记完成");
    addVisible.value = false;
  } finally {
    await loadCasting();
    emit("changed");
  }
}

// —— 项目角色配置（剧本解析角色 ↔ 角色库角色） ——
interface ScriptRoleRow {
  key: string;
  name: string;
  role_type: string | null;
  character_id: string;
  parsed: boolean;
}

const ROLE_TYPE_LABEL: Record<string, string> = {
  protagonist: "主角",
  supporting: "配角",
  antagonist: "反派",
  npc: "配角",
  other: "其他",
};

const configVisible = ref(false);
const configLoading = ref(false);
const configSaving = ref(false);
const scriptRoles = ref<ScriptRoleRow[]>([]);

function roleTypeLabel(type: string | null): string {
  return type ? ROLE_TYPE_LABEL[type] || type : "";
}

function isRoleCharacterUsed(characterId: string, row: ScriptRoleRow): boolean {
  return scriptRoles.value.some(
    (item) => item !== row && item.character_id === characterId
  );
}

async function openCastConfig() {
  configVisible.value = true;
  configLoading.value = true;
  scriptRoles.value = [];
  try {
    const res = await projectApi.listScriptRoles(props.projectId);
    const parsedRoles = res.data ?? [];
    const bound = new Map<string, string>();
    for (const item of items.value) {
      if (item.character.script_name) {
        bound.set(item.character.script_name, item.character.id);
      }
    }
    const rows: ScriptRoleRow[] = parsedRoles.map((role) => ({
      key: `parsed:${role.name}`,
      name: role.name,
      role_type: role.role_type,
      character_id: bound.get(role.name) ?? "",
      parsed: true,
    }));
    // 保留剧本未解析到、但已经绑定的项目角色，避免保存时静默丢失
    for (const item of items.value) {
      const name = item.character.script_name;
      if (name && !parsedRoles.some((role) => role.name === name)) {
        rows.push({
          key: `existing:${name}:${item.character.id}`,
          name,
          role_type: null,
          character_id: item.character.id,
          parsed: false,
        });
      }
    }
    // 角色库名称与剧本角色同名时默认预选
    const used = new Set(rows.map((row) => row.character_id).filter(Boolean));
    for (const row of rows) {
      if (row.character_id) continue;
      const match = items.value.find(
        (item) => item.character.name === row.name && !used.has(item.character.id)
      );
      if (match) {
        row.character_id = match.character.id;
        used.add(match.character.id);
      }
    }
    scriptRoles.value = rows;
  } catch {
    // 后端错误已由响应拦截器统一提示
  } finally {
    configLoading.value = false;
  }
}

async function handleSaveCastConfig() {
  configSaving.value = true;
  try {
    const roleByCharacter = new Map<string, string>();
    for (const row of scriptRoles.value) {
      if (row.character_id) roleByCharacter.set(row.character_id, row.name);
    }
    await projectApi.setCastingScriptNames(
      props.projectId,
      items.value.map((item) => ({
        character_id: item.character.id,
        script_name: roleByCharacter.get(item.character.id) ?? null,
      }))
    );
    ElMessage.success("项目角色配置已保存");
    configVisible.value = false;
    await loadCasting();
    emit("changed");
  } catch {
    // 后端错误已由响应拦截器统一提示
  } finally {
    configSaving.value = false;
  }
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
      <span class="panel-hint">
        出演角色引用角色库；「项目角色配置」按剧本解析角色绑定角色库角色，批量导入关键帧时自动回填出场角色；选中的立绘参与导出。
      </span>
      <div class="toolbar-actions">
        <el-button v-if="artDirty" type="primary" @click="handleSaveArts">保存选中立绘</el-button>
        <el-button @click="openCastConfig">项目角色配置</el-button>
        <el-button type="primary" @click="openAdd">添加出演角色</el-button>
      </div>
    </div>

    <div v-loading="loading" class="cast-list">
      <el-empty v-if="!items.length && !loading" description="还没有出演角色" :image-size="90" />
      <div v-for="(item, pagedIndex) in pagedItems" :key="item.character.id" class="cast-card">
        <div class="cast-head">
          <el-avatar :size="44" :src="storyFileUrl(item.character.avatar_file) || undefined">
            {{ item.character.name.slice(0, 1) }}
          </el-avatar>
          <div class="cast-meta">
            <div class="cast-name">{{ item.character.name }}</div>
            <div class="cast-sub">
              立绘 {{ item.arts.length }} 张 · 项目姓名：{{
                item.character.script_name || item.character.name
              }}
            </div>
          </div>
          <div class="cast-actions">
            <el-button
              size="small"
              link
              :disabled="(page - 1) * size + pagedIndex === 0"
              @click="move((page - 1) * size + pagedIndex, -1)"
            >
              上移
            </el-button>
            <el-button
              size="small"
              link
              :disabled="(page - 1) * size + pagedIndex === items.length - 1"
              @click="move((page - 1) * size + pagedIndex, 1)"
            >
              下移
            </el-button>
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

    <div v-if="total > 0" class="panel-pagination">
      <Pagination
        v-model:page="page"
        v-model:size="size"
        :total="total"
        :page-sizes="[5, 10, 20, 50]"
      />
    </div>

    <!-- 添加出演 -->
    <el-dialog v-model="addVisible" title="添加出演角色" width="560px" append-to-body destroy-on-close>
      <div v-loading="addLoading" class="library-list">
        <el-empty
          v-if="!library.length && !addLoading"
          description="角色库为空，请先到角色库创建"
          :image-size="80"
        />
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

    <!-- 项目角色配置：剧本解析角色 ↔ 角色库角色 -->
    <el-dialog
      v-model="configVisible"
      title="项目角色配置"
      width="640px"
      append-to-body
      destroy-on-close
    >
      <div class="config-hint">
        项目角色来自当前剧本解析结果。请为每个剧本角色选择角色库中的出演角色，批量导入关键帧时将自动回填出场角色。
      </div>
      <el-alert
        v-if="!configLoading && !items.length"
        type="warning"
        :closable="false"
        show-icon
        title="还没有出演角色，请先使用「添加出演角色」选入角色库角色。"
        style="margin-bottom: 12px"
      />
      <div v-loading="configLoading" class="config-body">
        <el-empty
          v-if="!configLoading && !scriptRoles.length"
          description="当前剧本未解析到角色，请先保存剧本或检查人物小传"
          :image-size="80"
        />
        <div v-else class="config-list">
          <div
            v-for="row in scriptRoles"
            :key="row.key"
            class="config-item"
          >
            <div class="config-role">
              <span class="config-role-name">{{ row.name }}</span>
              <el-tag v-if="!row.parsed" size="small" type="info">剧本未解析</el-tag>
              <span v-else-if="row.role_type" class="muted">
                {{ roleTypeLabel(row.role_type) }}
              </span>
            </div>
            <el-select
              v-model="row.character_id"
              size="small"
              clearable
              filterable
              placeholder="选择角色库角色"
              class="config-select"
            >
              <el-option
                v-for="item in items"
                :key="item.character.id"
                :label="item.character.name"
                :value="item.character.id"
                :disabled="isRoleCharacterUsed(item.character.id, row)"
              />
            </el-select>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="configSaving"
          :disabled="configLoading || !items.length"
          @click="handleSaveCastConfig"
        >
          保存配置
        </el-button>
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
.config-hint {
  font-size: 12px;
  color: #7d879a;
  line-height: 1.6;
  margin-bottom: 12px;
}
.config-body {
  min-height: 80px;
}
.config-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 360px;
  overflow-y: auto;
}
.config-item {
  display: flex;
  align-items: center;
  gap: 10px;
}
.config-role {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.config-role-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.config-select {
  width: 220px;
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
.panel-pagination {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
</style>
