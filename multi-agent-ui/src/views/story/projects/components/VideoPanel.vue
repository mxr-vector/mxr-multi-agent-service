<script setup lang="ts">
/**
 * 视频成品面板：上传登记（服务端抽首帧封面）、列表、编辑、删除、设为项目封面。
 */
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  collectPages,
  keyframeApi,
  storyFileUrl,
  videoApi,
  type StoryVideoUpdatePayload,
  type StoryVideoVO,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const loading = ref(false);
const list = ref<StoryVideoVO[]>([]);
const keyframeNames = ref<Record<string, string>>({});

async function loadVideos() {
  loading.value = true;
  try {
    list.value = await collectPages((params) => videoApi.list(props.projectId, params));
  } finally {
    loading.value = false;
  }
}

async function loadKeyframeNames() {
  try {
    const keyframes = await collectPages((params) => keyframeApi.list(props.projectId, params));
    keyframeNames.value = Object.fromEntries(
      keyframes.map((keyframe) => [
        keyframe.id,
        keyframe.name || `场景${keyframe.scene_no ?? "?"}-镜头${keyframe.shot_no ?? "?"}`,
      ])
    );
  } catch {
    keyframeNames.value = {};
  }
}

onMounted(() => {
  loadVideos();
  loadKeyframeNames();
});

// —— 上传 ——
const uploading = ref(false);
const uploadInput = ref<HTMLInputElement>();
const uploadForm = reactive({
  title: "",
  episode_no: null as number | null,
  keyframe_id: "",
  target_platform: "",
  remark: "",
});

function openVideoPicker() {
  uploadInput.value?.click();
}

async function onVideoPicked(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!["mp4", "mov", "webm", "mkv"].includes(ext)) {
    ElMessage.error("仅支持 mp4/mov/webm/mkv 视频");
    return;
  }
  uploading.value = true;
  try {
    await videoApi.upload(props.projectId, file, {
      title: uploadForm.title.trim() || undefined,
      episode_no: uploadForm.episode_no ?? undefined,
      keyframe_id: uploadForm.keyframe_id || undefined,
      target_platform: uploadForm.target_platform.trim() || undefined,
      remark: uploadForm.remark.trim() || undefined,
    });
    ElMessage.success("视频已登记（封面默认抽取首帧）");
    Object.assign(uploadForm, { title: "", episode_no: null, keyframe_id: "", target_platform: "", remark: "" });
    await loadVideos();
    emit("changed");
  } finally {
    uploading.value = false;
  }
}

// —— 编辑 ——
const editVisible = ref(false);
const editSubmitting = ref(false);
const editing = ref<StoryVideoVO | null>(null);
const editForm = reactive({
  title: "",
  episode_no: null as number | null,
  target_platform: "",
  remark: "",
});

function openEdit(video: StoryVideoVO) {
  editing.value = video;
  Object.assign(editForm, {
    title: video.title ?? "",
    episode_no: video.episode_no,
    target_platform: video.target_platform ?? "",
    remark: video.remark ?? "",
  });
  editVisible.value = true;
}

async function handleEdit() {
  if (!editing.value) return;
  editSubmitting.value = true;
  try {
    const payload: StoryVideoUpdatePayload = {
      title: editForm.title.trim() || null,
      episode_no: editForm.episode_no,
      target_platform: editForm.target_platform.trim() || null,
      remark: editForm.remark.trim() || null,
    };
    await videoApi.update(editing.value.id, payload);
    ElMessage.success("视频已更新");
    editVisible.value = false;
    await loadVideos();
  } finally {
    editSubmitting.value = false;
  }
}

// —— 删除 ——
async function handleDelete(video: StoryVideoVO) {
  const confirmed = await confirmDanger(`确定删除视频「${video.title || "未命名片段"}」吗？`);
  if (!confirmed) return;
  try {
    await videoApi.remove(video.id);
    ElMessage.success("视频已删除");
    await loadVideos();
    emit("changed");
  } catch {
    // 后端错误已由响应拦截器统一提示
  }
}

// —— 设为项目封面 ——
async function handleSetProjectCover(video: StoryVideoVO) {
  await videoApi.setProjectCover(video.id);
  ElMessage.success("项目封面已更新");
  emit("changed");
}

// —— 播放 ——
const playVisible = ref(false);
const playing = ref<StoryVideoVO | null>(null);

function openPlay(video: StoryVideoVO) {
  playing.value = video;
  playVisible.value = true;
}

function formatDuration(ms: number | null): string {
  if (!ms) return "—";
  return `${(ms / 1000).toFixed(1)}s`;
}
</script>

<template>
  <div class="video-panel">
    <!-- 上传区 -->
    <div class="upload-card">
      <input
        ref="uploadInput"
        type="file"
        accept=".mp4,.mov,.webm,.mkv"
        style="display: none"
        @change="onVideoPicked"
      />
      <div class="upload-fields">
        <el-input v-model="uploadForm.title" placeholder="片段标题，如：镜头03" class="field-title" />
        <el-input-number v-model="uploadForm.episode_no" :min="0" controls-position="right" placeholder="分组号" />
        <el-select v-model="uploadForm.keyframe_id" clearable placeholder="溯源关键帧（可选）" class="field-keyframe">
          <el-option v-for="(name, id) in keyframeNames" :key="id" :label="name" :value="id" />
        </el-select>
        <el-input v-model="uploadForm.target_platform" placeholder="生成平台备注" class="field-platform" />
        <el-button type="primary" :loading="uploading" @click="openVideoPicker">上传视频片段</el-button>
      </div>
      <div class="upload-hint">外部平台生成后下载的视频，以单镜头片段粒度回收登记。</div>
    </div>

    <!-- 列表 -->
    <div v-loading="loading" class="video-grid-wrap">
      <div v-if="list.length" class="video-grid">
        <div v-for="video in list" :key="video.id" class="video-card">
          <div class="video-cover" @click="openPlay(video)">
            <el-image v-if="video.cover_file" :src="storyFileUrl(video.cover_file)" fit="cover" class="cover-image" />
            <div v-else class="cover-placeholder">无封面</div>
            <div class="play-mask">播放</div>
          </div>
          <div class="video-body">
            <div class="video-title">{{ video.title || "未命名片段" }}</div>
            <div class="video-meta">
              <el-tag v-if="video.keyframe_id" size="small" type="info">
                {{ keyframeNames[video.keyframe_id] ?? "关键帧溯源" }}
              </el-tag>
              <span class="meta-text">{{ formatDuration(video.duration_ms) }}</span>
              <span v-if="video.target_platform" class="meta-text">{{ video.target_platform }}</span>
            </div>
            <div class="video-actions">
              <el-button size="small" link @click="openEdit(video)">编辑</el-button>
              <el-button size="small" link @click="handleSetProjectCover(video)">设为项目封面</el-button>
              <el-button size="small" link type="danger" @click="handleDelete(video)">删除</el-button>
            </div>
          </div>
        </div>
      </div>
      <el-empty v-else-if="!loading" description="还没有视频成品" :image-size="90" />
    </div>

    <!-- 播放 -->
    <el-dialog v-model="playVisible" :title="playing?.title || '视频预览'" width="720px" destroy-on-close>
      <video v-if="playing" :src="storyFileUrl(playing.video_file)" controls autoplay class="player" />
    </el-dialog>

    <!-- 编辑 -->
    <el-dialog v-model="editVisible" title="编辑视频登记" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="标题">
          <el-input v-model="editForm.title" />
        </el-form-item>
        <el-form-item label="分组号">
          <el-input-number v-model="editForm.episode_no" :min="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="生成平台">
          <el-input v-model="editForm.target_platform" placeholder="自由备注" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.remark" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.upload-card {
  border: 1px dashed #c9d3e6;
  border-radius: 10px;
  padding: 12px;
  background: #fafbfd;
  margin-bottom: 14px;
}
.upload-fields {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.field-title {
  width: 180px;
}
.field-keyframe {
  width: 200px;
}
.field-platform {
  width: 150px;
}
.upload-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #9aa4b2;
}
.video-grid-wrap {
  min-height: 120px;
}
.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.video-card {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}
.video-cover {
  position: relative;
  height: 130px;
  background: #10131a;
  cursor: pointer;
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
  color: #8b93a5;
  font-size: 12px;
}
.play-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 13px;
  background: rgba(16, 19, 26, 0.35);
  opacity: 0;
  transition: opacity 0.2s;
}
.video-cover:hover .play-mask {
  opacity: 1;
}
.video-body {
  padding: 8px 10px 10px;
}
.video-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
}
.video-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.meta-text {
  font-size: 12px;
  color: #7d879a;
}
.video-actions {
  margin-top: 6px;
}
.player {
  width: 100%;
  max-height: 420px;
  background: #000;
}
</style>
