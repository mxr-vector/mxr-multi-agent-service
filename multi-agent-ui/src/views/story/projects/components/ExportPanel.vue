<script setup lang="ts">
/**
 * 导出包面板：统一格式（角色+剧本+关键帧）快照生成、ZIP 素材包打包下载与素材内容预览。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Download, View } from "@element-plus/icons-vue";
import { exportApi, storyFileUrl, STORY_EXPORT_URL, type StoryExportPackageVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";
import { getToken } from "@/utils/auth";

const props = defineProps<{
  projectId: string;
}>();

const loading = ref(false);
const list = ref<StoryExportPackageVO[]>([]);
const downloadingId = ref<string | null>(null);

async function loadExports() {
  loading.value = true;
  try {
    const res = await exportApi.list(props.projectId, { page: 1, size: 50 });
    list.value = res.data?.items ?? [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadExports);

// —— 生成 ——
const createVisible = ref(false);
const creating = ref(false);
const createForm = reactive({ name: "", target_platform: "", auto_download: true });

function openCreate() {
  Object.assign(createForm, { name: "", target_platform: "", auto_download: true });
  createVisible.value = true;
}

async function handleCreate() {
  creating.value = true;
  try {
    const res = await exportApi.create(props.projectId, {
      name: createForm.name.trim() || undefined,
      target_platform: createForm.target_platform.trim() || undefined,
    });
    ElMessage.success("导出包已生成");
    createVisible.value = false;
    await loadExports();
    if (createForm.auto_download && res.data) {
      handleDownload(res.data);
    }
  } finally {
    creating.value = false;
  }
}

// —— 下载 ZIP ——
function handleDownload(pkg: StoryExportPackageVO) {
  downloadingId.value = pkg.id;
  try {
    const token = getToken();
    const base = import.meta.env.VITE_APP_BASE_API || "";
    const filename = `${pkg.name || "export"}.zip`;
    // 采用浏览器原生直链下载通道（由浏览器原生接管下载进度条与落盘，杜绝 Blob 被提前 revoke 导致的无响应）
    const downloadUrl = `${base}${STORY_EXPORT_URL.download(pkg.id)}${token ? `?token=${encodeURIComponent(token)}` : ""}`;

    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    setTimeout(() => {
      document.body.removeChild(link);
    }, 2000);
    ElMessage.success("导出包 ZIP 下载已开始");
  } catch (e) {
    console.error(e);
    ElMessage.error("导出包下载失败");
  } finally {
    setTimeout(() => {
      downloadingId.value = null;
    }, 1000);
  }
}

// —— 查看内容详情 ——
const viewVisible = ref(false);
const viewing = ref<StoryExportPackageVO | null>(null);
const activeViewTab = ref<"keyframe" | "character" | "script">("keyframe");

function openView(pkg: StoryExportPackageVO) {
  viewing.value = pkg;
  activeViewTab.value = "keyframe";
  viewVisible.value = true;
}

interface ScriptData {
  title?: string;
  version?: number;
  content?: string;
}

interface CharacterArtData {
  id?: string;
  name?: string;
  image_file?: string;
  art_type?: string;
  is_primary?: boolean;
}

interface CharacterData {
  id?: string;
  name?: string;
  role_type?: string;
  appearance_prompt?: string;
  profile?: string | Record<string, unknown>;
  style?: string | Record<string, unknown>;
  arts?: CharacterArtData[];
  avatar_file?: string;
}

interface KeyframeData {
  id?: string;
  scene_no?: number;
  shot_no?: number;
  name?: string;
  scene_description?: string;
  visual_description?: string;
  camera_description?: string;
  prompt?: string;
  negative_prompt?: string;
  image_file?: string;
  characters?: Array<{ character_name?: string }>;
}

const currentScript = computed<ScriptData>(() => {
  return (viewing.value?.payload as { script?: ScriptData })?.script ?? {};
});

const currentCharacters = computed<CharacterData[]>(() => {
  const chars = (viewing.value?.payload as { characters?: CharacterData[] })?.characters;
  return Array.isArray(chars) ? chars : [];
});

const currentKeyframes = computed<KeyframeData[]>(() => {
  const kfs = (viewing.value?.payload as { keyframes?: KeyframeData[] })?.keyframes;
  return Array.isArray(kfs) ? kfs : [];
});

function getCharCount(pkg: StoryExportPackageVO): number {
  const characters = (pkg.payload as { characters?: unknown[] })?.characters;
  return Array.isArray(characters) ? characters.length : 0;
}

function getKeyframeCount(pkg: StoryExportPackageVO): number {
  const keyframes = (pkg.payload as { keyframes?: unknown[] })?.keyframes;
  return Array.isArray(keyframes) ? keyframes.length : 0;
}
</script>

<template>
  <div class="export-panel">
    <div class="panel-toolbar">
      <span class="panel-hint">
        统一装配「当前剧本 + 出演角色 + 关键帧」，打包为包含剧本文档、人物立绘图片、关键帧图片与提示词的 ZIP 素材包；历史包为不可变快照。
      </span>
      <el-button type="primary" @click="openCreate">生成导出包</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column label="版本" prop="version" width="70">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="名称" prop="name" min-width="160" show-overflow-tooltip />
      <el-table-column label="包含素材" min-width="170">
        <template #default="{ row }">
          <span class="summary-badge">角色 {{ getCharCount(row) }}</span>
          <span class="summary-badge">关键帧 {{ getKeyframeCount(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="平台备注" min-width="110">
        <template #default="{ row }">{{ row.target_platform || "—" }}</template>
      </el-table-column>
      <el-table-column label="生成时间" width="160">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            link
            type="primary"
            :loading="downloadingId === row.id"
            :icon="Download"
            @click="handleDownload(row)"
          >
            下载 ZIP
          </el-button>
          <el-button size="small" link :icon="View" @click="openView(row)">查看详情</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有导出包" :image-size="80" />
      </template>
    </el-table>

    <!-- 生成 -->
    <el-dialog v-model="createVisible" title="生成导出包" width="520px" append-to-body destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="缺省自动生成" />
        </el-form-item>
        <el-form-item label="平台备注">
          <el-input v-model="createForm.target_platform" placeholder="如：可灵 / 即梦（仅备注）" />
        </el-form-item>
        <el-form-item label="下载设置">
          <el-checkbox v-model="createForm.auto_download">生成后自动启动 ZIP 素材包下载</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 查看包内内容 -->
    <el-dialog
      v-model="viewVisible"
      :title="viewing?.name ?? '导出包素材清单'"
      width="820px"
      append-to-body
      destroy-on-close
    >
      <div v-if="viewing" class="view-header">
        <div class="pkg-tags">
          <el-tag size="small" type="info">剧本 v{{ currentScript.version ?? 1 }}</el-tag>
          <el-tag size="small" type="success">包含角色 {{ currentCharacters.length }} 位</el-tag>
          <el-tag size="small" type="warning">包含关键帧 {{ currentKeyframes.length }} 个</el-tag>
        </div>
        <div class="view-actions">
          <el-button
            type="primary"
            size="small"
            :icon="Download"
            :loading="downloadingId === viewing.id"
            @click="handleDownload(viewing)"
          >
            下载 ZIP 素材包
          </el-button>
        </div>
      </div>

      <div class="view-hint-box">
        📦 ZIP 压缩包已打包包含：剧本文档（.md/.txt）、人物立绘高清图与人设信息、关键帧高清图片与各镜头提示词、完整说明文档。
      </div>

      <el-tabs v-model="activeViewTab" class="view-tabs">
        <el-tab-pane :label="`关键帧 (${currentKeyframes.length})`" name="keyframe">
          <div v-if="currentKeyframes.length === 0" class="empty-tip">未包含关键帧</div>
          <div v-else class="keyframes-grid">
            <div v-for="(kf, idx) in currentKeyframes" :key="idx" class="kf-card">
              <div class="kf-image-box">
                <el-image
                  v-if="kf.image_file"
                  :src="storyFileUrl(kf.image_file)"
                  :preview-src-list="[storyFileUrl(kf.image_file)]"
                  fit="cover"
                  class="kf-img"
                  preview-teleported
                />
                <div v-else class="kf-no-image">未生成图片</div>
              </div>
              <div class="kf-info">
                <div class="kf-title">
                  <el-tag size="small" effect="plain">场景 {{ kf.scene_no ?? '?' }}-镜头 {{ kf.shot_no ?? '?' }}</el-tag>
                  <span class="kf-name">{{ kf.name || '未命名' }}</span>
                </div>
                <div v-if="kf.visual_description || kf.scene_description" class="kf-desc">
                  {{ kf.visual_description || kf.scene_description }}
                </div>
                <div class="kf-prompt" :title="kf.prompt">{{ kf.prompt }}</div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`出演角色 (${currentCharacters.length})`" name="character">
          <div v-if="currentCharacters.length === 0" class="empty-tip">未包含出演角色</div>
          <div v-else class="chars-grid">
            <div v-for="(char, idx) in currentCharacters" :key="idx" class="char-card">
              <div class="char-arts">
                <template v-if="char.arts && char.arts.length > 0">
                  <el-image
                    v-for="art in char.arts"
                    :key="art.id"
                    :src="storyFileUrl(art.image_file)"
                    :preview-src-list="[storyFileUrl(art.image_file)]"
                    fit="cover"
                    class="char-art-img"
                    preview-teleported
                  />
                </template>
                <el-image
                  v-else-if="char.avatar_file"
                  :src="storyFileUrl(char.avatar_file)"
                  fit="cover"
                  class="char-art-img"
                  preview-teleported
                />
                <div v-else class="char-no-art">暂无立绘</div>
              </div>
              <div class="char-info">
                <div class="char-name-row">
                  <span class="char-name">{{ char.name || '未命名角色' }}</span>
                  <el-tag v-if="char.role_type" size="small" type="info">{{ char.role_type }}</el-tag>
                </div>
                <div v-if="char.appearance_prompt" class="char-desc">
                  <span class="desc-label">外观：</span>{{ char.appearance_prompt }}
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`剧本 (v${currentScript.version ?? 1})`" name="script">
          <div class="script-box">
            <div class="script-header">
              <h3 class="script-title">{{ currentScript.title || '未命名剧本' }}</h3>
              <el-tag size="small">第 {{ currentScript.version ?? 1 }} 版</el-tag>
            </div>
            <pre class="script-content">{{ currentScript.content || '（无剧本内容）' }}</pre>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
  </div>
</template>

<style scoped>
.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 12px;
}
.panel-hint {
  font-size: 12px;
  color: #7d879a;
  line-height: 1.5;
}
.summary-badge {
  display: inline-block;
  padding: 1px 6px;
  margin-right: 6px;
  font-size: 12px;
  border-radius: 4px;
  background: #f0f2f5;
  color: #555e6d;
}
.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 12px;
  flex-wrap: wrap;
}
.pkg-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}
.view-actions {
  display: flex;
  gap: 8px;
}
.view-hint-box {
  padding: 8px 12px;
  margin-bottom: 12px;
  background: #f0f7ff;
  border: 1px solid #d0e5ff;
  border-radius: 6px;
  font-size: 12px;
  color: #2b6cb0;
  line-height: 1.5;
}
.view-tabs {
  margin-top: 4px;
}
.empty-tip {
  padding: 30px;
  text-align: center;
  color: #8c9ba5;
  font-size: 13px;
}
.keyframes-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;
}
.kf-card {
  display: flex;
  gap: 12px;
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e9edf2;
  border-radius: 8px;
}
.kf-image-box {
  width: 100px;
  height: 75px;
  flex-shrink: 0;
  border-radius: 6px;
  overflow: hidden;
  background: #eef2f6;
  display: flex;
  align-items: center;
  justify-content: center;
}
.kf-img {
  width: 100%;
  height: 100%;
}
.kf-no-image {
  font-size: 11px;
  color: #94a3b8;
}
.kf-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kf-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kf-name {
  font-weight: 500;
  font-size: 13px;
  color: #1e293b;
}
.kf-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}
.kf-prompt {
  font-size: 12px;
  color: #0284c7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chars-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;
}
.char-card {
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e9edf2;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.char-arts {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  min-height: 80px;
  align-items: center;
}
.char-art-img {
  width: 70px;
  height: 90px;
  border-radius: 4px;
  flex-shrink: 0;
}
.char-no-art {
  width: 100%;
  text-align: center;
  color: #94a3b8;
  font-size: 11px;
}
.char-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.char-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.char-name {
  font-weight: 500;
  font-size: 13px;
  color: #1e293b;
}
.char-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}
.desc-label {
  color: #94a3b8;
}
.script-box {
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e9edf2;
  border-radius: 8px;
  max-height: 480px;
  overflow-y: auto;
}
.script-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e2e8f0;
}
.script-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}
.script-content {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
