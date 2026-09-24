<script setup lang="ts">
/**
 * AI 创作抽屉（右栏常驻可收起）：会话管理 + 消息流回放 + 流式生成。
 *
 * 状态与编排收口在 useStoryAi 组合式函数；卡片渲染委托给 ScriptCard /
 * CharacterCardItem；art 消息（图片/失败）为单块简单呈现，内联渲染。
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { characterApi, projectApi, storyAiApi, storyFileUrl, type StoryMessageVO } from "@/api/story";
import { readCard, useStoryAi } from "../../composables/useStoryAi";
import AiGenerateForm from "./AiGenerateForm.vue";
import ScriptCard from "./ScriptCard.vue";
import CharacterCardItem from "./CharacterCardItem.vue";
import KeyframeCardItem from "./KeyframeCardItem.vue";
import CharacterArtCardItem from "./CharacterArtCardItem.vue";

const props = defineProps<{
  projectId: string;
  /** 项目详情（制作参数记忆预填用） */
  project: { style_key: string | null; production_params: Record<string, unknown> | null } | null;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const projectIdRef = computed(() => props.projectId);
const projectRef = computed(() => props.project);
const ai = useStoryAi(projectIdRef, projectRef);

const castingCharacters = ref<Array<{ id: string; name: string }>>([]);

async function loadProjectCasting() {
  if (!props.projectId) return;
  try {
    const res = await projectApi.listCasting(props.projectId);
    castingCharacters.value = (res.data ?? []).map((c) => ({ id: c.id, name: c.name }));
  } catch {
    castingCharacters.value = [];
  }
}

/** 同名角色精确检测（延迟到"存入角色库"时按名查询，避免详情页打开即全量拉角色库） */
async function findSameName(name: string): Promise<{ id: string; name: string } | null> {
  if (!name) return null;
  try {
    const res = await characterApi.list({ page: 1, size: 20, keyword: name });
    const items = res.data?.items ?? [];
    return items.find((ch) => ch.name === name) ?? null;
  } catch {
    return null;
  }
}

onMounted(async () => {
  await Promise.all([ai.init(), loadProjectCasting()]);
  scrollToBottom(true);
});

// 消息流容器引用与滚动控制
const streamRef = ref<HTMLElement | null>(null);

/** 判断当前滚动条是否接近底部（用于决定流式增量时是否自动跟滚，避免打断用户往上浏览历史） */
function isNearBottom(threshold = 120): boolean {
  const el = streamRef.value;
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
}

/**
 * 滚动到底部。
 * @param force 为 true 时强制滚到底部（切换会话、主动发起生成等）；为 false 时仅在接近底部时自动跟滚。
 */
function scrollToBottom(force = false) {
  nextTick(() => {
    const el = streamRef.value;
    if (!el) return;
    if (force || isNearBottom()) {
      el.scrollTop = el.scrollHeight;
    }
  });
}

/** 产物变更后：静默刷新会话消息 + 通知父级刷新项目，保持当前滚动条位置不发生漂移 */
async function onCardChanged() {
  const el = streamRef.value;
  const prevScrollTop = el?.scrollTop;
  await ai.refresh();
  await nextTick();
  if (el && typeof prevScrollTop === "number") {
    el.scrollTop = prevScrollTop;
  }
  emit("changed");
}

/** 流式生成文本更新时，仅在用户处于底部附近时自动跟滚 */
watch(
  () => ai.streamText.value,
  () => {
    if (ai.streaming.value) {
      scrollToBottom(false);
    }
  }
);

/** 生成结束时，若用户在底部则对齐到底部 */
watch(
  () => ai.streaming.value,
  (streaming, prev) => {
    if (!streaming && prev) {
      scrollToBottom(false);
    }
  }
);

async function handleSwitchSession(id: string) {
  await ai.switchSession(id);
  scrollToBottom(true);
}

/** 会话标题输入（可取消） */
async function promptSessionTitle(): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt("会话标题（可空）", "新建生成会话", {
      confirmButtonText: "创建",
      cancelButtonText: "取消",
      inputPlaceholder: "如：剧本初稿",
    });
    return value?.trim() || null;
  } catch {
    return null;
  }
}

async function handleCreateSession() {
  const name = await promptSessionTitle();
  const res = await ai.createSession(name ?? undefined);
  if (res) {
    scrollToBottom(true);
  }
}

async function handleRemoveSession() {
  if (!ai.activeSession.value) return;
  try {
    await ElMessageBox.confirm(
      "删除会话将丢弃其中未沉淀的生成结果，已沉淀的正式资产不受影响。确定删除？",
      "删除会话",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  await ai.removeSession(ai.activeSession.value.id);
  scrollToBottom(true);
}

type OutputTabKey = "script" | "keyframe" | "art" | "all";
const activeTab = ref<OutputTabKey>("script");

function isUser(message: StoryMessageVO) {
  return message.role === "user";
}

/** 判断是否为关键帧关联的出图卡片 */
function isKeyframeArt(msg: StoryMessageVO): boolean {
  if (msg.kind !== "art") return false;
  const name = String(msg.params?.card_name || msg.content || "");
  return (
    name.startsWith("关键帧") ||
    name.startsWith("镜头") ||
    name.includes("关键帧") ||
    name.includes("分镜")
  );
}

/** 关键帧类别判定：关键帧卡或关键帧出图 */
function isKeyframe(msg: StoryMessageVO): boolean {
  return msg.kind === "keyframe" || isKeyframeArt(msg);
}

/** 人物立绘类别判定：角色卡或人物立绘/通用生图 */
function isCharacterOrArt(msg: StoryMessageVO): boolean {
  if (msg.kind === "character") return true;
  if (msg.kind === "art") {
    return !isKeyframeArt(msg);
  }
  return false;
}

/** 剧情类别判定：用户提问、剧本卡或一般回答 */
function isScript(msg: StoryMessageVO): boolean {
  return isUser(msg) || msg.kind === "script" || msg.kind === "general";
}

/** 当前 Tab 过滤后的展示消息列表 */
const filteredMessages = computed(() => {
  const all = ai.messages.value;
  if (activeTab.value === "script") {
    return all.filter(isScript);
  }
  if (activeTab.value === "keyframe") {
    return all.filter(isKeyframe);
  }
  if (activeTab.value === "art") {
    return all.filter(isCharacterOrArt);
  }
  return all;
});

/** Tab 徽标数统计 */
const scriptBadgeCount = computed(() => {
  const scripts = ai.messages.value.filter((m) => m.kind === "script").length;
  if (scripts > 0) return scripts;
  return ai.messages.value.filter(isScript).length;
});

const keyframeBadgeCount = computed(() => {
  return ai.messages.value.filter(isKeyframe).length;
});

const artBadgeCount = computed(() => {
  return ai.messages.value.filter(isCharacterOrArt).length;
});

const tabs = computed(() => [
  {
    key: "script" as OutputTabKey,
    label: "剧情",
    count: scriptBadgeCount.value,
  },
  {
    key: "keyframe" as OutputTabKey,
    label: "关键帧",
    count: keyframeBadgeCount.value,
  },
  {
    key: "art" as OutputTabKey,
    label: "人物立绘",
    count: artBadgeCount.value,
  },
  {
    key: "all" as OutputTabKey,
    label: "全部",
    count: ai.messages.value.length,
  },
]);

/** Tab 空态文案提示 */
const tabEmptyDescription = computed(() => {
  if (activeTab.value === "script") {
    return "暂无剧情内容，向 AI 描述你的故事开始创作";
  }
  if (activeTab.value === "keyframe") {
    return "暂无分镜关键帧，生成剧本后将自动拆解分镜关键帧";
  }
  if (activeTab.value === "art") {
    return "暂无人物立绘与角色卡，点击下方按钮「从剧本提取角色」后可生成立绘";
  }
  return "向 AI 描述你的故事，生成剧本与角色卡";
});

function handleTabChange(tabKey: OutputTabKey) {
  activeTab.value = tabKey;
  nextTick(() => {
    const el = streamRef.value;
    if (el) {
      el.scrollTop = tabKey === "all" || tabKey === "script" ? el.scrollHeight : 0;
    }
  });
}

function handleSend() {
  activeTab.value = "script";
  scrollToBottom(true);
  void ai.send(() => emit("changed"));
}

/** 用户消息气泡内嵌制作参数摘要（有则展示） */
function userParamsSummary(message: StoryMessageVO): string {
  const params = (message.params ?? {}) as Record<string, unknown>;
  const parts = [params.style_name, params.aspect_ratio, params.tone]
    .filter((v) => typeof v === "string" && v)
    .map(String);
  if (typeof params.episodes === "number") parts.push(`${params.episodes}集`);
  return parts.join(" · ");
}

/** 提取用户消息关联的多模态或参考图片列表 */
function getUserImages(message: StoryMessageVO): string[] {
  const images: string[] = [];
  if (message.image_file) {
    images.push(message.image_file);
  }
  const paramsImages = message.params?.images;
  if (Array.isArray(paramsImages)) {
    for (const img of paramsImages) {
      if (typeof img === "string" && img && !images.includes(img)) {
        images.push(img);
      }
    }
  }
  return images;
}

/** 从会话已生成角色卡与项目出演角色提炼角色候选列表（供生图选择关联与按编号快捷插入） */
const characterOptions = computed(() => {
  const result: Array<{ id: string; name: string; art_prompt?: string | null; message_id?: string }> = [];
  const seen = new Set<string>();
  // 1. 优先取当前会话中已经产出的角色卡
  for (const msg of ai.messages.value) {
    if (msg.kind === "character") {
      const card = readCard(msg);
      const name = card?.name || msg.content.replace(/^角色卡[：:]\s*/, "").trim();
      if (name && !seen.has(name)) {
        seen.add(name);
        result.push({
          id: msg.id,
          name,
          art_prompt: card?.art_prompt || msg.prompt,
          message_id: msg.id,
        });
      }
    }
  }
  // 2. 补充项目出演角色（若尚未生成角色卡时也能快捷按编号引用）
  for (const cast of castingCharacters.value) {
    if (cast.name && !seen.has(cast.name)) {
      seen.add(cast.name);
      result.push({
        id: cast.id,
        name: cast.name,
      });
    }
  }
  return result;
});

const generatingArt = ref(false);

async function handleGenerateArt(payload: {
  prompt: string;
  name?: string;
  cardMessageId?: string;
  size?: string;
  quality?: string;
  referenceImages?: string[];
}) {
  if (!ai.activeSessionId.value) {
    await ai.createSession(payload.name ? `图像：${payload.name}` : undefined);
  }
  const sessionId = ai.activeSessionId.value;
  if (!sessionId) {
    ElMessage.error("未能创建或获取生成会话");
    return;
  }
  // 按照出图类型自动切换到对应 Tab
  if (payload.name && (payload.name.startsWith("关键帧") || payload.name.startsWith("镜头"))) {
    activeTab.value = "keyframe";
  } else {
    activeTab.value = "art";
  }
  generatingArt.value = true;
  scrollToBottom(true);
  try {
    await storyAiApi.generateArtDirect(sessionId, {
      prompt: payload.prompt,
      name: payload.name,
      card_message_id: payload.cardMessageId,
      size: payload.size,
      quality: payload.quality,
      reference_images: payload.referenceImages,
    });
    ElMessage.success("已发起图像生成任务");
    await ai.refresh();
    scrollToBottom(true);
    emit("changed");
  } catch {
    // 错误拦截器统一处理
  } finally {
    generatingArt.value = false;
  }
}

/** 未沉淀关键帧计数 */
const unsavedKeyframeCount = computed(() => {
  return ai.messages.value.filter(
    (m) =>
      m.kind === "keyframe" &&
      !m.params?.["sedimented_keyframe_id"] &&
      !m.params?.["is_sedimented"]
  ).length;
});

const savingAllKeyframes = ref(false);

/** 一键存入所有关键帧 */
async function handleSaveAllKeyframes() {
  if (!ai.activeSession.value || savingAllKeyframes.value) return;
  savingAllKeyframes.value = true;
  try {
    const res = await storyAiApi.saveAllKeyframes(ai.activeSession.value.id);
    ElMessage.success(`成功存入 ${res.data?.saved_count ?? 0} 个关键帧到项目`);
    await onCardChanged();
  } catch {
    // 错误已由拦截器处理
  } finally {
    savingAllKeyframes.value = false;
  }
}

/** 角色卡计数 */
const characterCardsCount = computed(() => {
  return ai.messages.value.filter((m) => m.kind === "character").length;
});

/** 未沉淀角色卡计数 */
const unsavedCharacterCount = computed(() => {
  return ai.messages.value.filter(
    (m) => m.kind === "character" && !m.params?.["sedimented_character_id"]
  ).length;
});

/** 会话中是否存在剧本 */
const hasScriptMessage = computed(() => {
  return ai.messages.value.some((m) => m.kind === "script");
});

const extractingCharacters = ref(false);

/** 从剧本提取角色 */
async function handleExtractCharacters() {
  if (!ai.activeSession.value || extractingCharacters.value) {
    if (!ai.activeSession.value) {
      ElMessage.warning("请先选择或新建生成会话");
    }
    return;
  }
  extractingCharacters.value = true;
  try {
    const res = await storyAiApi.extractCharacters(ai.activeSession.value.id);
    const count = res.data?.characters?.length ?? 0;
    const created = res.data?.created_count ?? 0;
    if (created > 0) {
      ElMessage.success(`成功从剧本提取并生成 ${created} 个角色卡`);
    } else if (count > 0) {
      ElMessage.info(`剧本中的 ${count} 个角色已提取就绪`);
    } else {
      ElMessage.warning("未能在剧本中识别出角色，请确认剧本包含人物小传");
    }
    await onCardChanged();
    activeTab.value = "art";
  } catch {
    // 错误拦截器统一处理
  } finally {
    extractingCharacters.value = false;
  }
}

const savingAllCharacters = ref(false);

/** 一键存入所有角色 */
async function handleSaveAllCharacters() {
  if (!ai.activeSession.value || savingAllCharacters.value) return;
  savingAllCharacters.value = true;
  try {
    const res = await storyAiApi.saveAllCharacters(ai.activeSession.value.id);
    ElMessage.success(`成功存入 ${res.data?.saved_count ?? 0} 个角色到角色库并登记出演`);
    await onCardChanged();
  } catch {
    // 错误拦截器统一处理
  } finally {
    savingAllCharacters.value = false;
  }
}

defineExpose({
  /** 生成中标记（父级收起抽屉时提示） */
  isStreaming: computed(() => ai.streaming.value),
});
</script>

<template>
  <div class="ai-drawer">
    <!-- 会话管理 -->
    <div class="drawer-head">
      <el-select
        :model-value="ai.activeSessionId.value"
        size="small"
        placeholder="选择会话"
        class="session-select"
        @change="handleSwitchSession"
      >
        <el-option
          v-for="session in ai.sessions.value"
          :key="session.id"
          :value="session.id"
          :label="session.title || '未命名会话'"
        >
          <span>{{ session.title || "未命名会话" }}</span>
          <span class="option-count">（{{ session.message_count }}）</span>
        </el-option>
      </el-select>
      <el-button size="small" @click="handleCreateSession">新建</el-button>
      <el-button size="small" :disabled="!ai.activeSession.value" @click="handleRemoveSession">
        删除
      </el-button>
    </div>

    <!-- 产物分类 Tab 导航 -->
    <div class="drawer-tabs-wrapper">
      <div class="tabs-segmented">
        <div
          v-for="tab in tabs"
          :key="tab.key"
          class="tab-btn"
          :class="{ active: activeTab === tab.key }"
          @click="handleTabChange(tab.key)"
        >
          <span class="tab-label">{{ tab.label }}</span>
          <span v-if="tab.count > 0" class="tab-badge">{{ tab.count }}</span>
        </div>
      </div>
    </div>

    <!-- 消息流 -->
    <div ref="streamRef" v-loading="ai.loadingMessages.value" class="message-stream">
      <!-- 关键帧待入库快捷 Banner（在关键帧或全部 tab 且存在未入库帧时展示） -->
      <div
        v-if="(activeTab === 'keyframe' || activeTab === 'all') && unsavedKeyframeCount > 0"
        class="tab-action-banner"
      >
        <div class="banner-info">
          <span class="banner-icon">🎬</span>
          <span>待入库关键帧：<strong>{{ unsavedKeyframeCount }}</strong> 个</span>
        </div>
        <el-button
          size="small"
          type="primary"
          :loading="savingAllKeyframes"
          @click="handleSaveAllKeyframes"
        >
          存入全部关键帧
        </el-button>
      </div>

      <!-- 人物立绘快捷 Banner（在人物立绘或全部 tab 展示） -->
      <div
        v-if="activeTab === 'art' || (activeTab === 'all' && (characterCardsCount > 0 || hasScriptMessage))"
        class="tab-action-banner art-action-banner"
      >
        <div class="banner-info">
          <span class="banner-icon">👤</span>
          <span v-if="characterCardsCount > 0">
            角色卡：<strong>{{ characterCardsCount }}</strong> 个
            <template v-if="unsavedCharacterCount > 0">
              （待入库 <strong>{{ unsavedCharacterCount }}</strong> 个）
            </template>
          </span>
          <span v-else>
            暂无角色卡，可从剧本直接提取
          </span>
        </div>
        <div class="banner-actions">
          <el-button
            size="small"
            :type="characterCardsCount === 0 ? 'primary' : 'default'"
            :loading="extractingCharacters"
            @click="handleExtractCharacters"
          >
            {{ characterCardsCount > 0 ? "重新提取角色" : "从剧本提取角色" }}
          </el-button>
          <el-button
            v-if="unsavedCharacterCount > 0"
            size="small"
            type="primary"
            :loading="savingAllCharacters"
            @click="handleSaveAllCharacters"
          >
            存入全部角色
          </el-button>
        </div>
      </div>

      <template
        v-if="
          filteredMessages.length ||
          (ai.streaming.value && (activeTab === 'script' || activeTab === 'all'))
        "
      >
        <template v-for="message in filteredMessages" :key="message.id">
          <!-- 用户指令 -->
          <div v-if="isUser(message)" class="msg-user">
            <div class="user-bubble">
              <div v-if="getUserImages(message).length > 0" class="user-bubble-images">
                <el-image
                  v-for="(img, idx) in getUserImages(message)"
                  :key="idx"
                  :src="storyFileUrl(img)"
                  :preview-src-list="getUserImages(message).map(storyFileUrl)"
                  fit="cover"
                  class="user-msg-image"
                  preview-teleported
                />
              </div>
              <div class="user-bubble-text">{{ message.content }}</div>
            </div>
            <div v-if="userParamsSummary(message)" class="user-params">
              {{ userParamsSummary(message) }}
            </div>
          </div>

          <!-- 剧本卡 -->
          <ScriptCard
            v-else-if="message.kind === 'script'"
            :message="message"
            @saved="onCardChanged"
          />

          <!-- 角色卡 -->
          <CharacterCardItem
            v-else-if="message.kind === 'character'"
            :message="message"
            :find-same-name="findSameName"
            @changed="onCardChanged"
          />

          <!-- 关键帧卡 -->
          <KeyframeCardItem
            v-else-if="message.kind === 'keyframe'"
            :message="message"
            :session-id="ai.activeSessionId.value"
            @changed="onCardChanged"
          />

          <!-- 图像卡片（立绘/关键帧/图片生成卡片） -->
          <CharacterArtCardItem
            v-else-if="message.kind === 'art'"
            :message="message"
            :session-id="ai.activeSessionId.value"
            :project-id="projectId"
            @changed="onCardChanged"
          />

          <!-- 一般回复 -->
          <div v-else class="msg-text">{{ message.content }}</div>
        </template>

        <!-- 流式中的剧本增量 -->
        <div
          v-if="ai.streaming.value && (activeTab === 'script' || activeTab === 'all')"
          class="msg-streaming"
        >
          <span class="streaming-hint">生成中…</span>
          <div class="streaming-text">{{ ai.streamText.value }}</div>
        </div>
      </template>

      <!-- 空态引导 -->
      <el-empty
        v-else-if="!ai.loadingMessages.value"
        :description="tabEmptyDescription"
        :image-size="90"
      >
        <el-button
          v-if="activeTab === 'art'"
          type="primary"
          :loading="extractingCharacters"
          @click="handleExtractCharacters"
        >
          从剧本提取角色
        </el-button>
      </el-empty>
    </div>

    <!-- 生成表单：支持剧本与立绘双模式 -->
    <AiGenerateForm
      v-model="ai.form.value"
      :styles="ai.styles.value"
      :generating="ai.streaming.value"
      :generating-art="generatingArt"
      :characters="characterOptions"
      @send="handleSend"
      @stop="ai.stop()"
      @generate-art="handleGenerateArt"
    />
  </div>
</template>

<style scoped>
.ai-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f7f8fc;
}
.drawer-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid #e5e9f2;
  background: #fff;
}
.drawer-head :deep(.el-select__wrapper) {
  border-radius: 8px !important;
}
.drawer-head :deep(.el-button) {
  border-radius: 8px !important;
}
.session-select {
  flex: 1;
  min-width: 0;
}
.option-count {
  color: #9aa4b2;
  font-size: 12px;
}

/* 分类 Tab 切换栏 */
.drawer-tabs-wrapper {
  padding: 8px 12px;
  background: #fff;
  border-bottom: 1px solid #eef2f7;
}
.tabs-segmented {
  display: flex;
  align-items: center;
  background: #f1f4fa;
  border-radius: 10px;
  padding: 3px;
  gap: 3px;
}
.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 6px 4px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 500;
  color: #64748b;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.tab-btn:hover {
  color: #1e293b;
  background: rgba(255, 255, 255, 0.6);
}
.tab-btn.active {
  background: #ffffff;
  color: #4f46e5;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
}
.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  background: #e2e8f0;
  color: #64748b;
  transition: all 0.2s;
}
.tab-btn.active .tab-badge {
  background: #eef2ff;
  color: #4f46e5;
}

/* 关键帧快捷操作横幅 */
.tab-action-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 8px 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.banner-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #166534;
}
.banner-icon {
  font-size: 14px;
}
.banner-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.art-action-banner {
  background: #f5f3ff;
  border-color: #ddd6fe;
}
.art-action-banner .banner-info {
  color: #5b21b6;
}

.message-stream {
  flex: 1;
  overflow: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg-user {
  align-self: flex-end;
  max-width: 92%;
}
.user-bubble {
  background: #526ae2;
  color: #fff;
  border-radius: 10px 10px 2px 10px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.6;
}
.user-bubble-images {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
}
.user-msg-image {
  width: 64px;
  height: 64px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(0, 0, 0, 0.1);
  cursor: pointer;
}
.user-bubble-text {
  white-space: pre-wrap;
  word-break: break-all;
}
.user-params {
  margin-top: 2px;
  text-align: right;
  font-size: 11px;
  color: #9aa4b2;
}
.msg-text {
  font-size: 13px;
  color: #4b5563;
  white-space: pre-wrap;
  word-break: break-all;
}
.msg-streaming {
  border: 1px dashed #c3cdea;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
}
.streaming-hint {
  font-size: 12px;
  color: #526ae2;
}
.streaming-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #4b5563;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 220px;
  overflow: auto;
}
</style>
