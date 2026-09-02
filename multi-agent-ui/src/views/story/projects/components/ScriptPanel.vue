<script setup lang="ts">
/**
 * 剧本面板：多版本列表、保存新版本、切换当前版本、编辑既有版本。
 */
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { scriptApi, type StoryScriptVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const SOURCE_LABEL: Record<string, string> = {
  ai: "AI 生成",
  user: "手动编辑",
  upload: "上传",
};

const loading = ref(false);
const list = ref<StoryScriptVO[]>([]);

async function loadScripts() {
  loading.value = true;
  try {
    const res = await scriptApi.list(props.projectId, { page: 1, size: 100 });
    list.value = res.data?.items ?? [];
  } finally {
    loading.value = false;
  }
}

onMounted(loadScripts);

// —— 保存新版本 ——
const saveVisible = ref(false);
const saveSubmitting = ref(false);
const saveForm = reactive({
  content: "",
  title: "",
  set_current: true,
});

function openSave() {
  Object.assign(saveForm, { content: "", title: "", set_current: true });
  saveVisible.value = true;
}

async function handleSave() {
  if (!saveForm.content.trim()) {
    ElMessage.error("剧本内容不能为空");
    return;
  }
  saveSubmitting.value = true;
  try {
    await scriptApi.save(props.projectId, {
      content: saveForm.content.trim(),
      title: saveForm.title.trim() || null,
      source: "user",
      set_current: saveForm.set_current,
    });
    ElMessage.success("新版本已保存");
    saveVisible.value = false;
    await loadScripts();
    emit("changed");
  } finally {
    saveSubmitting.value = false;
  }
}

// —— 切换当前版本 ——
async function handleSwitch(script: StoryScriptVO) {
  await scriptApi.switchCurrent(script.id);
  ElMessage.success(`已切换到 v${script.version}`);
  await loadScripts();
  emit("changed");
}

// —— 编辑既有版本 ——
const editVisible = ref(false);
const editSubmitting = ref(false);
const editing = ref<StoryScriptVO | null>(null);
const editForm = reactive({ content: "", title: "" });

function openEdit(script: StoryScriptVO) {
  editing.value = script;
  Object.assign(editForm, { content: script.content, title: script.title ?? "" });
  editVisible.value = true;
}

async function handleEdit() {
  if (!editing.value) return;
  if (!editForm.content.trim()) {
    ElMessage.error("剧本内容不能为空");
    return;
  }
  editSubmitting.value = true;
  try {
    await scriptApi.update(editing.value.id, {
      content: editForm.content.trim(),
      title: editForm.title.trim() || null,
    });
    ElMessage.success("剧本已更新");
    editVisible.value = false;
    await loadScripts();
  } finally {
    editSubmitting.value = false;
  }
}
</script>

<template>
  <div class="script-panel">
    <div class="panel-toolbar">
      <span class="panel-hint">多版本并存，当前版本是导出的唯一事实来源。</span>
      <el-button type="primary" @click="openSave">保存新版本</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column label="版本" width="90">
        <template #default="{ row }">
          v{{ row.version }}
          <el-tag v-if="row.is_current" size="small" type="success">当前</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="标题" prop="title" min-width="140">
        <template #default="{ row }">{{ row.title || "—" }}</template>
      </el-table-column>
      <el-table-column label="来源" width="110">
        <template #default="{ row }">{{ SOURCE_LABEL[row.source] ?? row.source }}</template>
      </el-table-column>
      <el-table-column label="内容摘要" min-width="220">
        <template #default="{ row }">
          <span class="content-brief">{{ row.content.slice(0, 60) }}{{ row.content.length > 60 ? "…" : "" }}</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button v-if="!row.is_current" size="small" link @click="handleSwitch(row)">设为当前</el-button>
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有剧本版本" :image-size="80" />
      </template>
    </el-table>

    <!-- 保存新版本 -->
    <el-dialog v-model="saveVisible" title="保存新剧本版本" width="680px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="版本标题">
          <el-input v-model="saveForm.title" placeholder="可选，如：第二稿" />
        </el-form-item>
        <el-form-item label="剧本内容">
          <el-input v-model="saveForm.content" type="textarea" :rows="10" placeholder="完整剧本文本" />
        </el-form-item>
        <el-form-item label="设为当前">
          <el-switch v-model="saveForm.set_current" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveVisible = false">取消</el-button>
        <el-button type="primary" :loading="saveSubmitting" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑既有版本 -->
    <el-dialog v-model="editVisible" :title="`编辑 v${editing?.version ?? ''}`" width="680px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="版本标题">
          <el-input v-model="editForm.title" placeholder="可选" />
        </el-form-item>
        <el-form-item label="剧本内容">
          <el-input v-model="editForm.content" type="textarea" :rows="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.panel-hint {
  font-size: 12px;
  color: #7d879a;
}
.content-brief {
  color: #4b5563;
}
</style>
