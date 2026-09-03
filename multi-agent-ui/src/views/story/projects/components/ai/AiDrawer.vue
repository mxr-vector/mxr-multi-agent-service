<script setup lang="ts">
/**
 * AI 创作抽屉（右栏常驻可收起）：会话管理 + 消息流回放 + 流式生成。
 *
 * 状态与编排收口在 useStoryAi 组合式函数；卡片渲染委托给 ScriptCard /
 * CharacterCardItem；art 消息（图片/失败）为单块简单呈现，内联渲染。
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { characterApi, storyFileUrl, type StoryMessageVO } from "@/api/story";
import { useStoryAi } from "../../composables/useStoryAi";
import AiGenerateForm from "./AiGenerateForm.vue";
import ScriptCard from "./ScriptCard.vue";
import CharacterCardItem from "./CharacterCardItem.vue";

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

onMounted(() => {
  ai.init();
});

/** 产物变更后：刷新会话消息 + 通知父级刷新项目 */
async function onCardChanged() {
  await ai.refresh();
  emit("changed");
}

// 消息流/流式文本变化时滚动到底部
const streamRef = ref<HTMLElement | null>(null);
watch(
  () => [ai.messages.value.length, ai.streamText.value],
  async () => {
    await nextTick();
    streamRef.value?.scrollTo({ top: streamRef.value.scrollHeight });
  }
);

async function handleCreateSession() {
  const name = await promptSessionTitle();
  await ai.createSession(name ?? undefined);
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
}

function isUser(message: StoryMessageVO) {
  return message.role === "user";
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
        @change="(id: string) => ai.switchSession(id)"
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

    <!-- 消息流 -->
    <div ref="streamRef" v-loading="ai.loadingMessages.value" class="message-stream">
      <template v-if="ai.messages.value.length">
        <template v-for="message in ai.messages.value" :key="message.id">
          <!-- 用户指令 -->
          <div v-if="isUser(message)" class="msg-user">
            <div class="user-bubble">{{ message.content }}</div>
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

          <!-- 立绘消息：图片预览或失败提示 -->
          <div v-else-if="message.kind === 'art'" class="msg-art">
            <template v-if="message.status === 'done' && message.image_file">
              <el-image
                :src="storyFileUrl(message.image_file)"
                :preview-src-list="[storyFileUrl(message.image_file)]"
                fit="contain"
                class="art-image"
              />
              <div class="art-caption">{{ message.content }}（已生成，随角色卡"存入角色库"收编）</div>
            </template>
            <el-alert
              v-else-if="message.status === 'failed'"
              type="error"
              :title="`${message.content}失败`"
              :description="message.error ?? undefined"
              :closable="false"
            />
          </div>

          <!-- 一般回复 -->
          <div v-else class="msg-text">{{ message.content }}</div>
        </template>

        <!-- 流式中的剧本增量 -->
        <div v-if="ai.streaming.value" class="msg-streaming">
          <span class="streaming-hint">生成中…</span>
          <div class="streaming-text">{{ ai.streamText.value }}</div>
        </div>
      </template>

      <!-- 空态引导 -->
      <el-empty
        v-else-if="!ai.loadingMessages.value"
        description="向 AI 描述你的故事，生成剧本与角色卡"
        :image-size="90"
      />
    </div>

    <!-- 生成表单 -->
    <AiGenerateForm v-model="ai.form.value" :styles="ai.styles.value" :generating="ai.streaming.value" @send="ai.send(() => emit('changed'))" @stop="ai.stop()" />
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
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e9f2;
  background: #fff;
}
.session-select {
  flex: 1;
  min-width: 0;
}
.option-count {
  color: #9aa4b2;
  font-size: 12px;
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
  white-space: pre-wrap;
  word-break: break-all;
}
.user-params {
  margin-top: 2px;
  text-align: right;
  font-size: 11px;
  color: #9aa4b2;
}
.msg-art {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  padding: 10px;
}
.art-image {
  width: 100%;
  max-height: 260px;
  border-radius: 8px;
}
.art-caption {
  margin-top: 6px;
  font-size: 11px;
  color: #7d879a;
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
