<script setup lang="ts">
/**
 * 关键帧面板：五段式描述维护、编号冲突由后端校验、出场角色登记、导出选择。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Loading, Picture, QuestionFilled } from "@element-plus/icons-vue";
import {
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
import Pagination from "@/components/ui/Pagination.vue";

const route = useRoute();

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
const page = ref(1);
const size = ref(20);
const total = ref(0);

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
    emit("changed");
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
    const res = await keyframeApi.list(props.projectId, { page: page.value, size: size.value });
    list.value = res.data?.items ?? [];
    total.value = res.data?.total ?? 0;
    checkAndStartPolling();
  } finally {
    loading.value = false;
  }
}

// —— 关键帧生图与多线程并发轮询 ——
const MAX_CONCURRENT_THREADS = 5;
const generatingImageMap = reactive<Record<string, boolean>>({});
const stoppingImageMap = reactive<Record<string, boolean>>({});
let pollTimer: ReturnType<typeof setInterval> | null = null;

// 表格多选行
const tableSelectedRows = ref<StoryKeyframeVO[]>([]);
function onTableSelectionChange(rows: StoryKeyframeVO[]) {
  tableSelectedRows.value = rows;
}

// 批量生成控制与进度状态
const batchDialogVisible = ref(false);
const batchConcurrency = ref(5);
const batchTargets = ref<StoryKeyframeVO[]>([]);
const batchRunning = ref(false);
const batchStopping = ref(false);
const batchProgress = reactive({
  total: 0,
  finished: 0,
  success: 0,
  failed: 0,
  active: 0,
});
let batchAbortController = { aborted: false };

const batchNoCharCount = computed(() =>
  batchTargets.value.filter((k) => !k.characters || k.characters.length === 0).length
);
const hasGeneratingKeyframes = computed(() =>
  list.value.some((k) => k.status === "generating")
);

function checkAndStartPolling() {
  if (list.value.some((k) => k.status === "generating")) {
    if (!pollTimer) {
      pollTimer = setInterval(async () => {
        try {
          const res = await keyframeApi.list(props.projectId, { page: page.value, size: size.value });
          const oldList = list.value;
          list.value = res.data?.items ?? [];
          total.value = res.data?.total ?? 0;
          emit("changed");

          // 比较前后状态变化，完成或失败时给出明确通知（若当前正在批量任务中，由总进度条提示，免过多弹窗打扰）
          if (!batchRunning.value) {
            for (const item of list.value) {
              const prev = oldList.find((k) => k.id === item.id);
              if (prev && prev.status === "generating") {
                const label = item.name ? `「${item.name}」` : numbering(item);
                if (item.status === "done") {
                  ElMessage.success(`关键帧 ${label} 图片已生成完成`);
                } else if (item.status === "failed") {
                  ElMessage.error(
                    `关键帧 ${label} 图片生成失败${item.error_message ? "：" + item.error_message : ""}`
                  );
                }
              }
            }
          }

          if (!list.value.some((k) => k.status === "generating")) {
            stopPolling();
          }
        } catch {
          stopPolling();
        }
      }, 3000);
    }
  } else {
    stopPolling();
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

onMounted(() => {
  loadKeyframes();
});
onUnmounted(() => {
  batchAbortController.aborted = true;
  stopPolling();
  clearCreateImage();
});

function tableRowClassName({ row }: { row: StoryKeyframeVO }) {
  if (route.query.focus_id && row.id === route.query.focus_id) {
    return "focused-keyframe-row";
  }
  return "";
}

async function handleGenerateImage(keyframe: StoryKeyframeVO) {
  if (keyframe.status === "generating") {
    ElMessage.info("该关键帧正在生成图片中，请稍候");
    return;
  }
  const prompt = (keyframe.prompt || "").trim();
  if (!prompt) {
    ElMessage.warning("关键帧缺少出图提示词，请先编辑补充提示词");
    return;
  }

  const currentGenerating = list.value.filter((k) => k.status === "generating").length;
  if (currentGenerating >= MAX_CONCURRENT_THREADS) {
    ElMessage.warning(
      `当前已有 ${MAX_CONCURRENT_THREADS} 个关键帧正在生成中，已达并发上限，请等待部分任务完成`
    );
    return;
  }

  const charCount = keyframe.characters?.length || 0;
  if (charCount > 0) {
    const charNames = keyframe.characters
      .map((c) => c.character_name || "角色")
      .join("、");
    try {
      await ElMessageBox.confirm(
        `系统将自动根据当前提示词及已设置的出场角色（${charNames}）形象参考图，提交给模型生成，以保证角色与画面的一致性。\n\n是否开始生成？`,
        "生成关键帧图片",
        {
          confirmButtonText: "开始生成",
          cancelButtonText: "取消",
          type: "info",
        }
      );
    } catch {
      return;
    }
  } else {
    try {
      await ElMessageBox.confirm(
        "当前关键帧尚未设置出场角色。为了保证角色形象一致性，建议先点击「出场角色」绑定角色的参考立绘后再生成。\n\n若当前镜头无需角色或为场景空镜，也可直接按当前提示词生成。确定继续提交生成吗？",
        "关键帧未设置出场角色",
        {
          confirmButtonText: "继续生成",
          cancelButtonText: "先去设置出场角色",
          distinguishCancelAndClose: true,
          type: "warning",
        }
      );
    } catch (action) {
      if (action === "cancel") {
        openCastDialog(keyframe);
      }
      return;
    }
  }

  generatingImageMap[keyframe.id] = true;
  try {
    await keyframeApi.generateImage(keyframe.id);
    keyframe.status = "generating";
    ElMessage.success(`已发起关键帧「${keyframe.name || numbering(keyframe)}」生成任务`);
    checkAndStartPolling();
    emit("changed");
  } catch {
    // 错误拦截器统一处理
  } finally {
    delete generatingImageMap[keyframe.id];
  }
}

async function handleStopGeneration(keyframe: StoryKeyframeVO) {
  try {
    await ElMessageBox.confirm(
      `确定中断关键帧「${keyframe.name || numbering(keyframe)}」的图片生成吗？\n中断后将释放任务并发槽位，可重新编辑或生成。`,
      "中断生图任务",
      {
        confirmButtonText: "确定中断",
        cancelButtonText: "继续生成",
        type: "warning",
      }
    );
  } catch {
    return;
  }

  stoppingImageMap[keyframe.id] = true;
  try {
    await keyframeApi.stopGeneration(keyframe.id);
    keyframe.status = "failed";
    keyframe.error_message = "用户主动中止生成";
    ElMessage.warning(`已中断关键帧「${keyframe.name || numbering(keyframe)}」生成任务`);
    await loadKeyframes();
    emit("changed");
  } catch {
    // 错误拦截器统一处理
  } finally {
    delete stoppingImageMap[keyframe.id];
  }
}

// —— 批量多线程生图调度 ——

// 单个关键帧轮询直到完成或失败
async function pollKeyframeUntilDone(
  keyframeId: string,
  abortSignal: { aborted: boolean }
): Promise<StoryKeyframeVO | null> {
  const maxAttempts = 120; // 5分钟保护
  let attempts = 0;
  while (!abortSignal.aborted && attempts < maxAttempts) {
    attempts++;
    await new Promise((resolve) => setTimeout(resolve, 2500));
    if (abortSignal.aborted) break;
    try {
      const res = await keyframeApi.detail(keyframeId);
      const kf = res.data;
      if (kf) {
        const idx = list.value.findIndex((k) => k.id === kf.id);
        if (idx !== -1) {
          list.value[idx] = kf;
        }
        if (kf.status !== "generating") {
          return kf;
        }
      }
    } catch {
      // 容忍单次网络抖动
    }
  }
  return null;
}

// 启动多线程工作池执行批量生成（最多支持 5 线程并发）
async function runBatchGeneration(targets: StoryKeyframeVO[], concurrency = 5) {
  if (!targets.length) return;
  batchRunning.value = true;
  batchAbortController = { aborted: false };
  batchProgress.total = targets.length;
  batchProgress.finished = 0;
  batchProgress.success = 0;
  batchProgress.failed = 0;
  batchProgress.active = 0;

  const queue = [...targets];
  const actualConcurrency = Math.min(
    Math.max(1, concurrency),
    MAX_CONCURRENT_THREADS,
    targets.length
  );

  async function worker() {
    while (queue.length > 0 && !batchAbortController.aborted) {
      const kf = queue.shift();
      if (!kf) break;

      const prompt = (kf.prompt || "").trim();
      if (!prompt) {
        batchProgress.finished++;
        batchProgress.failed++;
        ElMessage.warning(`关键帧「${kf.name || numbering(kf)}」缺少出图提示词，已跳过`);
        continue;
      }

      batchProgress.active++;
      generatingImageMap[kf.id] = true;
      try {
        await keyframeApi.generateImage(kf.id);
        kf.status = "generating";
        checkAndStartPolling();
        emit("changed");

        const finishedKf = await pollKeyframeUntilDone(kf.id, batchAbortController);
        batchProgress.finished++;
        if (finishedKf?.status === "done") {
          batchProgress.success++;
        } else {
          batchProgress.failed++;
        }
      } catch (err: any) {
        batchProgress.finished++;
        batchProgress.failed++;
        ElMessage.error(
          `关键帧「${kf.name || numbering(kf)}」发起失败: ${err.message || "请求异常"}`
        );
      } finally {
        delete generatingImageMap[kf.id];
        batchProgress.active--;
      }
    }
  }

  const workers = Array.from({ length: actualConcurrency }, () => worker());

  try {
    await Promise.all(workers);
    if (!batchAbortController.aborted) {
      ElMessage.success(
        `多线程批量生图完成！成功 ${batchProgress.success} 个，失败 ${batchProgress.failed} 个`
      );
    }
  } catch (err: any) {
    ElMessage.error(`批量生图过程异常: ${err.message || "未知错误"}`);
  } finally {
    batchRunning.value = false;
    await loadKeyframes();
    emit("changed");
  }
}

async function handleBatchGenerateCommand(command: string) {
  let targets: StoryKeyframeVO[] = [];
  if (command === "selected") {
    targets = tableSelectedRows.value.filter((k) => k.status !== "generating");
    if (!targets.length) {
      ElMessage.warning("请先勾选需要生成的关键帧");
      return;
    }
  } else if (command === "pending") {
    loading.value = true;
    try {
      const all = await collectPages((params) => keyframeApi.list(props.projectId, params));
      targets = all.filter((k) => k.status !== "done" && k.status !== "generating");
    } finally {
      loading.value = false;
    }
    if (!targets.length) {
      ElMessage.info("当前没有未完成（草稿/失败）的关键帧");
      return;
    }
  } else if (command === "all") {
    loading.value = true;
    try {
      const all = await collectPages((params) => keyframeApi.list(props.projectId, params));
      targets = all.filter((k) => k.status !== "generating");
    } finally {
      loading.value = false;
    }
    if (!targets.length) {
      ElMessage.info("当前没有可生成的关键帧");
      return;
    }
  }

  batchTargets.value = targets;
  batchDialogVisible.value = true;
}

function handleBatchGenerateClick() {
  if (tableSelectedRows.value.length > 0) {
    handleBatchGenerateCommand("selected");
  } else {
    handleBatchGenerateCommand("pending");
  }
}

async function confirmStartBatch() {
  batchDialogVisible.value = false;
  await runBatchGeneration(batchTargets.value, batchConcurrency.value);
}

async function handleStopAllGenerations() {
  try {
    await ElMessageBox.confirm(
      "确定中断本项目所有正在生成的关键帧图片任务吗？\n队列中尚未开始的任务也将被取消。",
      "中断全部生图",
      {
        confirmButtonText: "确定中断",
        cancelButtonText: "继续生成",
        type: "warning",
      }
    );
  } catch {
    return;
  }

  batchAbortController.aborted = true;
  batchStopping.value = true;
  try {
    const res = await keyframeApi.stopAll(props.projectId);
    const stoppedCount = res.data?.stopped_count ?? 0;
    for (const key of Object.keys(generatingImageMap)) {
      delete generatingImageMap[key];
    }
    for (const key of Object.keys(stoppingImageMap)) {
      delete stoppingImageMap[key];
    }
    ElMessage.warning(`已中断全部生图任务（共终止 ${stoppedCount} 个在途任务）`);
    await loadKeyframes();
    emit("changed");
  } catch (err: any) {
    ElMessage.error(`中断生图任务失败: ${err.message || "请求异常"}`);
  } finally {
    batchStopping.value = false;
    batchRunning.value = false;
  }
}

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

const ART_TYPE_LABEL: Record<string, string> = {
  character_sheet: "主视图+三视图",
  turnaround: "三视图",
  front_bust: "主视图",
  full_body: "全身",
  half_body: "半身",
  face: "面部特写",
  action: "动作",
  reference: "参考图",
  other: "其他",
};

function formatArtLabel(art: StoryCharacterArtVO): string {
  const typeLabel = ART_TYPE_LABEL[art.art_type] || "";
  if (art.name && typeLabel && art.name !== typeLabel) {
    return `${art.name}（${typeLabel}）`;
  }
  return art.name || typeLabel || "立绘";
}

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
    const arts: StoryCharacterArtVO[] = casting.arts ?? [];
    const defaultArt = arts.find((a) => a.art_type === "character_sheet") || arts[0];
    const initialArtId =
      hit !== undefined ? (hit.character_art_id ?? "") : (defaultArt?.id ?? "");
    options.push({
      character_id: casting.id,
      name: casting.name,
      checked: hit !== undefined,
      role: hit?.role ?? "main",
      character_prompt: hit?.character_prompt ?? "",
      arts,
      art_id: initialArtId,
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
    emit("changed");
  } finally {
    castSubmitting.value = false;
  }
}

// —— 导出选择 ——
const selectionVisible = ref(false);
const selectionSubmitting = ref(false);
const selectedIds = ref<string[]>([]);
const allKeyframesForSelection = ref<StoryKeyframeVO[]>([]);
const loadingSelection = ref(false);

async function openSelection() {
  selectionVisible.value = true;
  loadingSelection.value = true;
  try {
    const all = await collectPages((params) => keyframeApi.list(props.projectId, params));
    allKeyframesForSelection.value = all;
    selectedIds.value = all
      .filter((keyframe) => keyframe.is_selected)
      .sort((a, b) => a.selection_order - b.selection_order)
      .map((keyframe) => keyframe.id);
  } finally {
    loadingSelection.value = false;
  }
}

async function handleSelectionSubmit() {
  selectionSubmitting.value = true;
  try {
    await keyframeApi.setSelection(props.projectId, selectedIds.value);
    ElMessage.success("导出选择已保存");
    selectionVisible.value = false;
    await loadKeyframes();
    emit("changed");
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
      <div class="toolbar-left">
        <span class="panel-hint">关键帧是视频生成的视觉锚点；支持多线程并发批量生成图片（最多 5 线程）。</span>
      </div>
      <div class="toolbar-actions">
        <el-button
          v-if="hasGeneratingKeyframes"
          type="danger"
          plain
          :loading="batchStopping"
          @click="handleStopAllGenerations"
        >
          中断全部生成
        </el-button>
        <el-dropdown
          v-if="!batchRunning"
          split-button
          type="success"
          @click="handleBatchGenerateClick"
          @command="handleBatchGenerateCommand"
        >
          <el-icon class="el-icon--left"><Picture /></el-icon>
          {{ tableSelectedRows.length ? `批量生图 (${tableSelectedRows.length})` : "批量生成图片" }}
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="tableSelectedRows.length" command="selected">
                生成选中的 {{ tableSelectedRows.length }} 个关键帧
              </el-dropdown-item>
              <el-dropdown-item command="pending">
                生成全部未完成关键帧（草稿/失败）
              </el-dropdown-item>
              <el-dropdown-item command="all">
                重新生成项目全部关键帧
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-else type="warning" plain :loading="true">
          生图中 ({{ batchProgress.finished }}/{{ batchProgress.total }})
        </el-button>
        <el-button @click="openSelection">导出选择</el-button>
        <el-button type="primary" @click="openCreate">新建关键帧</el-button>
      </div>
    </div>

    <!-- 批量进度展示条 -->
    <div v-if="batchRunning" class="batch-progress-bar">
      <div class="batch-progress-info">
        <div class="batch-progress-title">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span class="batch-title-text">
            多线程批量生图中（最多 {{ batchConcurrency }} 线程并发）：已完成 {{ batchProgress.finished }} / {{ batchProgress.total }}
          </span>
          <span class="batch-sub-text">
            (进行中 {{ batchProgress.active }} | 成功 {{ batchProgress.success }} | 失败 {{ batchProgress.failed }})
          </span>
        </div>
        <el-button size="small" type="danger" plain :loading="batchStopping" @click="handleStopAllGenerations">
          中断批量生成
        </el-button>
      </div>
      <el-progress
        :percentage="batchProgress.total > 0 ? Math.round((batchProgress.finished / batchProgress.total) * 100) : 0"
        :status="batchProgress.failed > 0 ? 'warning' : 'success'"
        :stroke-width="6"
        class="batch-progress-slider"
      />
    </div>

    <input
      ref="imageInput"
      type="file"
      accept=".png,.jpg,.jpeg,.webp"
      style="display: none"
      @change="onImagePicked"
    />

    <el-table
      v-loading="loading"
      :data="list"
      stripe
      :row-class-name="tableRowClassName"
      @selection-change="onTableSelectionChange"
    >
      <el-table-column
        type="selection"
        width="46"
        :selectable="(row: StoryKeyframeVO) => row.status !== 'generating'"
      />
      <el-table-column label="场景-镜头" width="100">
        <template #default="{ row }">{{ numbering(row) }}</template>
      </el-table-column>
      <el-table-column label="参考图" width="110">
        <template #default="{ row }">
          <div v-if="row.status === 'generating'" class="kf-generating-box" title="正在生成图片，可点击中止">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span class="kf-generating-text">生图中</span>
            <el-button
              size="small"
              link
              type="danger"
              class="kf-generating-stop-btn"
              :loading="stoppingImageMap[row.id]"
              @click="handleStopGeneration(row)"
            >
              中断
            </el-button>
          </div>
          <el-image
            v-else-if="row.image_file"
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
            :disabled="row.status === 'generating'"
            @click="openImagePicker(row)"
          >
            {{ row.image_file ? "替换图" : "上传图片" }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="名称" prop="name" min-width="130">
        <template #default="{ row }">{{ row.name || "—" }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tooltip
            v-if="row.status === 'failed' && row.error_message"
            :content="row.error_message"
            placement="top"
            effect="dark"
          >
            <el-tag size="small" type="danger" class="failed-tag">
              失败
              <el-icon class="el-icon--right"><QuestionFilled /></el-icon>
            </el-tag>
          </el-tooltip>
          <el-tag
            v-else
            size="small"
            :type="
              row.status === 'done'
                ? 'success'
                : row.status === 'generating'
                ? 'warning'
                : row.status === 'failed'
                ? 'danger'
                : 'info'
            "
          >
            {{ STATUS_LABEL[row.status] ?? row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="正向提示词" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="prompt-brief" :title="row.prompt">
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
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'generating'"
            size="small"
            link
            type="danger"
            :loading="stoppingImageMap[row.id]"
            @click="handleStopGeneration(row)"
          >
            中断生成
          </el-button>
          <el-button
            v-else
            size="small"
            link
            type="primary"
            :loading="generatingImageMap[row.id]"
            @click="handleGenerateImage(row)"
          >
            {{ row.status === "failed" ? "重新生成" : "生成图片" }}
          </el-button>
          <el-button size="small" link @click="openCastDialog(row)">出场角色</el-button>
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有关键帧" :image-size="80" />
      </template>
    </el-table>

    <div v-if="total > 0" class="panel-pagination">
      <Pagination
        v-model:page="page"
        v-model:size="size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        @change="loadKeyframes"
      />
    </div>

    <!-- 创建/编辑 -->
    <el-dialog
      v-model="formVisible"
      :title="editing ? '编辑关键帧' : '新建关键帧'"
      width="720px"
      append-to-body
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
      append-to-body
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
              placeholder="参考立绘（默认主视图+三视图）"
              class="cast-art"
            >
              <el-option
                v-for="art in option.arts"
                :key="art.id"
                :label="formatArtLabel(art)"
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
    <el-dialog v-model="selectionVisible" title="设置导出选中关键帧" width="560px" append-to-body destroy-on-close>
      <span class="panel-hint">勾选参与导出的关键帧（空选即清空选择）。</span>
      <div v-loading="loadingSelection" style="min-height: 80px; max-height: 360px; overflow-y: auto;">
        <el-checkbox-group v-model="selectedIds" class="selection-group">
          <el-checkbox v-for="keyframe in allKeyframesForSelection" :key="keyframe.id" :value="keyframe.id">
            {{ numbering(keyframe) }} {{ keyframe.name || "未命名" }}
          </el-checkbox>
        </el-checkbox-group>
      </div>
      <template #footer>
        <el-button @click="selectionVisible = false">取消</el-button>
        <el-button type="primary" :loading="selectionSubmitting" @click="handleSelectionSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量多线程生图确认弹窗 -->
    <el-dialog
      v-model="batchDialogVisible"
      title="批量生成关键帧图片（多线程）"
      width="540px"
      append-to-body
      destroy-on-close
    >
      <div class="batch-dialog-content">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="系统将自动组装各关键帧提示词与绑定的出场角色立绘，按设定的线程并发数进行后台多线程异步生成。"
          style="margin-bottom: 16px;"
        />
        <el-form label-width="110px">
          <el-form-item label="待生成关键帧">
            <span class="batch-dialog-count">{{ batchTargets.length }} 个关键帧</span>
            <div v-if="batchNoCharCount > 0" class="muted" style="margin-top: 4px; font-size: 12px; line-height: 1.4;">
              提示：其中 {{ batchNoCharCount }} 个关键帧尚未设置出场角色，将直接按正向提示词出图。
            </div>
          </el-form-item>
          <el-form-item label="并发线程数">
            <el-select v-model="batchConcurrency" style="width: 240px;">
              <el-option :value="5" label="5 线程 (推荐，最快)" />
              <el-option :value="4" label="4 线程" />
              <el-option :value="3" label="3 线程" />
              <el-option :value="2" label="2 线程" />
              <el-option :value="1" label="1 线程 (单任务串行)" />
            </el-select>
            <div class="form-item-tip">最多支持 5 个线程并发生成，各线程独立向模型出图。</div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="batchDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchRunning" @click="confirmStartBatch">
          开始多线程生成
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
.panel-pagination {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
.kf-generating-box {
  width: 56px;
  height: 56px;
  border-radius: 4px;
  border: 1px dashed #3b82f6;
  background: #eff6ff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #3b82f6;
  margin-bottom: 4px;
}
.kf-generating-text {
  font-size: 10px;
}
.kf-generating-stop-btn {
  font-size: 11px !important;
  padding: 0 !important;
  height: auto !important;
  line-height: 1 !important;
  margin-top: 2px;
}
.failed-tag {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}
:deep(.focused-keyframe-row) {
  --el-table-tr-bg-color: #f0fdf4 !important;
  animation: pulse-focus 2s ease-in-out infinite alternate;
}
@keyframes pulse-focus {
  from {
    background-color: #f0fdf4;
  }
  to {
    background-color: #e0f2fe;
  }
}
.batch-progress-bar {
  margin-bottom: 12px;
  padding: 10px 14px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 6px;
}
.batch-progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.batch-progress-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #166534;
  font-weight: 500;
  flex-wrap: wrap;
}
.batch-title-text {
  font-weight: 600;
}
.batch-sub-text {
  font-size: 12px;
  color: #15803d;
  font-weight: normal;
}
.batch-progress-slider {
  margin-top: 8px;
}
.batch-dialog-count {
  font-weight: 600;
  color: #1f2937;
}
.form-item-tip {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 4px;
  line-height: 1.4;
}
</style>
