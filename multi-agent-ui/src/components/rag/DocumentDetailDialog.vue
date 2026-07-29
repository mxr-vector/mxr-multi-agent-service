<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import type { RagDocument, DocumentUpdatePayload } from "@/api/rag/document";
import { buildFolderTree, type Folder } from "@/api/rag/folders";

const props = defineProps<{
  visible: boolean;
  submitting: boolean;
  /** 当前查看的文档（打开时由父组件传入） */
  document: RagDocument | null;
  /** 所属知识库名称（只读展示） */
  knowledgeBaseName: string;
  /** 当前知识库内的文件夹列表（归属文件夹候选仅限同库） */
  folders: Folder[];
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "submit", payload: DocumentUpdatePayload): void;
}>();

const formRef = ref<FormInstance>();
// 有效期起止（daterange）；清空表示保留起始、清除截止（长期有效）
const dateRange = ref<[string, string] | null>(null);

const form = reactive({
  title: "",
  folder_id: null as string | null,
  remark: "",
});

const dialogVisible = computed({
  get: () => props.visible,
  set: (v) => emit("update:visible", v),
});

const rules: FormRules = {
  title: [{ required: true, message: "请输入手册名称", trigger: "blur" }],
};

// 归属文件夹候选树（仅当前知识库内的文件夹）
const folderTree = computed(() => buildFolderTree(props.folders));

// 状态展示：与卡片同步圆点口径一致
const STATUS_LABEL: Record<string, string> = {
  pending: "未同步",
  reindexing: "同步中",
  active: "已同步",
  failed: "同步失败",
};
const statusLabel = computed(() => STATUS_LABEL[props.document?.status ?? ""] ?? "未同步");

// 分块策略展示：structure→章节分块，char/缺省（存量文档）→通用分块
const chunkStrategyLabel = computed(() =>
  props.document?.metadata?.chunk_strategy === "structure" ? "章节分块" : "通用分块"
);

/** ISO 时间转 "YYYY-MM-DD HH:mm:ss" 展示，空值回退占位符 */
function fmtTime(v: string | null | undefined) {
  return v ? v.slice(0, 19).replace("T", " ") : "—";
}

// 弹窗打开时用当前文档回填表单
watch(
  () => props.visible,
  (v) => {
    if (!v || !props.document) return;
    const doc = props.document;
    form.title = doc.title ?? "";
    form.folder_id = doc.folder_id;
    form.remark = String(doc.metadata?.remark ?? "");
    dateRange.value = doc.valid_until
      ? [doc.valid_from.slice(0, 19), doc.valid_until.slice(0, 19)]
      : null;
    formRef.value?.clearValidate();
  }
);

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || !props.document) return;
  const payload: DocumentUpdatePayload = {
    title: form.title.trim(),
    folder_id: form.folder_id,
    // 备注并入既有 metadata，避免覆盖丢失 chunk_strategy 等键
    metadata: { ...props.document.metadata, remark: form.remark.trim() },
  };
  if (dateRange.value) {
    payload.valid_from = dateRange.value[0];
    payload.valid_until = dateRange.value[1];
  } else if (props.document.valid_until) {
    // 原有截止时间被清空：显式置 null 转为长期有效（valid_from 保留不动）
    payload.valid_until = null;
  }
  emit("submit", payload);
}
</script>

<template>
  <el-dialog v-model="dialogVisible" title="文档详情" width="620px">
    <!-- 只读信息区：来源/状态/版本等不可编辑字段 -->
    <el-descriptions :column="2" size="small" border class="detail-meta">
      <el-descriptions-item label="AI知识库">{{ knowledgeBaseName || "—" }}</el-descriptions-item>
      <el-descriptions-item label="同步状态">{{ statusLabel }}</el-descriptions-item>
      <el-descriptions-item label="文档类型">{{ document?.doc_type ?? "—" }}</el-descriptions-item>
      <el-descriptions-item label="分块策略">{{ chunkStrategyLabel }}</el-descriptions-item>
      <el-descriptions-item label="版本">v{{ document?.version ?? 1 }}</el-descriptions-item>
      <el-descriptions-item label="来源">{{ document?.source_uri ?? "—" }}</el-descriptions-item>
      <el-descriptions-item label="创建时间">
        {{ fmtTime(document?.created_at) }}
      </el-descriptions-item>
      <el-descriptions-item label="更新时间">
        {{ fmtTime(document?.updated_at) }}
      </el-descriptions-item>
    </el-descriptions>

    <!-- 可编辑区：仅元数据（标题/文件夹/有效期/备注），不触碰内容与状态 -->
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="手册名称" prop="title">
        <el-input
          v-model="form.title"
          placeholder="请输入手册名称"
          maxlength="50"
          show-word-limit
        />
      </el-form-item>
      <el-form-item label="有效期">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DDTHH:mm:ss"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="归属文件夹">
        <el-tree-select
          v-model="form.folder_id"
          :data="folderTree"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          value-key="id"
          check-strictly
          clearable
          placeholder="根目录"
          :render-after-expand="false"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="备注">
        <el-input
          v-model="form.remark"
          type="textarea"
          :rows="4"
          placeholder="选填"
          maxlength="500"
          show-word-limit
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.detail-meta {
  margin-bottom: 18px;
}
</style>
