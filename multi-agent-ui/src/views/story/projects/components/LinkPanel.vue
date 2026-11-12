<script setup lang="ts">
/**
 * 关联集面板：按集展示已生成片段，并为相邻两集生成首尾帧衔接片段。
 *
 * 生成阶段各集独立并发生成，集间画面可能出现跳变；本面板抽取上一集成片
 * 尾帧作首帧、下一集成片首帧作尾帧，生成一段过渡片段，下载后插入两集之间。
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getToken } from "@/utils/auth";
import { useDictStore } from "@/stores/dictStore";
import {
  STORY_VIDEO_URL,
  storyFileUrl,
  videoApi,
  type StoryVideoLinkVO,
  type StoryVideoVO,
} from "@/api/story";
import { confirmDanger } from "@/utils/confirm";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

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

const DEFAULT_LINK_PROMPT =
  "集间过渡片段：从上一集的结尾画面开始，自然过渡到下一集的开始画面，" +
  "保持人物、服装、场景、光线与镜头方向一致，画面连贯，避免跳切。";

const resolutionOptions = computed(() => dictStore.getOptions("video_resolution"));
const ratioOptions = computed(() => dictStore.getOptions("video_ratio"));

const loading = ref(false);
const episodes = ref<StoryVideoVO[]>([]);
const links = ref<StoryVideoLinkVO[]>([]);

const modelName = ref("");
const resolution = ref("480P");
const ratio = ref("adaptive");
const duration = ref(5);
const supportsLastFrame = ref(true);

type EpisodeFlow = { type: "episode"; episode: StoryVideoVO };
type LinkFlow = {
  type: "link";
  from: StoryVideoVO;
  to: StoryVideoVO;
  link: StoryVideoLinkVO | null;
};
type FlowItem = EpisodeFlow | LinkFlow;

function linkPairKey(link: StoryVideoLinkVO): string {
  if (link.from_episode_no != null && link.to_episode_no != null) {
    return `ep-${link.from_episode_no}-${link.to_episode_no}`;
  }
  return `${link.from_video_id}:${link.to_video_id}`;
}

const latestLinks = computed(() => {
  const map = new Map<string, StoryVideoLinkVO>();
  for (const link of links.value) {
    const key = linkPairKey(link);
    const current = map.get(key);
    if (!current || link.created_at > current.created_at) map.set(key, link);
  }
  return map;
});

const flow = computed<FlowItem[]>(() => {
  const items: FlowItem[] = [];
  episodes.value.forEach((episode, index) => {
    items.push({ type: "episode", episode });
    const next = episodes.value[index + 1];
    if (!next) return;
    const pairKey =
      episode.episode_no != null && next.episode_no != null
        ? `ep-${episode.episode_no}-${next.episode_no}`
        : `${episode.id}:${next.id}`;
    items.push({
      type: "link",
      from: episode,
      to: next,
      link: latestLinks.value.get(pairKey) ?? null,
    });
  });
  return items;
});

const activeLinks = computed(() =>
  links.value.filter(
    (link) => link.status === "queued" || link.status === "generating"
  )
);

function isActive(link?: StoryVideoLinkVO | null): boolean {
  return Boolean(link && (link.status === "queued" || link.status === "generating"));
}

function episodeLabel(video: StoryVideoVO): string {
  return video.episode_no ? `第${video.episode_no}集` : "未分组片段";
}

function linkLabel(link: StoryVideoLinkVO): string {
  if (link.from_episode_no != null && link.to_episode_no != null) {
    return `第${link.from_episode_no}→${link.to_episode_no}集衔接`;
  }
  return link.title || "衔接片段";
}

function formatDuration(ms: number | null): string {
  return ms ? `${(ms / 1000).toFixed(1)}s` : "—";
}

async function loadConfig() {
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
    supportsLastFrame.value = options.supports_last_frame !== false;
  } catch {
    // 配置接口不可用时沿用默认规格，生成时由后端兜底
  }
}

async function loadLinks() {
  const res = await videoApi.links(props.projectId);
  episodes.value = res.data?.episodes ?? [];
  links.value = res.data?.links ?? [];
}

async function loadAll() {
  loading.value = true;
  try {
    await Promise.all([loadConfig(), loadLinks()]);
    syncPolling();
  } finally {
    loading.value = false;
  }
}

async function refreshAll() {
  loading.value = true;
  try {
    await loadLinks();
  } finally {
    loading.value = false;
  }
}

onMounted(() => loadAll());
onUnmounted(stopPolling);

// —— 轮询：衔接片段生成期间轻量刷新 ——
let pollTimer: ReturnType<typeof setInterval> | null = null;

function syncPolling() {
  if (activeLinks.value.length > 0) {
    if (!pollTimer) {
      pollTimer = setInterval(refreshLinks, 3000);
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

async function refreshLinks() {
  const previous = new Map(links.value.map((link) => [link.id, link.status]));
  const hadActive = activeLinks.value.length > 0;
  try {
    await loadLinks();
    for (const link of links.value) {
      const before = previous.get(link.id);
      if (before && before !== "failed" && link.status === "failed") {
        ElMessage.error(
          `衔接片段「${linkLabel(link)}」生成失败${link.error_message ? "：" + link.error_message : ""}`
        );
      }
    }
    if (hadActive && activeLinks.value.length === 0) {
      ElMessage.success("衔接片段任务已全部结束");
      emit("changed");
    }
    syncPolling();
  } catch {
    stopPolling();
  }
}

// —— 生成衔接片段 ——
const dialogVisible = ref(false);
const submitting = ref(false);
const currentLink = ref<LinkFlow | null>(null);
const promptDraft = ref("");

function openGenerate(pair: LinkFlow) {
  currentLink.value = pair;
  promptDraft.value = (pair.link?.prompt || DEFAULT_LINK_PROMPT).trim();
  dialogVisible.value = true;
}

async function submitLink() {
  if (!currentLink.value) return;
  const prompt = promptDraft.value.trim();
  if (!prompt) {
    ElMessage.warning("衔接提示词不能为空");
    return;
  }
  submitting.value = true;
  try {
    await videoApi.createLink(props.projectId, {
      from_video_id: currentLink.value.from.id,
      to_video_id: currentLink.value.to.id,
      prompt,
      resolution: resolution.value || undefined,
      ratio: ratio.value || undefined,
      duration: duration.value || undefined,
    });
    ElMessage.success("已提交集间衔接片段生成");
    dialogVisible.value = false;
    await loadLinks();
    syncPolling();
    emit("changed");
  } catch {
    // 错误拦截器统一提示
  } finally {
    submitting.value = false;
  }
}

const stopping = ref<Record<string, boolean>>({});

async function handleStop(link: StoryVideoLinkVO) {
  stopping.value[link.id] = true;
  try {
    await videoApi.stop(link.id);
    ElMessage.warning("已中止衔接片段生成");
    await loadLinks();
    syncPolling();
  } catch {
    // 错误拦截器统一提示
  } finally {
    stopping.value[link.id] = false;
  }
}

async function handleDelete(link: StoryVideoLinkVO) {
  const confirmed = await confirmDanger(`确定删除衔接片段「${linkLabel(link)}」吗？`);
  if (!confirmed) return;
  try {
    await videoApi.remove(link.id);
    ElMessage.success("衔接片段已删除");
    await loadLinks();
    syncPolling();
    emit("changed");
  } catch {
    // 错误拦截器统一提示
  }
}

// —— 播放 / 下载 ——
const playVisible = ref(false);
const playing = ref<StoryVideoVO | null>(null);

function openPlay(video?: StoryVideoVO | null) {
  if (!video?.video_file) {
    ElMessage.info("该片段尚未生成完成");
    return;
  }
  playing.value = video;
  playVisible.value = true;
}

function safeFilename(name: string): string {
  return name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "视频片段";
}

function handleDownload(video?: StoryVideoVO | null) {
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
</script>

<template>
  <div class="link-panel">
    <div class="link-head">
      <div>
        <div class="link-title">关联集 · 集间衔接片段</div>
        <div class="link-desc">
          各集片段独立并发生成，集间画面可能出现跳变。这里抽取上一集成片尾帧作首帧、
          下一集成片首帧作尾帧，生成一段过渡片段；下载后插入两集之间完成衔接。
        </div>
      </div>
      <div class="link-head-actions">
        <el-tag v-if="modelName" size="small" type="info">{{ modelName }}</el-tag>
        <el-tag v-if="!supportsLastFrame" size="small" type="warning" effect="plain">
          当前模型不支持尾帧，衔接仅保证起幅
        </el-tag>
        <el-button text type="primary" :loading="loading" @click="refreshAll">刷新</el-button>
      </div>
    </div>

    <div v-loading="loading" class="flow-wrap">
      <div v-if="episodes.length >= 2" class="flow-list">
        <template v-for="item in flow" :key="item.type === 'episode' ? `ep-${item.episode.id}` : `link-${item.from.id}-${item.to.id}`">
          <div v-if="item.type === 'episode'" class="episode-card">
            <el-image
              v-if="item.episode.cover_file"
              :src="storyFileUrl(item.episode.cover_file)"
              fit="cover"
              class="episode-cover"
            />
            <div v-else class="episode-cover placeholder">无封面</div>
            <div class="episode-body">
              <div class="episode-title">
                {{ episodeLabel(item.episode) }}
                <span v-if="item.episode.title" class="episode-sub"> · {{ item.episode.title }}</span>
              </div>
              <div class="episode-meta">{{ formatDuration(item.episode.duration_ms) }}</div>
              <div class="episode-actions">
                <el-button size="small" link @click="openPlay(item.episode)">播放</el-button>
                <el-button size="small" link type="success" @click="handleDownload(item.episode)">
                  下载
                </el-button>
              </div>
            </div>
          </div>

          <div v-else class="link-slot">
            <div class="link-slot-main">
              <span class="link-slot-title">
                衔接 {{ episodeLabel(item.from) }} 尾帧 → {{ episodeLabel(item.to) }} 首帧
              </span>
              <el-tag v-if="item.link" size="small" :type="STATUS_TAG[item.link.status] || 'info'">
                {{ STATUS_LABEL[item.link.status] || item.link.status }}
              </el-tag>
              <el-tag
                v-if="
                  item.link &&
                  (item.link.from_video_id !== item.from.id ||
                    item.link.to_video_id !== item.to.id)
                "
                size="small"
                type="warning"
                effect="plain"
                title="该衔接片段基于重新生成前的旧片段，建议重新生成"
              >
                基于旧片段
              </el-tag>
              <span v-if="item.link?.duration_ms" class="link-meta">
                {{ formatDuration(item.link.duration_ms) }}
              </span>
              <span v-if="item.link?.error_message" class="link-error">
                {{ item.link.error_message }}
              </span>
            </div>
            <div class="link-slot-actions">
              <template v-if="item.link">
                <el-button
                  v-if="isActive(item.link)"
                  size="small"
                  type="danger"
                  plain
                  :loading="stopping[item.link.id]"
                  @click="handleStop(item.link)"
                >
                  停止
                </el-button>
                <template v-else>
                  <el-button
                    v-if="item.link.status === 'done'"
                    size="small"
                    link
                    @click="openPlay(item.link)"
                  >
                    播放
                  </el-button>
                  <el-button
                    v-if="item.link.status === 'done'"
                    size="small"
                    link
                    type="success"
                    @click="handleDownload(item.link)"
                  >
                    下载
                  </el-button>
                  <el-button size="small" link type="primary" @click="openGenerate(item)">
                    重新生成
                  </el-button>
                  <el-button size="small" link type="danger" @click="handleDelete(item.link)">
                    删除
                  </el-button>
                </template>
              </template>
              <el-button v-else size="small" type="primary" plain @click="openGenerate(item)">
                生成衔接片段
              </el-button>
            </div>
          </div>
        </template>
      </div>
      <el-empty
        v-else-if="!loading"
        description="至少需要两集已完成片段，才能生成集间衔接"
        :image-size="90"
      />
    </div>

    <!-- 生成衔接片段 -->
    <el-dialog
      v-model="dialogVisible"
      :title="
        currentLink
          ? `生成衔接：${episodeLabel(currentLink.from)} → ${episodeLabel(currentLink.to)}`
          : '生成集间衔接片段'
      "
      width="600px"
      append-to-body
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        :title="
          supportsLastFrame
            ? '首帧取上一集成片尾帧、尾帧取下一集成片首帧；生成完成后插入两集之间即可。'
            : '当前模型不支持尾帧入参，本次只提交上一集尾帧作首帧，结尾画面可能无法精确对齐下一集首帧。'
        "
        style="margin-bottom: 12px"
      />
      <div class="dialog-specs">
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
      </div>
      <el-input
        v-model="promptDraft"
        type="textarea"
        :autosize="{ minRows: 4 }"
        placeholder="衔接提示词"
      />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitLink">
          开始生成
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
.link-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  padding: 12px 14px;
  background: #fafbfd;
  margin-bottom: 14px;
}
.link-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.link-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #7d879a;
  line-height: 1.5;
}
.link-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.flow-wrap {
  min-height: 120px;
}
.flow-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.episode-card {
  display: flex;
  gap: 12px;
  align-items: center;
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  padding: 10px 12px;
}
.episode-cover {
  width: 160px;
  height: 90px;
  flex: none;
  border-radius: 8px;
}
.episode-cover.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f2f4f8;
  color: #9aa4b2;
  font-size: 12px;
}
.episode-body {
  min-width: 0;
}
.episode-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.episode-sub {
  font-size: 12px;
  font-weight: 400;
  color: #7d879a;
}
.episode-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #7d879a;
}
.episode-actions {
  margin-top: 4px;
  display: flex;
  gap: 4px;
}
.link-slot {
  margin-left: 24px;
  padding: 8px 12px;
  border: 1px dashed #c7d2fe;
  border-radius: 8px;
  background: #f8faff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.link-slot-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.link-slot-title {
  font-size: 12px;
  font-weight: 500;
  color: #374151;
}
.link-meta {
  font-size: 12px;
  color: #7d879a;
}
.link-error {
  font-size: 12px;
  color: #d9534f;
}
.link-slot-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dialog-specs {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.setting-select {
  width: 130px;
}
.setting-duration {
  width: 110px;
}
.player {
  width: 100%;
  max-height: 420px;
  background: #000;
}
</style>
