<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import type { KnowledgeBase } from "@/api/rag/knowledgeBase";
import { buildFolderTree, type Folder } from "@/api/rag/folders";
import { getChunkStrategyOptions } from "@/api/rag/document";
import type { DocumentUploadFormPayload } from "@/views/rag/document/types";

const props = defineProps<{
  visible: boolean;
  uploading: boolean;
  /** 固定归属的知识库（页面当前生效的 KB），弹窗内只读展示 */
  knowledgeBase: KnowledgeBase | null;
  /** 当前知识库内的文件夹列表（归属文件夹候选仅限同库） */
  folders: Folder[];
  /** 默认归属文件夹（取自左侧当前选中的文件夹） */
  defaultFolderId: string | null;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "submit", payload: DocumentUploadFormPayload): void;
}>();

const formRef = ref<FormInstance>();
const fileInput = ref<HTMLInputElement>();
const selectedFile = ref<File | null>(null);
// 有效期起止（daterange，ISO 字符串数组）；留空表示长期有效
const dateRange = ref<[string, string] | null>(null);
// 表格类：后端依据文件扩展名自动判定 doc_type，这里仅作展示，随所选文件自动勾选，不参与提交
const isSpreadsheet = ref(false);

const form = reactive({
  title: "",
  folder_id: null as string | null,
  remark: "",
  chunk_strategy: "char",
});

// 分块策略选项：直接取全局词典（chunk_strategy 类型，字典管理页维护），字典为准
const chunkStrategyOptions = computed(() => getChunkStrategyOptions());

// 归属文件夹候选树（仅当前知识库内的文件夹）
const folderTree = computed(() => buildFolderTree(props.folders));

const dialogVisible = computed({
  get: () => props.visible,
  set: (v) => emit("update:visible", v),
});

const rules: FormRules = {
  title: [{ required: true, message: "请输入手册名称", trigger: "blur" }],
};

// 弹窗打开时重置表单，默认归属当前选中的文件夹
watch(
  () => props.visible,
  (v) => {
    if (!v) return;
    form.folder_id = props.defaultFolderId;
    form.title = "";
    form.remark = "";
    form.chunk_strategy = "char";
    selectedFile.value = null;
    dateRange.value = null;
    isSpreadsheet.value = false;
    formRef.value?.clearValidate();
  }
);

const SPREADSHEET_EXT = /\.(xlsx|xls|csv)$/i;

function pickFile() {
  fileInput.value?.click();
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) {
    selectedFile.value = file;
    // 文件名缺省作为手册名称，便于用户直接提交
    if (!form.title) form.title = file.name.replace(/\.[^.]+$/, "");
    // 表格类随文件扩展名自动判定
    isSpreadsheet.value = SPREADSHEET_EXT.test(file.name);
  }
  input.value = "";
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  if (!selectedFile.value) {
    ElMessage.warning("请先选择要上传的文件");
    return;
  }
  if (!props.knowledgeBase) {
    ElMessage.warning("请先在页面选择知识库");
    return;
  }
  emit("submit", {
    file: selectedFile.value,
    knowledge_base_id: props.knowledgeBase.id,
    folder_id: form.folder_id,
    title: form.title.trim() || selectedFile.value.name,
    valid_from: dateRange.value?.[0],
    valid_until: dateRange.value?.[1],
    remark: form.remark.trim(),
    chunk_strategy: form.chunk_strategy,
  });
}
</script>

<template>
  <el-dialog v-model="dialogVisible" title="新建文档" width="620px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="文件" required>
        <div class="file-row">
          <input
            ref="fileInput"
            type="file"
            accept=".pdf,.docx,.md,.markdown,.txt,.xlsx,.xls,.csv"
            hidden
            @change="onFileChange"
          />
          <span class="file-name" :class="{ placeholder: !selectedFile }">
            {{ selectedFile ? selectedFile.name : "支持 PDF、DOCX、Markdown、Excel、TXT" }}
          </span>
          <el-button link type="primary" @click="pickFile">浏览</el-button>
        </div>
      </el-form-item>
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
      <el-form-item label="分块策略">
        <el-select v-model="form.chunk_strategy" style="width: 100%">
          <el-option
            v-for="o in chunkStrategyOptions"
            :key="o.value"
            :label="o.label"
            :value="o.value"
          />
        </el-select>
        <div class="strategy-tip">
          章节分块按标题切分（仅 Markdown、DOCX、Excel）；语义分块按内容相似度切分（所有格式）
        </div>
      </el-form-item>
      <el-form-item label="表格类">
        <!-- doc_type 由后端依据文件类型自动判定，此处随所选文件展示 -->
        <el-checkbox v-model="isSpreadsheet" disabled>是</el-checkbox>
      </el-form-item>
      <el-form-item label="AI知识库">
        <!-- 知识库固定为页面当前生效的 KB，只读展示 -->
        <el-input :model-value="knowledgeBase?.name ?? ''" disabled />
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
      <el-button type="primary" :loading="uploading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 0 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fff;
}

.file-name {
  flex: 1;
  overflow: hidden;
  color: #4d5970;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 32px;
}

.file-name.placeholder {
  color: #9aa3b5;
}

.strategy-tip {
  width: 100%;
  color: #9aa3b5;
  font-size: 12px;
  line-height: 18px;
}
</style>
