<script setup lang="ts">
/**
 * 剧本卡：AI 生成剧本消息的预览、复制全文与"存为版本"沉淀。
 */
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { storyAiApi, type StoryMessageVO } from "@/api/story";

const props = defineProps<{
  message: StoryMessageVO;
}>();

const emit = defineEmits<{
  (e: "saved"): void;
}>();

const previewVisible = ref(false);
const saveVisible = ref(false);
const saveTitle = ref("");
const saveCurrent = ref(false);
const saving = ref(false);

async function copyContent() {
  await navigator.clipboard.writeText(props.message.content ?? "");
  ElMessage.success("剧本全文已复制");
}

async function handleSave() {
  saving.value = true;
  try {
    const res = await storyAiApi.saveScript(props.message.id, saveTitle.value.trim() || undefined, saveCurrent.value);
    const version = (res.data as Record<string, unknown> | null)?.version;
    ElMessage.success(`已存为剧本 v${version ?? ""}（${saveCurrent.value ? "并设为当前" : "未设当前"}）`);
    saveVisible.value = false;
    emit("saved");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="script-card">
    <div class="card-head">
      <span class="card-title">📜 剧本</span>
      <el-tag v-if="message.status === 'stopped'" size="small" type="warning">已停止</el-tag>
      <el-tag v-else-if="message.status === 'failed'" size="small" type="danger">生成失败</el-tag>
    </div>
    <!-- 失败终态须可见错误原因（spec"生成失败不污染会话"场景） -->
    <el-alert
      v-if="message.status === 'failed'"
      type="error"
      :title="message.content ? '剧本生成失败（以下为已产出的部分内容）' : '剧本生成失败，请重试'"
      :description="message.error ?? undefined"
      :closable="false"
    />
    <div v-if="message.content" class="card-body">{{ message.content.slice(0, 160) }}{{ message.content.length > 160 ? "…" : "" }}</div>
    <div class="card-actions">
      <template v-if="message.status !== 'failed'">
        <el-button size="small" link type="primary" @click="previewVisible = true">预览全文</el-button>
        <el-button size="small" link @click="copyContent">复制全文</el-button>
        <el-button
          v-if="message.status === 'done'"
          size="small"
          link
          type="primary"
          @click="saveVisible = true"
        >
          存为版本
        </el-button>
      </template>
    </div>

    <el-dialog v-model="previewVisible" title="剧本全文" width="720px" destroy-on-close>
      <div class="preview-content">{{ message.content }}</div>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
        <el-button type="primary" @click="copyContent">复制全文</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="saveVisible" title="存为剧本版本" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="版本标题">
          <el-input v-model="saveTitle" placeholder="可选，如：AI 初稿" />
        </el-form-item>
        <el-form-item label="设为当前">
          <el-switch v-model="saveCurrent" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.script-card {
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
.card-body {
  margin-top: 6px;
  font-size: 12px;
  color: #4b5563;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.card-actions {
  margin-top: 8px;
  display: flex;
  gap: 2px;
}
.preview-content {
  max-height: 60vh;
  overflow: auto;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-all;
  color: #1f2d3d;
}
</style>
