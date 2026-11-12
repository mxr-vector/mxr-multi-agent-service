<script setup lang="ts">
/**
 * 生成视频面板：按章节把剧本正文与全部关键帧组合成一份生成单元。
 *
 * 服务端把章节内每个关键帧放到剧本对应标记位置（前端内嵌展示），并合成一份
 * 整章提示词。用户确认/编辑后「生成本章片段」，一次提交该章全部关键帧参考图，
 * 产出单个视频片段；完成后可下载，由用户外部组装整片。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Loading } from "@element-plus/icons-vue";
import { useDictStore } from "@/stores/dictStore";
import { getToken } from "@/utils/auth";
import {
  STORY_VIDEO_URL,
  collectPages,
  storyFileUrl,
  videoApi,
  type StoryVideoChainStatus,
  type StoryVideoPlan,
  type StoryVideoPlanChapter,
  type StoryVideoVO,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const route = useRoute();
const router = useRouter();
const dictStore = useDictStore();
dictStore.ensureLoaded();

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  queued: "排队中",
  generating: "生成中",
  done: "已完成",
  failed: "失败",
  cancelled: "已中止",
};
const STATUS_TAG: Record<string, "info" | "warning" | "success" | "danger"> = {
  draft: "info",
  queued: "info",
  generating: "warning",
  done: "success",
  failed: "danger",
  cancelled: "info",
};

const resolutionOptions = computed(() => dictStore.getOptions("video_resolution"));
const ratioOptions = computed(() => dictStore.getOptions("video_ratio"));

const loading = ref(false);
const plan = ref<StoryVideoPlan | null>(null);
const videos = ref<StoryVideoVO[]>([]);

// 用户编辑稿：按章节保存整章提示词与片段标题，刷新编排时保留
const promptDrafts = reactive<Record<string, string>>({});
const titleDrafts = reactive<Record<string, string>>({});
const generatingChapter = reactive<Record<string, boolean>>({});
const stoppingVideo = reactive<Record<string, boolean>>({});
// 剧本预览默认展示；提示词编辑默认收起，按需展开
const promptExpanded = reactive<Record<string, boolean>>({});

// —— 生成规格（缺省取模型管理 video 角色 extra，改配置后下次打开生效） ——
const resolution = ref("480P");
const ratio = ref("adaptive");
const duration = ref(5);
const useImages = ref(true);
// 单章生成时自动衔接上一集已完成片段尾帧（默认关闭：优先按本章关键帧参考图生成）
const chainFromPrev = ref(false);

function confirmChainFromPrev(): Promise<boolean> | boolean {
  // 仅开启时提示；关闭直接生效
  if (chainFromPrev.value) return true;
  return ElMessageBox.confirm(
    "开启后，本章片段将优先取上一集已完成片段的尾帧作为首帧，保证集间画面衔接。\n" +
      "若当前视频接口不支持「首帧 + 参考图」同时下发，提交时优先只带上一集尾帧，" +
      "关键帧参考图仅在尾帧入参被拒时兜底，人物形象可能以上一集成片为准。\n\n确定开启吗？",
    "开启单章衔接上一集尾帧",
    { confirmButtonText: "开启衔接", cancelButtonText: "取消", type: "warning" }
  )
    .then(() => true)
    .catch(() => false);
}
const modelName = ref("");
const maxConcurrent = ref(3);

async function loadVideoConfig() {
  try {
    const res = await videoApi.generationOptions();
    const options = res.data;
    if (!options) return;
    if (options.resolution) resolution.value = options.resolution;
    if (options.ratio) ratio.value = options.ratio;
    if (options.duration >= 2 && options.duration <= 30) {
      duration.value = options.duration;
    }
    modelName.value = options.model;
    maxConcurrent.value = options.max_concurrent;
  } catch {
    // 配置接口不可用时沿用默认规格，生成时由后端兜底
  }
}

const chapters = computed<StoryVideoPlanChapter[]>(() => plan.value?.chapters ?? []);

function chapterKey(chapter: StoryVideoPlanChapter): string {
  // 未匹配章节与无剧本兜底章节统一使用 episode_no=0
  return String(chapter.chapter_no ?? 0);
}

function chapterTitle(chapter: StoryVideoPlanChapter): string {
  if (chapter.chapter_no == null) return chapter.title;
  const prefix = `第${chapter.chapter_no}集`;
  if (
    chapter.title.startsWith(prefix) ||
    chapter.title.startsWith(`第${chapter.chapter_no}章`)
  ) {
    return chapter.title;
  }
  return `${prefix} · ${chapter.title}`;
}

function chapterImageCount(chapter: StoryVideoPlanChapter): number {
  return chapter.shots.filter((shot) => shot.has_image).length;
}

const latestByEpisode = computed<Record<string, StoryVideoVO>>(() => {
  const map: Record<string, StoryVideoVO> = {};
  for (const video of videos.value) {
    const key = String(video.episode_no ?? 0);
    const current = map[key];
    if (!current || video.created_at > current.created_at) {
      map[key] = video;
    }
  }
  return map;
});

const latestDoneByEpisode = computed<Record<string, StoryVideoVO>>(() => {
  const map: Record<string, StoryVideoVO> = {};
  for (const video of videos.value) {
    if (video.status !== "done" || !video.video_file) continue;
    const key = String(video.episode_no ?? 0);
    const current = map[key];
    if (!current || video.created_at > current.created_at) {
      map[key] = video;
    }
  }
  return map;
});

const activeVideos = computed(() =>
  videos.value.filter(
    (video) => video.status === "queued" || video.status === "generating"
  )
);
const chainState = ref<StoryVideoChainStatus | null>(null);
const chainRunning = computed(() => chainState.value?.running ?? false);
const isBusy = computed(
  () => chainRunning.value || activeVideos.value.length > 0
);
const showChainProgress = computed(() => {
  const state = chainState.value;
  return !!state && state.running && state.total > 0;
});
const chainPercentage = computed(() => {
  const state = chainState.value;
  if (!state || !state.total) return 0;
  return Math.min(100, Math.round(((state.finished ?? 0) / state.total) * 100));
});

function latestChapterVideo(chapter: StoryVideoPlanChapter): StoryVideoVO | undefined {
  return latestByEpisode.value[chapterKey(chapter)];
}

function latestDoneChapterVideo(
  chapter: StoryVideoPlanChapter
): StoryVideoVO | undefined {
  return latestDoneByEpisode.value[chapterKey(chapter)];
}

function previousDoneEpisode(chapter: StoryVideoPlanChapter): number | null {
  if (chapter.chapter_no == null || chapter.chapter_no <= 1) return null;
  const candidates = Object.keys(latestDoneByEpisode.value)
    .map((key) => Number(key))
    .filter((episode) => episode > 0 && episode < chapter.chapter_no!)
    .sort((a, b) => b - a);
  return candidates.length ? candidates[0] : null;
}

function previousDoneVideo(
  chapter: StoryVideoPlanChapter
): StoryVideoVO | undefined {
  const prev = previousDoneEpisode(chapter);
  return prev == null ? undefined : latestDoneByEpisode.value[String(prev)];
}

function willLinkChapter(chapter: StoryVideoPlanChapter): boolean {
  return (
    !chainRunning.value &&
    chainFromPrev.value &&
    useImages.value &&
    !!previousDoneVideo(chapter)
  );
}

function isActive(video?: StoryVideoVO): boolean {
  return Boolean(video && (video.status === "queued" || video.status === "generating"));
}

function applyPlan(data: StoryVideoPlan | null) {
  plan.value = data;
  if (!data) return;
  for (const chapter of data.chapters) {
    const key = chapterKey(chapter);
    // 只初始化一次，刷新编排时保留用户已编辑稿
    if (promptDrafts[key] === undefined) promptDrafts[key] = chapter.prompt;
    if (titleDrafts[key] === undefined) titleDrafts[key] = chapterTitle(chapter);
  }
}

async function loadPlan() {
  const res = await videoApi.plan(props.projectId);
  applyPlan(res.data);
}

async function loadVideos() {
  videos.value = await collectPages((params) =>
    videoApi.list(props.projectId, { ...params, source: "generated", brief: true })
  );
}

async function loadChainStatus() {
  try {
    const res = await videoApi.chainStatus(props.projectId);
    chainState.value = res.data ?? null;
  } catch {
    // 链状态不可用时不影响视频列表轮询
  }
}

async function loadAll() {
  loading.value = true;
  try {
    await Promise.all([
      loadVideoConfig(),
      loadPlan(),
      loadVideos(),
      loadChainStatus(),
    ]);
    syncPolling();
  } finally {
    loading.value = false;
  }
}

async function refreshPlan() {
  loading.value = true;
  try {
    await loadPlan();
    ElMessage.success("编排已刷新，已保留手动修改的提示词");
  } finally {
    loading.value = false;
  }
}

onMounted(() => loadAll());
onUnmounted(stopPolling);

// —— 轮询：项目级轻量批量刷新视频状态 ——
let pollTimer: ReturnType<typeof setInterval> | null = null;
// 已完成提示按 chain_id 去重，避免并发轮询重复弹窗
let notifiedChainId: string | null = null;

function syncPolling() {
  if (activeVideos.value.length > 0 || chainRunning.value) {
    if (!pollTimer) {
      pollTimer = setInterval(refreshVideos, 3000);
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

async function refreshVideos() {
  const previous = new Map(videos.value.map((video) => [video.id, video.status]));
  const hadActive = activeVideos.value.length > 0;
  const hadChain = chainRunning.value;
  try {
    await loadVideos();
    await loadChainStatus();
    for (const video of videos.value) {
      const before = previous.get(video.id);
      if (before && before !== "failed" && video.status === "failed") {
        ElMessage.error(
          `章节「${video.title || "未命名"}」片段生成失败${video.error_message ? "：" + video.error_message : ""}`
        );
      }
    }
    if (hadChain && !chainRunning.value && chainState.value) {
      const state = chainState.value;
      if (state.chain_id && state.chain_id !== notifiedChainId) {
        notifiedChainId = state.chain_id;
        const message =
          `串行生成已结束：成功 ${state.success ?? 0} 个，` +
          `失败 ${state.failed ?? 0} 个，取消 ${state.cancelled ?? 0} 个`;
        if ((state.failed ?? 0) > 0 || (state.cancelled ?? 0) > 0) {
          ElMessage.warning(message);
        } else {
          ElMessage.success(message);
        }
        emit("changed");
      }
    } else if (!hadChain && hadActive && activeVideos.value.length === 0) {
      ElMessage.success("视频生成任务已全部结束");
      emit("changed");
    }
    syncPolling();
  } catch {
    stopPolling();
  }
}

// —— 生成 ——
function specPayload() {
  return {
    use_images: useImages.value,
    resolution: resolution.value || undefined,
    ratio: ratio.value || undefined,
    duration: duration.value || undefined,
  };
}

function resetPrompt(chapter: StoryVideoPlanChapter) {
  promptDrafts[chapterKey(chapter)] = chapter.prompt;
}

function togglePrompt(chapter: StoryVideoPlanChapter) {
  const key = chapterKey(chapter);
  promptExpanded[key] = !promptExpanded[key];
}

async function generateChapter(chapter: StoryVideoPlanChapter) {
  const key = chapterKey(chapter);
  if (isActive(latestChapterVideo(chapter))) {
    ElMessage.info("本章片段正在生成中，请稍候");
    return;
  }
  const ids = useImages.value
    ? chapter.keyframe_ids
    : chapter.shots.map((shot) => shot.keyframe_id);
  if (!ids.length) {
    ElMessage.warning(
      useImages.value ? "本章没有已出图的关键帧" : "本章没有可用的关键帧"
    );
    return;
  }
  const prompt = (promptDrafts[key] ?? chapter.prompt ?? "").trim();
  if (!prompt) {
    ElMessage.warning("整章视频提示词为空，请补充后再生成");
    return;
  }
  const linkEpisode = previousDoneEpisode(chapter);
  const linkHint =
    willLinkChapter(chapter) && linkEpisode != null
      ? `\n\n将自动取第${linkEpisode}集成片尾帧作为首帧，保证与第${linkEpisode}集画面衔接；` +
        "若上游不支持首帧与参考图同时下发，将优先使用尾帧。"
      : "";
  try {
    await ElMessageBox.confirm(
      (useImages.value
        ? `将把本章 ${ids.length} 张关键帧作为参考图，一次性生成 1 个章节片段。\n` +
          "生成完成后可下载片段，自行在外部剪辑组装。"
        : "将以整章提示词进行文生视频，一次性生成 1 个章节片段。\n生成完成后可下载片段，自行在外部剪辑组装。") +
        linkHint,
      "生成本章片段",
      { confirmButtonText: "开始生成", cancelButtonText: "取消", type: "info" }
    );
  } catch {
    return;
  }
  generatingChapter[key] = true;
  try {
    await videoApi.generate(props.projectId, {
      chapter_no: chapter.chapter_no,
      title: (titleDrafts[key] || chapterTitle(chapter)).trim(),
      prompt,
      keyframe_ids: ids,
      chapter_content: chapter.content || null,
      link_previous: chainFromPrev.value && useImages.value,
      ...specPayload(),
    });
    ElMessage.success(`已提交章节「${chapterTitle(chapter)}」片段生成`);
    await loadVideos();
    syncPolling();
    emit("changed");
  } catch {
    // 错误拦截器统一提示
  } finally {
    generatingChapter[key] = false;
  }
}

// —— 串行链：按集顺序逐章生成，上一章成片尾帧作为下一章首帧 ——
const chainDialogVisible = ref(false);
const chainSubmitting = ref(false);
const chainSelectedKeys = ref<string[]>([]);

const chainCandidates = computed(() =>
  chapters.value.filter((chapter) => chapter.keyframe_ids.length > 0)
);

function openChainDialog() {
  if (!useImages.value) {
    ElMessage.warning("串行衔接需要关键帧图片，请先开启「关键帧作参考图」");
    return;
  }
  if (!chainCandidates.value.length) {
    ElMessage.warning("当前没有已出图的关键帧章节，无法串行生成");
    return;
  }
  chainSelectedKeys.value = chainCandidates.value.map((chapter) =>
    chapterKey(chapter)
  );
  chainDialogVisible.value = true;
}

function toggleChainAll(checked: boolean) {
  chainSelectedKeys.value = checked
    ? chainCandidates.value.map((chapter) => chapterKey(chapter))
    : [];
}

async function submitChain() {
  const selected = chainCandidates.value.filter((chapter) =>
    chainSelectedKeys.value.includes(chapterKey(chapter))
  );
  if (!selected.length) {
    ElMessage.warning("请至少勾选一个章节");
    return;
  }
  const empty = selected.find(
    (chapter) => !(promptDrafts[chapterKey(chapter)] ?? chapter.prompt ?? "").trim()
  );
  if (empty) {
    ElMessage.warning(`「${chapterTitle(empty)}」的整章提示词为空，请先补充`);
    return;
  }
  chainSubmitting.value = true;
  notifiedChainId = null;
  try {
    await videoApi.generateChain(props.projectId, {
      chapters: selected.map((chapter) => ({
        chapter_no: chapter.chapter_no,
        title: (titleDrafts[chapterKey(chapter)] || chapterTitle(chapter)).trim(),
        prompt: (promptDrafts[chapterKey(chapter)] ?? chapter.prompt).trim(),
        keyframe_ids: chapter.keyframe_ids,
        chapter_content: chapter.content || null,
      })),
      use_images: true,
      resolution: resolution.value || undefined,
      ratio: ratio.value || undefined,
      duration: duration.value || undefined,
    });
    ElMessage.success(`已提交 ${selected.length} 个章节的串行生成`);
    chainDialogVisible.value = false;
    await loadVideos();
    await loadChainStatus();
    syncPolling();
    emit("changed");
  } catch {
    // 错误拦截器统一提示
  } finally {
    chainSubmitting.value = false;
  }
}

async function handleStop(video?: StoryVideoVO) {
  if (!video) return;
  try {
    await ElMessageBox.confirm(
      `确定中止片段「${video.title || "未命名"}」的生成吗？\n若该片段属于串行链，将同时终止整条链及其后续章节。`,
      "中止生成",
      { confirmButtonText: "确定中止", cancelButtonText: "继续生成", type: "warning" }
    );
  } catch {
    return;
  }
  stoppingVideo[video.id] = true;
  try {
    await videoApi.stop(video.id);
    ElMessage.warning("已中止视频生成任务");
    await loadVideos();
    syncPolling();
  } catch {
    // 错误拦截器统一提示
  } finally {
    stoppingVideo[video.id] = false;
  }
}

async function handleStopAll() {
  try {
    await ElMessageBox.confirm(
      "确定中止本项目所有在途视频生成任务吗？排队中的任务、串行链及其后续章节也会被取消。",
      "中止全部视频任务",
      { confirmButtonText: "确定中止", cancelButtonText: "继续生成", type: "warning" }
    );
  } catch {
    return;
  }
  try {
    const res = await videoApi.stopAll(props.projectId);
    ElMessage.warning(`已中止全部视频任务（共 ${res.data?.stopped_count ?? 0} 个）`);
    await loadVideos();
    syncPolling();
  } catch {
    // 错误拦截器统一提示
  }
}

// —— 下载 / 播放 / 删除 ——
function safeFilename(name: string): string {
  return name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "视频片段";
}

function handleDownload(video?: StoryVideoVO) {
  if (!video?.video_file) {
    ElMessage.info("该片段尚未生成完成");
    return;
  }
  const token = getToken();
  const base = import.meta.env.VITE_APP_BASE_API || "";
  const dot = video.video_file.lastIndexOf(".");
  const suffix = dot !== -1 ? video.video_file.slice(dot) : ".mp4";
  const filename = `${safeFilename(video.title || "视频片段")}${suffix}`;
  const url = `${base}${STORY_VIDEO_URL.download(video.id)}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  setTimeout(() => document.body.removeChild(link), 2000);
  ElMessage.success("片段下载已开始");
}

const playVisible = ref(false);
const playing = ref<StoryVideoVO | null>(null);

function openPlay(video?: StoryVideoVO) {
  if (!video?.video_file) {
    ElMessage.info("该片段尚未生成完成");
    return;
  }
  playing.value = video;
  playVisible.value = true;
}

async function handleDelete(video?: StoryVideoVO) {
  if (!video) return;
  const confirmed = await confirmDanger(
    chainRunning.value
      ? `确定删除片段「${video.title || "未命名"}」吗？当前存在串行链任务，删除链内片段会终止整条链及其后续章节。`
      : `确定删除片段「${video.title || "未命名"}」吗？`
  );
  if (!confirmed) return;
  try {
    await videoApi.remove(video.id);
    ElMessage.success("片段已删除");
    await loadVideos();
    emit("changed");
  } catch {
    // 错误拦截器统一提示
  }
}

function formatDuration(ms: number | null): string {
  return ms ? `${(ms / 1000).toFixed(1)}s` : "—";
}

function goExport() {
  router.push({ path: route.path, query: { ...route.query, tab: "export" } });
}
</script>

<template>
  <div class="video-gen-panel">
    <!-- 全局设置 -->
    <div class="gen-card">
      <div class="gen-head">
        <div>
          <div class="gen-title">按章节生成视频片段</div>
          <div class="gen-desc">
            系统已把本章剧本和全部关键帧按位置组合成一份生成单元；确认或修改整章提示词后点击一次，
            即可提交该章全部关键帧生成 1 个视频片段。完成后可下载片段，自行在外部剪辑组装。
          </div>
        </div>
        <div class="gen-actions">
          <el-tag v-if="modelName" size="small" type="info">{{ modelName }}</el-tag>
          <el-button
            type="primary"
            plain
            size="small"
            :disabled="!useImages || isBusy"
            @click="openChainDialog"
          >
            串行生成章节
          </el-button>
          <el-button text type="primary" :loading="loading" :disabled="chainRunning" @click="refreshPlan">刷新编排</el-button>
          <el-button text type="primary" @click="goExport">导出素材（外部生成）</el-button>
          <el-button v-if="isBusy" type="danger" plain size="small" @click="handleStopAll">
            中止全部任务
          </el-button>
        </div>
      </div>
      <div class="gen-settings">
        <el-select v-model="resolution" class="setting-select" placeholder="分辨率">
          <el-option
            v-for="option in resolutionOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
          <el-option v-if="!resolutionOptions.length" label="480P" value="480P" />
        </el-select>
        <el-select v-model="ratio" class="setting-select" placeholder="画幅">
          <el-option
            v-for="option in ratioOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
          <el-option v-if="!ratioOptions.length" label="自适应" value="adaptive" />
        </el-select>
        <el-input-number
          v-model="duration"
          :min="2"
          :max="30"
          controls-position="right"
          class="setting-duration"
        />
        <el-switch v-model="useImages" active-text="关键帧作参考图" />
        <el-switch
          v-model="chainFromPrev"
          :before-change="confirmChainFromPrev"
          :disabled="!useImages || chainRunning"
          active-text="单章衔接上一集尾帧"
        />
        <span class="gen-hint">单章任务最多 {{ maxConcurrent }} 个并行；串行链逐章执行</span>
      </div>
    </div>

    <!-- 串行链进度 -->
    <div v-if="showChainProgress" class="chain-progress-bar">
      <div class="chain-progress-info">
        <div class="chain-progress-title">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>
            串行生成中：已完成 {{ chainState?.finished ?? 0 }} / {{ chainState?.total ?? 0 }}
            <template v-if="chainState?.current_chapter_no != null">
              · 当前第 {{ chainState.current_chapter_no }} 集
            </template>
          </span>
          <span class="chain-sub-text">
            (成功 {{ chainState?.success ?? 0 }} | 失败 {{ chainState?.failed ?? 0 }} | 取消
            {{ chainState?.cancelled ?? 0 }})
          </span>
        </div>
        <el-button size="small" type="danger" plain @click="handleStopAll">
          中止整链
        </el-button>
      </div>
      <el-progress :percentage="chainPercentage" :stroke-width="6" class="chain-progress-slider" />
    </div>

    <!-- 章节生成单元 -->
    <div v-loading="loading" class="plan-wrap">
      <template v-if="chapters.length">
        <section
          v-for="chapter in chapters"
          :key="chapterKey(chapter)"
          class="chapter-card"
        >
          <header class="chapter-head">
            <div class="chapter-heading">
              <span class="chapter-title">{{ chapterTitle(chapter) }}</span>
              <span class="chapter-meta">
                {{ chapter.shots.length }} 个镜头 ·
                {{ chapterImageCount(chapter) }} 张图
              </span>
              <el-tag
                v-if="latestChapterVideo(chapter)"
                :type="STATUS_TAG[latestChapterVideo(chapter)?.status || ''] || 'info'"
                size="small"
                class="chapter-status"
              >
                {{ STATUS_LABEL[latestChapterVideo(chapter)?.status || ''] || latestChapterVideo(chapter)?.status }}
              </el-tag>
              <el-tag
                v-if="willLinkChapter(chapter)"
                size="small"
                type="success"
                effect="plain"
                class="chapter-status"
              >
                衔接第{{ previousDoneEpisode(chapter) }}集尾帧
              </el-tag>
              <span v-if="latestChapterVideo(chapter)?.duration_ms" class="chapter-meta">
                {{ formatDuration(latestChapterVideo(chapter)?.duration_ms ?? null) }}
              </span>
              <span v-if="useImages && !chapter.keyframe_ids.length" class="chapter-warning">
                本章暂无已出图关键帧
              </span>
            </div>
            <div class="chapter-actions">
              <el-button
                type="primary"
                size="small"
                :loading="generatingChapter[chapterKey(chapter)]"
                :disabled="
                  chainRunning ||
                  isActive(latestChapterVideo(chapter)) ||
                  (!useImages && !chapter.shots.length) ||
                  (useImages && !chapter.keyframe_ids.length)
                "
                @click="generateChapter(chapter)"
              >
                {{ latestChapterVideo(chapter) ? "重新生成本章" : "生成本章片段" }}
              </el-button>
              <el-button
                v-if="isActive(latestChapterVideo(chapter))"
                size="small"
                type="danger"
                plain
                :loading="stoppingVideo[latestChapterVideo(chapter)?.id || '']"
                @click="handleStop(latestChapterVideo(chapter))"
              >
                停止
              </el-button>
              <el-button
                v-if="latestDoneChapterVideo(chapter)"
                size="small"
                link
                @click="openPlay(latestDoneChapterVideo(chapter))"
              >
                播放
              </el-button>
              <el-button
                v-if="latestDoneChapterVideo(chapter)"
                size="small"
                link
                type="success"
                @click="handleDownload(latestDoneChapterVideo(chapter))"
              >
                下载片段
              </el-button>
              <el-button
                v-if="latestChapterVideo(chapter) && !isActive(latestChapterVideo(chapter))"
                size="small"
                link
                type="danger"
                @click="handleDelete(latestChapterVideo(chapter))"
              >
                删除
              </el-button>
            </div>
          </header>

          <!-- 章节剧本预览：关键帧图片落在对应剧本位置 -->
          <div v-if="chapter.blocks.length" class="chapter-script">
            <template v-for="(block, blockIndex) in chapter.blocks" :key="blockIndex">
              <div v-if="block.type === 'text'" class="script-text">{{ block.text }}</div>
              <figure v-else class="script-image">
                <el-image
                  v-if="block.image_file"
                  :src="storyFileUrl(block.image_file)"
                  :preview-src-list="[storyFileUrl(block.image_file)]"
                  fit="cover"
                  preview-teleported
                  class="script-image-el"
                />
                <div v-else class="script-image-placeholder">未出图</div>
                <figcaption>{{ block.label }}</figcaption>
              </figure>
            </template>
          </div>

          <div class="chapter-prompt">
            <div class="chapter-prompt-head">
              <span>
                {{
                  chapter.keyframe_ids.length
                    ? "整章视频提示词（图1…图N 已按剧本位置嵌入，可编辑）"
                    : "整章视频提示词（可编辑）"
                }}
              </span>
              <div class="chapter-prompt-actions">
                <el-button size="small" link type="primary" @click="togglePrompt(chapter)">
                  {{ promptExpanded[chapterKey(chapter)] ? "收起提示词" : "编辑提示词" }}
                </el-button>
              </div>
            </div>
            <div v-show="promptExpanded[chapterKey(chapter)]" class="chapter-prompt-body">
              <div class="chapter-prompt-toolbar">
                <el-input
                  v-model="titleDrafts[chapterKey(chapter)]"
                  size="small"
                  class="chapter-title-input"
                  placeholder="片段标题"
                />
                <el-button size="small" link @click="resetPrompt(chapter)">
                  恢复自动提示词
                </el-button>
              </div>
              <el-input
                v-model="promptDrafts[chapterKey(chapter)]"
                type="textarea"
                :autosize="{ minRows: 4 }"
                placeholder="整章视频提示词"
              />
            </div>
            <div v-if="latestChapterVideo(chapter)?.error_message" class="chapter-error">
              {{ latestChapterVideo(chapter)?.error_message }}
            </div>
          </div>
        </section>
      </template>

      <el-empty
        v-else-if="!loading"
        description="还没有可编排的剧本或关键帧，请先生成剧本分镜与关键帧"
        :image-size="90"
      />
    </div>

    <!-- 串行生成确认 -->
    <el-dialog
      v-model="chainDialogVisible"
      title="串行生成章节视频"
      width="640px"
      append-to-body
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="按集顺序逐章串行生成：下一章首帧取上一章成片尾帧，保证集间画面连续；任一章失败或中止将终止整链，后续章节标记为已取消。"
        style="margin-bottom: 12px"
      />
      <div class="chain-dialog-toolbar">
        <span class="muted">
          已选 {{ chainSelectedKeys.length }} / {{ chainCandidates.length }} 集
        </span>
        <div>
          <el-button size="small" link type="primary" @click="toggleChainAll(true)">全选</el-button>
          <el-button size="small" link @click="toggleChainAll(false)">清空</el-button>
        </div>
      </div>
      <el-checkbox-group v-model="chainSelectedKeys" class="chain-chapter-list">
        <el-checkbox
          v-for="chapter in chainCandidates"
          :key="chapterKey(chapter)"
          :value="chapterKey(chapter)"
        >
          <span class="chain-chapter-title">{{ chapterTitle(chapter) }}</span>
          <span class="muted">
            {{ chapter.shots.length }} 个镜头 · {{ chapterImageCount(chapter) }} 张图
          </span>
        </el-checkbox>
      </el-checkbox-group>
      <div class="chain-dialog-hint muted">
        规格沿用面板顶部：{{ resolution }} · {{ ratio }} · {{ duration }}s，可先调整再提交。
      </div>
      <template #footer>
        <el-button @click="chainDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="chainSubmitting" @click="submitChain">
          开始串行生成
        </el-button>
      </template>
    </el-dialog>

    <!-- 播放 -->
    <el-dialog
      v-model="playVisible"
      :title="playing?.title || '视频预览'"
      width="720px"
      append-to-body
      destroy-on-close
    >
      <video
        v-if="playing?.video_file"
        :src="storyFileUrl(playing.video_file)"
        controls
        autoplay
        class="player"
      />
    </el-dialog>
  </div>
</template>

<style scoped>
.gen-card {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  padding: 12px 14px;
  background: #fafbfd;
  margin-bottom: 14px;
}
.gen-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.gen-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.gen-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #7d879a;
  line-height: 1.5;
}
.gen-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.gen-settings {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.setting-select {
  width: 130px;
}
.setting-duration {
  width: 110px;
}
.gen-hint {
  font-size: 12px;
  color: #9aa4b2;
}
.muted {
  color: #9aa4b2;
}
.chain-progress-bar {
  margin-bottom: 14px;
  padding: 10px 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
}
.chain-progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.chain-progress-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #1e40af;
  font-weight: 500;
  flex-wrap: wrap;
}
.chain-sub-text {
  font-size: 12px;
  color: #2563eb;
  font-weight: normal;
}
.chain-progress-slider {
  margin-top: 8px;
}
.chain-dialog-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.chain-chapter-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.chain-chapter-title {
  margin-right: 8px;
}
.chain-dialog-hint {
  margin-top: 10px;
  font-size: 12px;
}
.plan-wrap {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chapter-card {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  padding: 12px 14px;
}
.chapter-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.chapter-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.chapter-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.chapter-meta {
  font-size: 12px;
  color: #7d879a;
}
.chapter-status {
  margin-left: 2px;
}
.chapter-warning {
  font-size: 12px;
  color: #d98c00;
}
.chapter-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.chapter-script {
  margin-top: 10px;
  max-height: 440px;
  overflow: auto;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f7f9fc;
  font-size: 12px;
  line-height: 1.7;
  color: #5f6b7c;
}
.script-text {
  white-space: pre-wrap;
}
.script-image {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0;
  padding: 6px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #eef1f7;
}
.script-image-el {
  width: 160px;
  height: 90px;
  flex: none;
  border-radius: 6px;
  display: block;
}
.script-image-placeholder {
  width: 160px;
  height: 90px;
  flex: none;
  border-radius: 6px;
  background: #10131a;
  color: #8b93a5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.script-image figcaption {
  font-size: 12px;
  color: #7d879a;
}
.chapter-prompt {
  margin-top: 10px;
}
.chapter-prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
  color: #7d879a;
}
.chapter-prompt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chapter-prompt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.chapter-title-input {
  width: 200px;
}
.chapter-error {
  margin-top: 4px;
  font-size: 12px;
  color: #d9534f;
}
.player {
  width: 100%;
  max-height: 420px;
  background: #000;
}
</style>
