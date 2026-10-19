<script setup lang="ts">
/**
 * 剧本独立编辑与浏览页面：
 * 替代小弹窗，提供沉浸式长文本编辑、版本切换对比、分集目录与创作规范参考。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  ArrowLeft,
  Check,
  DocumentAdd,
  DocumentCopy,
  InfoFilled,
  List,
} from "@element-plus/icons-vue";
import { projectApi, scriptApi, type StoryProjectDetailVO, type StoryScriptVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";
import { VMdEditor, NormalToolbar, MD_PREVIEW_DEFAULTS } from "@/utils/md-editor-v3";
import type { ToolbarNames, Footers, ExposeParam } from "md-editor-v3";

const route = useRoute();
const router = useRouter();

const projectId = computed(() => String(route.params.id ?? ""));
const targetScriptId = computed(() => (route.query.scriptId as string) || null);

const project = ref<StoryProjectDetailVO | null>(null);
const versionList = ref<StoryScriptVO[]>([]);
const listLoading = ref(false);
const saving = ref(false);

// 当前正在编辑的剧本对象（null 表示正在新建版本）
const currentScript = ref<StoryScriptVO | null>(null);
const isCreate = computed(() => !currentScript.value);

// 表单状态
const form = reactive({
  title: "",
  content: "",
  setCurrent: true,
});

// 编辑区辅助状态与编辑器实例
const editorFontSize = ref(15);
const editorRef = ref<ExposeParam | null>(null);

// 剧本分集规范模板
const SCRIPT_TEMPLATE = `### 第1集（预估生成时长：15秒）

**[场景]** 晨光初醒的旧书店，阳光透过斑驳玻璃照在落灰书架上。
**[角色]** 林晚，神色迷茫地翻开桌上的泛黄日记本。
**[旁白]** 那是故事开始的第一天。
**[台词]**
- **林晚**：（低语）这段记忆……为什么我不记得发生过？
`;

// 插入规范模板到编辑器
function handleInsertTemplate() {
  if (!form.content.trim()) {
    form.content = SCRIPT_TEMPLATE;
  } else {
    const editorInstance = editorRef.value;
    if (editorInstance) {
      editorInstance.insert((_selectedText: string) => {
        return {
          targetValue: "\n\n" + SCRIPT_TEMPLATE,
          select: false,
          deviationStart: 0,
          deviationEnd: 0,
        };
      });
    } else {
      form.content += "\n\n" + SCRIPT_TEMPLATE;
    }
  }
  ElMessage.success("已插入剧本规范模板");
}

// Markdown 编辑器工具栏配置
const toolbars: ToolbarNames[] = [
  "bold",
  "underline",
  "italic",
  "strikeThrough",
  "-",
  "title",
  "quote",
  "unorderedList",
  "orderedList",
  "task",
  "-",
  "table",
  "code",
  "link",
  "image",
  "-",
  "revoke",
  "next",
  "save",
  0, // 自定义插槽：插入分集模板
  "=",
  "prettier",
  "pageFullscreen",
  "fullscreen",
  "preview",
  "previewOnly",
  "catalog",
];

// 编辑器页脚配置
const footers: Footers[] = ["markdownTotal", "=", "scrollSwitch"];

// 统计
const stats = computed(() => {
  const text = form.content || "";
  const charCount = text.length;
  const lineCount = text ? text.split("\n").length : 0;
  // 匹配分集（如 第1集、第2幕、第3场、Scene 1）
  const episodeMatches =
    text.match(/(第[0-9一二三四五六七八九十百]+[集幕场]|Scene\s*[0-9]+)/gi) || [];
  return {
    charCount,
    lineCount,
    episodes: episodeMatches.length,
  };
});

// 分集大纲导航列表（支持常规格式与 Markdown 标题前缀，如 ### 第1集）
const episodes = computed(() => {
  const text = form.content || "";
  const lines = text.split("\n");
  const result: { label: string; lineIndex: number }[] = [];
  const epRegex = /^\s*(?:#{1,6}\s*)?(第[0-9一二三四五六七八九十百]+[集幕场]|Scene\s*[0-9]+.*)/i;

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (epRegex.test(trimmed)) {
      result.push({
        label: trimmed.replace(/^#{1,6}\s*/, "").slice(0, 30),
        lineIndex: index,
      });
    }
  });
  return result;
});

async function loadProjectInfo() {
  if (!projectId.value) return;
  try {
    const res = await projectApi.detail(projectId.value);
    project.value = res.data;
  } catch {
    // 拦截器已处理
  }
}

async function loadVersionList(autoSelectId?: string | null) {
  if (!projectId.value) return;
  listLoading.value = true;
  try {
    const res = await scriptApi.list(projectId.value, { page: 1, size: 50 });
    versionList.value = res.data?.items ?? [];

    const selectId = autoSelectId ?? targetScriptId.value;
    if (selectId) {
      const found = versionList.value.find((item) => item.id === selectId);
      if (found) {
        selectVersion(found);
      } else {
        // 未找到指定版本，回退为新建
        switchToCreate();
      }
    } else if (versionList.value.length > 0 && !targetScriptId.value && !isCreate.value) {
      // 默认选中第一个
      selectVersion(versionList.value[0]);
    } else if (isCreate.value) {
      // 保持新建状态
    } else if (versionList.value.length > 0) {
      selectVersion(versionList.value[0]);
    }
  } finally {
    listLoading.value = false;
  }
}

function selectVersion(script: StoryScriptVO) {
  currentScript.value = script;
  form.title = script.title ?? "";
  form.content = script.content ?? "";
  form.setCurrent = script.is_current;
  // 更新 query 供分享与刷新
  if (route.query.scriptId !== script.id) {
    router.replace({
      path: route.path,
      query: { ...route.query, scriptId: script.id },
    });
  }
}

function switchToCreate(copyCurrent = false) {
  currentScript.value = null;
  form.title = copyCurrent && form.title ? `${form.title} (新草稿)` : "";
  if (!copyCurrent) {
    form.content = "";
  }
  form.setCurrent = true;
  const nextQuery = { ...route.query };
  delete nextQuery.scriptId;
  router.replace({ path: route.path, query: nextQuery });
}

onMounted(async () => {
  await Promise.all([loadProjectInfo(), loadVersionList()]);
});

watch(
  () => route.query.scriptId,
  (newId) => {
    if (newId && (!currentScript.value || currentScript.value.id !== newId)) {
      const found = versionList.value.find((item) => item.id === newId);
      if (found) selectVersion(found);
    } else if (!newId && currentScript.value) {
      switchToCreate();
    }
  }
);

function goBack() {
  router.push({
    path: `/story/projects/${projectId.value}`,
    query: { tab: "script" },
  });
}

// 保存当前（若为编辑已有则更新，若为新建则保存新版本）
async function handleSave() {
  if (!form.content.trim()) {
    ElMessage.error("剧本内容不能为空");
    return;
  }

  saving.value = true;
  try {
    if (isCreate.value) {
      const res = await scriptApi.save(projectId.value, {
        content: form.content.trim(),
        title: form.title.trim() || null,
        source: "user",
        set_current: form.setCurrent,
      });
      ElMessage.success("新剧本版本已创建");
      const createdId = res.data?.id;
      await loadVersionList(createdId);
    } else {
      if (!currentScript.value) return;
      await scriptApi.update(currentScript.value.id, {
        content: form.content.trim(),
        title: form.title.trim() || null,
      });
      ElMessage.success("剧本更新成功");
      await loadVersionList(currentScript.value.id);
    }
  } finally {
    saving.value = false;
  }
}

// 另存为新版本
async function handleSaveAsNew() {
  if (!form.content.trim()) {
    ElMessage.error("剧本内容不能为空");
    return;
  }

  saving.value = true;
  try {
    const res = await scriptApi.save(projectId.value, {
      content: form.content.trim(),
      title: form.title.trim() || null,
      source: "user",
      set_current: form.setCurrent,
    });
    ElMessage.success("已另存为新版本");
    const createdId = res.data?.id;
    await loadVersionList(createdId);
  } finally {
    saving.value = false;
  }
}

// 切换当前生效版本
async function handleSetCurrent() {
  if (!currentScript.value) return;
  try {
    await scriptApi.switchCurrent(currentScript.value.id);
    ElMessage.success(`已切换 v${currentScript.value.version} 为当前生效版本`);
    await loadVersionList(currentScript.value.id);
  } catch {
    // 拦截器提示
  }
}

// 跳转到指定行
function scrollToEpisode(lineIndex: number) {
  nextTick(() => {
    const editorInstance = editorRef.value;
    if (!editorInstance) return;
    const view = editorInstance.getEditorView();
    if (view) {
      try {
        const targetLine = Math.min(Math.max(1, lineIndex + 1), view.state.doc.lines);
        const line = view.state.doc.line(targetLine);
        view.dispatch({
          selection: { anchor: line.from },
          scrollIntoView: true,
        });
        view.focus();
        return;
      } catch (err) {
        console.warn("EditorView scroll failed:", err);
      }
    }
    // 回退方案：字符位置定位
    const lines = form.content.split("\n");
    let charPos = 0;
    for (let i = 0; i < lineIndex && i < lines.length; i++) {
      charPos += lines[i].length + 1;
    }
    editorInstance.focus({ cursorPos: charPos });
  });
}
</script>

<template>
  <div class="script-edit-page list-page">
    <!-- 顶栏导航与操作 -->
    <div class="topbar">
      <div class="topbar-left">
        <el-button :icon="ArrowLeft" text class="back-btn" @click="goBack">返回工作区</el-button>
        <el-divider direction="vertical" />
        <div class="project-info">
          <span class="project-title">{{ project?.title || "剧本项目" }}</span>
          <span class="page-mode">
            <template v-if="isCreate">
              <el-tag size="small" type="primary">新建版本</el-tag>
            </template>
            <template v-else>
              <el-tag size="small" type="success">v{{ currentScript?.version }}</el-tag>
              <el-tag
                v-if="currentScript?.is_current"
                size="small"
                type="warning"
                class="current-badge"
              >
                当前生效
              </el-tag>
            </template>
          </span>
        </div>
      </div>

      <div class="topbar-right">
        <el-button-group class="font-controls">
          <el-button size="small" @click="editorFontSize = Math.max(12, editorFontSize - 1)">
            A-
          </el-button>
          <el-button size="small" @click="editorFontSize = Math.min(22, editorFontSize + 1)">
            A+
          </el-button>
        </el-button-group>

        <template v-if="!isCreate">
          <el-button v-if="!currentScript?.is_current" size="default" @click="handleSetCurrent">
            设为当前版本
          </el-button>
          <el-button size="default" :icon="DocumentCopy" :loading="saving" @click="handleSaveAsNew">
            另存为新版本
          </el-button>
        </template>

        <el-button type="primary" :icon="Check" :loading="saving" @click="handleSave">
          {{ isCreate ? "保存新版本" : "保存修改" }}
        </el-button>
      </div>
    </div>

    <!-- 主体两栏布局 -->
    <div class="workspace-container">
      <!-- 左侧版本导航与大纲索引 -->
      <div class="sidebar-panel">
        <div class="sidebar-section version-history-section">
          <div class="sidebar-header">
            <span class="sidebar-title">版本列表 ({{ versionList.length }})</span>
            <el-button
              size="small"
              type="primary"
              link
              :icon="DocumentAdd"
              @click="switchToCreate(false)"
            >
              新建版本
            </el-button>
          </div>

          <div v-loading="listLoading" class="version-list-scroll">
            <div
              v-for="ver in versionList"
              :key="ver.id"
              class="version-item"
              :class="{
                active: currentScript?.id === ver.id,
                'is-current': ver.is_current,
              }"
              @click="selectVersion(ver)"
            >
              <div class="ver-top">
                <span class="ver-badge">v{{ ver.version }}</span>
                <span class="ver-title" :title="ver.title || '无标题'">
                  {{ ver.title || "（未命名版本）" }}
                </span>
                <el-tag
                  v-if="ver.is_current"
                  size="small"
                  type="success"
                  effect="dark"
                  class="active-tag"
                >
                  生效
                </el-tag>
              </div>
              <div class="ver-bottom">
                <span class="ver-source">
                  {{ ver.source === "ai" ? "AI生成" : ver.source === "user" ? "手动编辑" : "上传" }}
                </span>
                <span class="ver-time">{{ formatDateTime(ver.updated_at) }}</span>
              </div>
            </div>

            <el-empty
              v-if="!versionList.length && !listLoading"
              description="暂无版本记录"
              :image-size="70"
            />
          </div>
        </div>

        <!-- 规范提示 -->
        <div class="sidebar-section spec-tip-box">
          <div class="spec-tip-head">
            <el-icon class="spec-icon"><InfoFilled /></el-icon>
            <span class="spec-title">剧本创作规范</span>
          </div>
          <p class="spec-desc">每集需注明预估生成秒数（目前视频模型仅支持 15s 或 30s），例如：</p>
          <div class="spec-example">
            ### 第1集（预估生成时长：15秒）
            <br />
            **[场景]** 繁华雨夜街道
            <br />
            **[台词]** ...
          </div>
          <el-button
            size="small"
            type="warning"
            plain
            :icon="DocumentAdd"
            class="insert-spec-btn"
            @click="handleInsertTemplate"
          >
            插入规范模板
          </el-button>
        </div>

        <!-- 分集大纲导航 -->
        <div v-if="episodes.length" class="sidebar-section episode-nav-section">
          <div class="sidebar-header">
            <span class="sidebar-title">
              <el-icon><List /></el-icon>
              分集大纲 ({{ episodes.length }})
            </span>
          </div>
          <div class="episode-list-scroll">
            <div
              v-for="(ep, idx) in episodes"
              :key="idx"
              class="episode-item"
              @click="scrollToEpisode(ep.lineIndex)"
            >
              <span class="ep-index">#{{ idx + 1 }}</span>
              <span class="ep-label" :title="ep.label">{{ ep.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧主编辑区域 -->
      <div class="editor-main-panel">
        <!-- 标题输入与快捷控制条 -->
        <div class="editor-header-bar">
          <div class="title-field">
            <el-input
              v-model="form.title"
              placeholder="版本标题（可选，如：第一稿 / 导演修订版）"
              size="large"
              clearable
              class="title-input"
            />
          </div>
          <div class="header-options">
            <el-checkbox v-model="form.setCurrent" class="set-current-check">
              设为当前版本
            </el-checkbox>
            <span class="stats-text">
              共
              <strong>{{ stats.charCount }}</strong>
              字 ·
              <strong>{{ stats.lineCount }}</strong>
              行 ·
              <strong>{{ stats.episodes }}</strong>
              个分集/场景
            </span>
          </div>
        </div>

        <!-- 核心文本编辑浏览区 -->
        <div class="editor-body">
          <v-md-editor
            ref="editorRef"
            v-model="form.content"
            editor-id="story-script-editor"
            class="script-md-editor"
            :preview-theme="MD_PREVIEW_DEFAULTS.previewTheme"
            :code-theme="MD_PREVIEW_DEFAULTS.codeTheme"
            :toolbars="toolbars"
            :footers="footers"
            :show-code-row-number="true"
            :scroll-auto="true"
            placeholder="在此输入或编辑剧本文本（支持 Markdown 排版，可实时双栏预览）...

示例规范：
### 第1集（预估生成时长：15秒）
**[场景]** 晨光初醒的旧书店，阳光透过斑驳玻璃照在落灰书架上。
**[角色]** 林晚，神色迷茫地翻开桌上的泛黄日记本。
**[旁白]** 那是故事开始的第一天。
**[台词]**
- **林晚**：（低语）这段记忆……为什么我不记得发生过？"
            :style="{ '--script-editor-font-size': `${editorFontSize}px` }"
            @on-save="handleSave"
          >
            <template #defToolbars>
              <NormalToolbar
                title="插入规范模板"
                @click="handleInsertTemplate"
                @on-click="handleInsertTemplate"
              >
                <template #trigger>
                  <span class="custom-toolbar-btn" title="插入分集规范模板">
                    <el-icon><DocumentAdd /></el-icon>
                    <span class="btn-text">模板</span>
                  </span>
                </template>
              </NormalToolbar>
            </template>
          </v-md-editor>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.script-edit-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px 18px 16px;
  box-sizing: border-box;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #fff;
  border: 1px solid #e5e9f2;
  border-radius: 8px;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.back-btn {
  font-size: 14px;
}

.project-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.project-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2d3d;
}

.current-badge {
  margin-left: 4px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.font-controls {
  margin-right: 6px;
}

.workspace-container {
  display: flex;
  flex: 1;
  gap: 14px;
  min-height: 0;
}

/* 左侧栏 */
.sidebar-panel {
  width: 290px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.sidebar-section {
  background: #fff;
  border: 1px solid #e5e9f2;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
}

.version-history-section {
  flex: 1.2;
  min-height: 180px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  display: flex;
  align-items: center;
  gap: 4px;
}

.version-list-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 2px;
}

.version-item {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  background: #f9fafc;
  cursor: pointer;
  transition: all 0.2s;
}

.version-item:hover {
  background: #f0f4fc;
  border-color: #d0dcf5;
}

.version-item.active {
  background: #eef5ff;
  border-color: #409eff;
}

.ver-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.ver-badge {
  font-weight: 600;
  font-size: 12px;
  color: #409eff;
}

.ver-title {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: #1f2d3d;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.active-tag {
  font-size: 10px;
  height: 18px;
  line-height: 18px;
  padding: 0 4px;
}

.ver-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: #9aa4b2;
}

/* 规范说明 */
.spec-tip-box {
  background: #fdfbf7;
  border-color: #faecd8;
}

.spec-tip-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  color: #e6a23c;
  font-weight: 600;
  font-size: 13px;
}

.spec-desc {
  font-size: 12px;
  color: #7d879a;
  margin: 0 0 6px;
  line-height: 1.4;
}

.spec-example {
  background: #fff;
  border: 1px dashed #e8d9c5;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 11px;
  color: #606266;
  font-family: monospace;
  line-height: 1.4;
}

/* 分集导航 */
.episode-nav-section {
  flex: 1;
  min-height: 140px;
}

.episode-list-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.episode-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: #4b5563;
  transition: background 0.15s;
}

.episode-item:hover {
  background: #edf2fc;
  color: #409eff;
}

.ep-index {
  color: #9aa4b2;
  font-size: 11px;
  width: 22px;
}

.ep-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 右侧主编辑器 */
.editor-main-panel {
  flex: 1;
  background: #fff;
  border: 1px solid #e5e9f2;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.editor-header-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #f0f2f5;
  background: #fbfcfe;
  gap: 16px;
  flex-shrink: 0;
}

.title-field {
  flex: 1;
  max-width: 480px;
}

.title-input :deep(.el-input__wrapper) {
  box-shadow: none;
  border-bottom: 1px solid #dcdfe6;
  border-radius: 0;
  padding-left: 0;
  background: transparent;
}

.title-input :deep(.el-input__wrapper.is-focus) {
  border-bottom-color: #409eff;
}

.title-input :deep(.el-input__inner) {
  font-size: 15px;
  font-weight: 500;
}

.header-options {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stats-text {
  font-size: 12px;
  color: #9aa4b2;
}

.stats-text strong {
  color: #4b5563;
}

.editor-body {
  flex: 1;
  display: flex;
  padding: 0;
  min-height: 0;
  overflow: hidden;
}

.script-md-editor {
  width: 100%;
  height: 100% !important;
  border: none !important;
  background: transparent;
}

/* 动态字体与行高绑定 */
:deep(.script-md-editor .cm-content),
:deep(.script-md-editor .cm-line) {
  font-size: var(--script-editor-font-size, 15px) !important;
  line-height: 1.8 !important;
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB",
    "Microsoft YaHei", monospace;
}

:deep(.script-md-editor .md-editor-preview) {
  font-size: var(--script-editor-font-size, 15px) !important;
  line-height: 1.8 !important;
}

:deep(.script-md-editor .md-editor-preview p),
:deep(.script-md-editor .md-editor-preview li) {
  font-size: var(--script-editor-font-size, 15px) !important;
  line-height: 1.8 !important;
}

/* 剧本特定 Markdown 样式优化：高亮场景与角色提示 */
:deep(.script-md-editor .md-editor-preview blockquote) {
  border-left: 4px solid #409eff;
  background: #f4f8fe;
  padding: 8px 14px;
  margin: 10px 0;
  border-radius: 0 4px 4px 0;
  color: #334155;
}

:deep(.script-md-editor .md-editor-preview h1),
:deep(.script-md-editor .md-editor-preview h2),
:deep(.script-md-editor .md-editor-preview h3) {
  color: #1e293b;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 6px;
  margin-top: 18px;
  margin-bottom: 10px;
}

:deep(.script-md-editor .md-editor-toolbar-wrapper) {
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
}

:deep(.script-md-editor .md-editor-footer) {
  border-top: 1px solid #f0f2f5;
  background: #fafbfc;
  font-size: 12px;
}

.insert-spec-btn {
  margin-top: 8px;
  width: 100%;
}

.custom-toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #409eff;
  cursor: pointer;
  padding: 0 6px;
  height: 24px;
  border-radius: 4px;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  transition: all 0.2s;
  font-weight: 500;
}

.custom-toolbar-btn:hover {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}

.custom-toolbar-btn .btn-text {
  font-size: 11px;
}
</style>
