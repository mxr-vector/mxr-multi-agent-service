<script setup lang="ts">
/**
 * 关键帧面板：五段式描述维护、编号冲突由后端校验、出场角色登记、导出选择。
 */
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  characterApi,
  collectPages,
  keyframeApi,
  projectApi,
  storyFileUrl,
  type StoryCharacterArtVO,
  type StoryKeyframeCharacterEntry,
  type StoryKeyframeCharacterVO,
  type StoryKeyframeVO,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  generating: "生成中",
  done: "已完成",
  failed: "失败",
  archived: "已归档",
};

const loading = ref(false);
const list = ref<StoryKeyframeVO[]>([]);

// —— 关键帧图片上传 ——
const imageInput = ref<HTMLInputElement>();
const pendingImageKeyframe = ref<StoryKeyframeVO | null>(null);
const uploadingImageId = ref<string | null>(null);

function openImagePicker(keyframe: StoryKeyframeVO) {
  pendingImageKeyframe.value = keyframe;
  imageInput.value?.click();
}

async function onImagePicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  const keyframe = pendingImageKeyframe.value;
  pendingImageKeyframe.value = null;
  if (!file || !keyframe) return;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!["png", "jpg", "jpeg", "webp"].includes(ext)) {
    ElMessage.error("仅支持 png/jpg/jpeg/webp 图片");
    return;
  }
  uploadingImageId.value = keyframe.id;
  try {
    await keyframeApi.uploadImage(keyframe.id, file);
    ElMessage.success(keyframe.image_file ? "关键帧图片已替换" : "关键帧图片已上传");
    await loadKeyframes();
  } finally {
    uploadingImageId.value = null;
  }
}

// —— 新建关键帧时附带图片 ——
const createImageInput = ref<HTMLInputElement>();
const createImageFile = ref<File | null>(null);
const createImageUrl = ref("");

function openCreateImagePicker() {
  createImageInput.value?.click();
}

function onCreateImagePicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!["png", "jpg", "jpeg", "webp"].includes(ext)) {
    ElMessage.error("仅支持 png/jpg/jpeg/webp 图片");
    return;
  }
  clearCreateImage();
  createImageFile.value = file;
  createImageUrl.value = URL.createObjectURL(file);
}

function clearCreateImage() {
  if (createImageUrl.value) URL.revokeObjectURL(createImageUrl.value);
  createImageFile.value = null;
  createImageUrl.value = "";
}

async function loadKeyframes() {
  loading.value = true;
  try {
    list.value = await collectPages((params) => keyframeApi.list(props.projectId, params));
  } finally {
    loading.value = false;
  }
}

onMounted(loadKeyframes);

// —— 创建/编辑 ——
const formVisible = ref(false);
const formSubmitting = ref(false);
const editing = ref<StoryKeyframeVO | null>(null);
const form = reactive({
  name: "",
  chapter_no: null as number | null,
  scene_no: null as number | null,
  shot_no: null as number | null,
  prompt: "",
  negative_prompt: "",
  scene_description: "",
  visual_description: "",
  camera_description: "",
  lighting_description: "",
  style_description: "",
});

function resetForm() {
  Object.assign(form, {
    name: "",
    chapter_no: null,
    scene_no: null,
    shot_no: null,
    prompt: "",
    negative_prompt: "",
    scene_description: "",
    visual_description: "",
    camera_description: "",
    lighting_description: "",
    style_description: "",
  });
}

function openCreate() {
  editing.value = null;
  resetForm();
  clearCreateImage();
  formVisible.value = true;
}

function openEdit(keyframe: StoryKeyframeVO) {
  editing.value = keyframe;
  Object.assign(form, {
    name: keyframe.name ?? "",
    chapter_no: keyframe.chapter_no,
    scene_no: keyframe.scene_no,
    shot_no: keyframe.shot_no,
    prompt: keyframe.prompt,
    negative_prompt: keyframe.negative_prompt ?? "",
    scene_description: keyframe.scene_description ?? "",
    visual_description: keyframe.visual_description ?? "",
    camera_description: keyframe.camera_description ?? "",
    lighting_description: keyframe.lighting_description ?? "",
    style_description: keyframe.style_description ?? "",
  });
  formVisible.value = true;
}

async function handleSubmit() {
  if (!form.prompt.trim()) {
    ElMessage.error("正向提示词不能为空");
    return;
  }
  formSubmitting.value = true;
  try {
    if (editing.value) {
      await keyframeApi.update(editing.value.id, {
        name: form.name.trim() || null,
        chapter_no: form.chapter_no,
        scene_no: form.scene_no,
        shot_no: form.shot_no,
        prompt: form.prompt.trim(),
        negative_prompt: form.negative_prompt.trim() || null,
        scene_description: form.scene_description.trim() || null,
        visual_description: form.visual_description.trim() || null,
        camera_description: form.camera_description.trim() || null,
        lighting_description: form.lighting_description.trim() || null,
        style_description: form.style_description.trim() || null,
      });
      ElMessage.success("关键帧已更新");
    } else {
      const created = (
        await keyframeApi.create(props.projectId, {
          name: form.name.trim() || null,
          chapter_no: form.chapter_no,
          scene_no: form.scene_no,
          shot_no: form.shot_no,
          prompt: form.prompt.trim(),
          negative_prompt: form.negative_prompt.trim() || null,
          scene_description: form.scene_description.trim() || null,
          visual_description: form.visual_description.trim() || null,
          camera_description: form.camera_description.trim() || null,
          lighting_description: form.lighting_description.trim() || null,
          style_description: form.style_description.trim() || null,
        })
      ).data;
      if (createImageFile.value) {
        try {
          await keyframeApi.uploadImage(created.id, createImageFile.value);
        } catch {
          ElMessage.warning("关键帧已创建，但图片上传失败，可在列表「上传图片」处重试");
        }
      }
      clearCreateImage();
      ElMessage.success("关键帧已创建");
    }
    formVisible.value = false;
    await loadKeyframes();
    emit("changed");
  } finally {
    formSubmitting.value = false;
  }
}

async function handleDelete(keyframe: StoryKeyframeVO) {
  const confirmed = await confirmDanger(`确定删除关键帧「${keyframe.name || "未命名"}」吗？`);
  if (!confirmed) return;
  try {
    await keyframeApi.remove(keyframe.id);
    ElMessage.success("关键帧已删除");
    await loadKeyframes();
    emit("changed");
  } catch {
    // 后端错误已由响应拦截器统一提示
  }
}

// —— 出场角色 ——
interface CastOption {
  character_id: string;
  name: string;
  checked: boolean;
  role: string;
  character_prompt: string;
  arts: StoryCharacterArtVO[];
  art_id: string;
}

const castVisible = ref(false);
const castSubmitting = ref(false);
const castTarget = ref<StoryKeyframeVO | null>(null);
const castOptions = ref<CastOption[]>([]);
// 版本令牌：弹窗快速切换关键帧时，作废在途加载，防止把 A 帧数据写进 B 帧
let castDialogToken = 0;

async function openCastDialog(keyframe: StoryKeyframeVO) {
  const token = ++castDialogToken;
  castTarget.value = keyframe;
  castOptions.value = [];
  castVisible.value = true;
  const res = await projectApi.listCasting(props.projectId);
  if (token !== castDialogToken) return;
  const existing = new Map(keyframe.characters.map((item) => [item.character_id, item]));
  const options: CastOption[] = [];
  for (const casting of res.data ?? []) {
    const hit = existing.get(casting.id);
    let arts: StoryCharacterArtVO[] = [];
    try {
      const detail = await characterApi.detail(casting.id);
      arts = detail.data?.arts ?? [];
    } catch {
      arts = [];
    }
    if (token !== castDialogToken) return;
    options.push({
      character_id: casting.id,
      name: casting.name,
      checked: hit !== undefined,
      role: hit?.role ?? "main",
      character_prompt: hit?.character_prompt ?? "",
      arts,
      art_id: hit?.character_art_id ?? "",
    });
  }
  castOptions.value = options;
  if (!options.length) {
    ElMessage.warning("请先在「出演角色」子视图为项目选入角色");
  }
}

async function handleCastSubmit() {
  if (!castTarget.value) return;
  const entries: StoryKeyframeCharacterEntry[] = castOptions.value
    .filter((option) => option.checked)
    .map((option) => ({
      character_id: option.character_id,
      character_art_id: option.art_id || null,
      role: option.role || null,
      character_prompt: option.character_prompt.trim() || null,
    }));
  castSubmitting.value = true;
  try {
    await keyframeApi.setCharacters(castTarget.value.id, entries);
    ElMessage.success("出场角色已更新");
    castVisible.value = false;
    await loadKeyframes();
  } finally {
    castSubmitting.value = false;
  }
}

// —— 导出选择 ——
const selectionVisible = ref(false);
const selectionSubmitting = ref(false);
const selectedIds = ref<string[]>([]);

function openSelection() {
  // 回显已保存的导出选择（按导出顺序），避免重新打开保存即静默清空
  selectedIds.value = list.value
    .filter((keyframe) => keyframe.is_selected)
    .sort((a, b) => a.selection_order - b.selection_order)
    .map((keyframe) => keyframe.id);
  selectionVisible.value = true;
}

async function handleSelectionSubmit() {
  selectionSubmitting.value = true;
  try {
    await keyframeApi.setSelection(props.projectId, selectedIds.value);
    ElMessage.success("导出选择已保存");
    selectionVisible.value = false;
  } finally {
    selectionSubmitting.value = false;
  }
}

function numbering(keyframe: StoryKeyframeVO): string {
  if (keyframe.scene_no == null && keyframe.shot_no == null) return "—";
  return `${keyframe.scene_no ?? "?"}-${keyframe.shot_no ?? "?"}`;
}
</script>

<template>
  <div class="keyframe-panel">
    <div class="panel-toolbar">
      <span class="panel-hint">关键帧是视频生成的视觉锚点；被选中的关键帧参与导出。</span>
      <div class="toolbar-actions">
        <el-button @click="openSelection">导出选择</el-button>
        <el-button type="primary" @click="openCreate">新建关键帧</el-button>
      </div>
    </div>

    <input
      ref="imageInput"
      type="file"
      accept=".png,.jpg,.jpeg,.webp"
      style="display: none"
      @change="onImagePicked"
    />

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column label="场景-镜头" width="100">
        <template #default="{ row }">{{ numbering(row) }}</template>
      </el-table-column>
      <el-table-column label="参考图" width="110">
        <template #default="{ row }">
          <el-image
            v-if="row.image_file"
            :src="storyFileUrl(row.image_file)"
            :preview-src-list="[storyFileUrl(row.image_file)]"
            fit="cover"
            class="kf-thumb"
            preview-teleported
          />
          <el-button
            size="small"
            link
            :loading="uploadingImageId === row.id"
            @click="openImagePicker(row)"
          >
            {{ row.image_file ? "替换图" : "上传图片" }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="名称" prop="name" min-width="130">
        <template #default="{ row }">{{ row.name || "—" }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ STATUS_LABEL[row.status] ?? row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="正向提示词" min-width="200">
        <template #default="{ row }">
          <span class="prompt-brief">
            {{ row.prompt.slice(0, 50) }}{{ row.prompt.length > 50 ? "…" : "" }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="出场角色" min-width="140">
        <template #default="{ row }">
          <span v-if="row.characters.length">
            {{
              row.characters
                .map((c: StoryKeyframeCharacterVO) => c.character_name ?? "?")
                .join("、")
            }}
          </span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" link @click="openCastDialog(row)">出场角色</el-button>
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有关键帧" :image-size="80" />
      </template>
    </el-table>

    <!-- 创建/编辑 -->
    <el-dialog
      v-model="formVisible"
      :title="editing ? '编辑关键帧' : '新建关键帧'"
      width="720px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="200" placeholder="如：决战-全景-01" />
        </el-form-item>
        <el-form-item v-if="!editing" label="关键帧图片">
          <div class="create-image">
            <el-image
              v-if="createImageUrl"
              :src="createImageUrl"
              fit="cover"
              class="create-image-preview"
            />
            <div class="create-image-actions">
              <el-button size="small" @click="openCreateImagePicker">
                {{ createImageUrl ? "重新选择" : "选择图片" }}
              </el-button>
              <el-button
                v-if="createImageUrl"
                size="small"
                link
                type="danger"
                @click="clearCreateImage"
              >
                移除
              </el-button>
              <span class="muted">可选，随关键帧一并上传</span>
            </div>
          </div>
          <input
            ref="createImageInput"
            type="file"
            accept=".png,.jpg,.jpeg,.webp"
            style="display: none"
            @change="onCreateImagePicked"
          />
        </el-form-item>
        <el-form-item label="编号">
          <div class="numbering-row">
            <el-input-number
              v-model="form.chapter_no"
              :min="0"
              controls-position="right"
              placeholder="章节"
            />
            <el-input-number
              v-model="form.scene_no"
              :min="0"
              controls-position="right"
              placeholder="场景"
            />
            <el-input-number
              v-model="form.shot_no"
              :min="0"
              controls-position="right"
              placeholder="镜头"
            />
            <span class="muted">场景 + 镜头组合项目内唯一</span>
          </div>
        </el-form-item>
        <el-form-item label="正向提示词">
          <el-input
            v-model="form.prompt"
            type="textarea"
            :rows="3"
            placeholder="图片模型生成输入"
          />
        </el-form-item>
        <el-form-item label="负向提示词">
          <el-input v-model="form.negative_prompt" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="场景描述">
          <el-input
            v-model="form.scene_description"
            type="textarea"
            :rows="2"
            placeholder="当前场景发生了什么"
          />
        </el-form-item>
        <el-form-item label="画面描述">
          <el-input
            v-model="form.visual_description"
            type="textarea"
            :rows="2"
            placeholder="画面应该长什么样"
          />
        </el-form-item>
        <el-form-item label="镜头描述">
          <el-input
            v-model="form.camera_description"
            type="textarea"
            :rows="2"
            placeholder="景别/机位/焦段/运动"
          />
        </el-form-item>
        <el-form-item label="光线描述">
          <el-input
            v-model="form.lighting_description"
            type="textarea"
            :rows="2"
            placeholder="光线/时间/氛围"
          />
        </el-form-item>
        <el-form-item label="风格描述">
          <el-input
            v-model="form.style_description"
            type="textarea"
            :rows="2"
            placeholder="与角色/项目风格一致"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="formSubmitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 出场角色 -->
    <el-dialog
      v-model="castVisible"
      :title="`出场角色 - ${castTarget?.name || '关键帧'}`"
      width="680px"
      destroy-on-close
    >
      <el-empty v-if="!castOptions.length" description="项目还没有出演角色" :image-size="80" />
      <div v-else class="cast-list">
        <div v-for="option in castOptions" :key="option.character_id" class="cast-item">
          <el-checkbox v-model="option.checked">{{ option.name }}</el-checkbox>
          <template v-if="option.checked">
            <el-select v-model="option.role" size="small" class="cast-role">
              <el-option label="主要" value="main" />
              <el-option label="次要" value="secondary" />
              <el-option label="背景" value="background" />
            </el-select>
            <el-select
              v-model="option.art_id"
              size="small"
              clearable
              placeholder="参考立绘（默认主立绘）"
              class="cast-art"
            >
              <el-option
                v-for="art in option.arts"
                :key="art.id"
                :label="art.name || (art.is_primary ? '主立绘' : '立绘')"
                :value="art.id"
              />
            </el-select>
            <el-input
              v-model="option.character_prompt"
              size="small"
              placeholder="本镜头局部描述，如：愤怒的表情"
              class="cast-prompt"
            />
          </template>
        </div>
      </div>
      <template #footer>
        <el-button @click="castVisible = false">取消</el-button>
        <el-button type="primary" :loading="castSubmitting" @click="handleCastSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 导出选择 -->
    <el-dialog v-model="selectionVisible" title="设置导出选中关键帧" width="560px" destroy-on-close>
      <span class="panel-hint">勾选参与导出的关键帧（空选即清空选择）。</span>
      <el-checkbox-group v-model="selectedIds" class="selection-group">
        <el-checkbox v-for="keyframe in list" :key="keyframe.id" :value="keyframe.id">
          {{ numbering(keyframe) }} {{ keyframe.name || "未命名" }}
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="selectionVisible = false">取消</el-button>
        <el-button type="primary" :loading="selectionSubmitting" @click="handleSelectionSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kf-thumb {
  width: 72px;
  height: 54px;
  border-radius: 6px;
  display: block;
  margin-bottom: 4px;
  cursor: zoom-in;
}
.create-image {
  display: flex;
  align-items: center;
  gap: 10px;
}
.create-image-preview {
  width: 96px;
  height: 72px;
  border-radius: 6px;
  border: 1px solid #e5e9f2;
}
.create-image-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
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
.prompt-brief {
  color: #4b5563;
}
.muted {
  color: #9aa4b2;
}
.numbering-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cast-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cast-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cast-role {
  width: 96px;
}
.cast-art {
  width: 180px;
}
.cast-prompt {
  flex: 1;
  min-width: 200px;
}
.selection-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  max-height: 320px;
  overflow: auto;
}
</style>
