<script setup lang="ts">
/**
 * 角色卡：AI 生成角色的判定/编辑与立绘双通道（外部出图回传 / 内部生成），
 * 以及"存入角色库"沉淀（同名角色提示新建或并入）。
 */
import { computed, onBeforeUnmount, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  storyAiApi,
  type StoryCharacterCard,
  type StoryGenerationTaskVO,
  type StoryMessageVO,
} from "@/api/story";
import { readCard } from "../../composables/useStoryAi";

const props = defineProps<{
  message: StoryMessageVO;
  /** 同名角色检测（延迟调用，返回库内同名角色或 null） */
  findSameName: (name: string) => Promise<{ id: string; name: string } | null>;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const card = computed<StoryCharacterCard | null>(() => readCard(props.message));
/** 已沉淀标记（幂等：卡片只能沉淀一次） */
const sedimentedId = computed(() => {
  const id = (props.message.params ?? {})["sedimented_character_id"];
  return typeof id === "string" ? id : "";
});

/** 人设键值摘要展示（profile 为结构化 JSONB：性格/身份/背景等） */
const profileSummary = computed(() => {
  if (!card.value?.profile) return "";
  return Object.entries(card.value.profile)
    .map(([key, value]) => `${key}：${String(value)}`)
    .join("；");
});

// ---------- 编辑 ----------
const editVisible = ref(false);
const editSaving = ref(false);
const editForm = ref<StoryCharacterCard>({
  name: "",
  role_type: null,
  profile: {},
  visual_profile: {},
  appearance_prompt: null,
  art_prompt: null,
  negative_prompt: null,
});
/** 结构化字段以 JSON 文本编辑（人设/视觉形象为键值对象） */
const profileText = ref("{}");
const visualProfileText = ref("{}");

function openEdit() {
  if (!card.value) return;
  editForm.value = { ...card.value };
  profileText.value = JSON.stringify(card.value.profile ?? {}, null, 2);
  visualProfileText.value = JSON.stringify(card.value.visual_profile ?? {}, null, 2);
  editVisible.value = true;
}

/** JSON 文本 -> 对象；非法时提示并返回 null */
function parseJsonObject(text: string, label: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text || "{}") as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new TypeError("not an object");
    }
    return parsed as Record<string, unknown>;
  } catch {
    ElMessage.error(`${label} 须为合法的 JSON 对象`);
    return null;
  }
}

async function handleEditSave() {
  if (!editForm.value.name?.trim()) {
    ElMessage.error("角色名不能为空");
    return;
  }
  const profile = parseJsonObject(profileText.value, "人设");
  if (profile === null) return;
  const visualProfile = parseJsonObject(visualProfileText.value, "视觉形象");
  if (visualProfile === null) return;
  editSaving.value = true;
  try {
    await storyAiApi.editCard(props.message.id, {
      name: editForm.value.name.trim(),
      role_type: editForm.value.role_type,
      profile,
      visual_profile: visualProfile,
      appearance_prompt: editForm.value.appearance_prompt,
      art_prompt: editForm.value.art_prompt,
      negative_prompt: editForm.value.negative_prompt,
    });
    ElMessage.success("角色卡已更新");
    editVisible.value = false;
    emit("changed");
  } finally {
    editSaving.value = false;
  }
}

// ---------- 出图提示词复制（外部出图通道） ----------
async function copyArtPrompt() {
  if (!card.value?.art_prompt) return;
  await navigator.clipboard.writeText(card.value.art_prompt);
  ElMessage.success("出图提示词已复制，可粘贴到外部绘图工具出图后回传上传");
}

// ---------- 内部生成立绘（任务轮询） ----------
const artTask = ref<StoryGenerationTaskVO | null>(null);
let pollTimer: ReturnType<typeof setTimeout> | null = null;
/** 组件已卸载标记：轮询续体不得再发请求/触发 emit */
let disposed = false;
const POLL_INTERVAL_MS = 2500;
/** 轮询最大次数（超出提示稍后查看任务列表，防无限循环） */
const POLL_MAX_ATTEMPTS = 40;
let pollAttempts = 0;

async function generateArt() {
  try {
    const res = await storyAiApi.generateArt(props.message.id);
    artTask.value = res.data;
    pollAttempts = 0;
    pollTask();
  } catch {
    // 后端错误已由响应拦截器统一提示
  }
}

function pollTask() {
  if (disposed) return;
  pollTimer = setTimeout(async () => {
    if (disposed || !artTask.value) return;
    if (pollAttempts++ >= POLL_MAX_ATTEMPTS) {
      ElMessage.warning("立绘任务查询超时，请稍后在任务列表查看结果");
      return;
    }
    try {
      const res = await storyAiApi.task(artTask.value.id);
      if (disposed) return;
      artTask.value = res.data;
      if (["succeeded", "failed", "cancelled"].includes(res.data.status)) {
        if (res.data.status === "succeeded") {
          ElMessage.success("立绘生成完成");
          emit("changed");
        } else {
          ElMessage.error(`立绘生成失败：${res.data.error_message ?? "未知原因"}`);
        }
        return;
      }
      pollTask();
    } catch {
      pollTask();
    }
  }, POLL_INTERVAL_MS);
}

onBeforeUnmount(() => {
  disposed = true;
  if (pollTimer) clearTimeout(pollTimer);
});

// ---------- 存入角色库（同名提示新建/并入） ----------
const saving = ref(false);

async function saveToLibrary() {
  if (!card.value) return;
  const sameName = await props.findSameName(card.value.name);
  let mode: "new" | "merge" = "new";
  let characterId: string | undefined;
  if (sameName) {
    try {
      await ElMessageBox.confirm(
        `角色库中已存在同名角色「${sameName.name}」。选择"并入"将作为其新增立绘（不改人设），选择"新建"将创建独立角色。`,
        "同名角色",
        {
          confirmButtonText: "并入既有角色",
          cancelButtonText: "新建角色",
          distinguishCancelAndClose: true,
          type: "warning",
        }
      );
      mode = "merge";
      characterId = sameName.id;
    } catch (action) {
      // close/ESC = 放弃沉淀；仅显式点"新建角色"才走 new 分支
      if (action !== "cancel") return;
      mode = "new";
    }
  }
  saving.value = true;
  try {
    const res = await storyAiApi.saveCharacter(props.message.id, mode, characterId);
    ElMessage.success(
      `已存入角色库（立绘收编 ${res.data.saved_art_count} 张${res.data.casting_added ? "，已登记出演本项目" : ""}）`
    );
    emit("changed");
  } finally {
    saving.value = false;
  }
}

/** 角色类型展示名 */
const ROLE_LABEL: Record<string, string> = {
  protagonist: "主角",
  supporting: "配角",
  antagonist: "反派",
  npc: "NPC",
  other: "其他",
};
</script>

<template>
  <div v-if="card" class="character-card">
    <div class="card-head">
      <span class="card-title">👤 {{ card.name }}</span>
      <el-tag v-if="card.role_type" size="small" type="info">
        {{ ROLE_LABEL[card.role_type] ?? card.role_type }}
      </el-tag>
      <el-tag v-if="sedimentedId" size="small" type="success">已入库</el-tag>
    </div>
    <div v-if="profileSummary" class="card-line">
      <span class="line-label">人设：</span>{{ profileSummary }}
    </div>
    <div v-if="card.visual_profile && Object.keys(card.visual_profile).length" class="card-line">
      <span class="line-label">视觉：</span>{{ Object.values(card.visual_profile).join(" / ") }}
    </div>
    <div v-if="card.appearance_prompt" class="card-line">
      <span class="line-label">外观：</span>{{ card.appearance_prompt }}
    </div>
    <div v-if="card.art_prompt" class="card-line prompt-line">
      <span class="line-label">出图提示词：</span>{{ card.art_prompt }}
    </div>

    <div class="card-actions">
      <el-button size="small" link type="primary" @click="copyArtPrompt">复制出图提示词</el-button>
      <el-button size="small" link @click="openEdit">编辑</el-button>
      <el-button size="small" link :loading="!!artTask && artTask.status === 'generating'" @click="generateArt">
        生成立绘
      </el-button>
      <el-button
        v-if="!sedimentedId"
        size="small"
        link
        type="primary"
        :loading="saving"
        @click="saveToLibrary"
      >
        存入角色库
      </el-button>
    </div>

    <el-dialog v-model="editVisible" title="编辑角色卡" width="560px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="角色名">
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="人设">
          <el-input v-model="profileText" type="textarea" :rows="4" placeholder="JSON 对象，如 {性格：勇敢}" />
        </el-form-item>
        <el-form-item label="视觉形象">
          <el-input v-model="visualProfileText" type="textarea" :rows="4" placeholder="JSON 对象，如 {发型：长发}" />
        </el-form-item>
        <el-form-item label="外观描述">
          <el-input v-model="editForm.appearance_prompt" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="出图提示词">
          <el-input v-model="editForm.art_prompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="负向提示词">
          <el-input v-model="editForm.negative_prompt" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="handleEditSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.character-card {
  border: 1px solid #e5e9f2;
  border-radius: 10px;
  background: #fff;
  padding: 10px 12px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
}
.card-line {
  margin-top: 6px;
  font-size: 12px;
  color: #4b5563;
  line-height: 1.6;
  word-break: break-all;
}
.prompt-line .line-label + * {
  color: #7d879a;
}
.line-label {
  color: #9aa4b2;
}
.card-actions {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
</style>
