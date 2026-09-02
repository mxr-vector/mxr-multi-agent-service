<script setup lang="ts">
/**
 * 导出包面板：统一格式（角色+剧本+关键帧）快照生成、历史列表、复制文本。
 */
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { exportApi, type StoryExportPackageVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";

const props = defineProps<{
  projectId: string;
}>();

const loading = ref(false);
const list = ref<StoryExportPackageVO[]>([]);

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
const createForm = reactive({ name: "", target_platform: "" });

function openCreate() {
  Object.assign(createForm, { name: "", target_platform: "" });
  createVisible.value = true;
}

async function handleCreate() {
  creating.value = true;
  try {
    await exportApi.create(props.projectId, {
      name: createForm.name.trim() || undefined,
      target_platform: createForm.target_platform.trim() || undefined,
    });
    ElMessage.success("导出包已生成");
    createVisible.value = false;
    await loadExports();
  } finally {
    creating.value = false;
  }
}

// —— 查看/复制 ——
const viewVisible = ref(false);
const viewing = ref<StoryExportPackageVO | null>(null);

function openView(pkg: StoryExportPackageVO) {
  viewing.value = pkg;
  viewVisible.value = true;
}

async function handleCopy(pkg: StoryExportPackageVO) {
  const text = pkg.copy_text ?? pkg.prompt_text;
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制到剪贴板");
  } catch {
    ElMessage.error("复制失败，请在查看弹窗中手动选择复制");
  }
}
</script>

<template>
  <div class="export-panel">
    <div class="panel-toolbar">
      <span class="panel-hint">
        统一装配「当前剧本 + 出演角色 + 被选关键帧」，生成后可直接复制到外部视频生成网站；历史包为不可变快照。
      </span>
      <el-button type="primary" @click="openCreate">生成导出包</el-button>
    </div>

    <el-table v-loading="loading" :data="list" stripe>
      <el-table-column label="版本" prop="version" width="80">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="名称" prop="name" min-width="180" />
      <el-table-column label="平台备注" min-width="120">
        <template #default="{ row }">{{ row.target_platform || "—" }}</template>
      </el-table-column>
      <el-table-column label="生成时间" width="160">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button size="small" link @click="openView(row)">查看</el-button>
          <el-button size="small" link type="primary" @click="handleCopy(row)">一键复制</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有导出包" :image-size="80" />
      </template>
    </el-table>

    <!-- 生成 -->
    <el-dialog v-model="createVisible" title="生成导出包" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="缺省自动生成" />
        </el-form-item>
        <el-form-item label="平台备注">
          <el-input v-model="createForm.target_platform" placeholder="如：可灵 / 即梦（仅备注）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">生成</el-button>
      </template>
    </el-dialog>

    <!-- 查看 -->
    <el-dialog v-model="viewVisible" :title="viewing?.name ?? '导出包'" width="760px" destroy-on-close>
      <div class="view-actions">
        <el-button type="primary" size="small" @click="viewing && handleCopy(viewing)">一键复制</el-button>
      </div>
      <pre class="export-text">{{ viewing?.prompt_text ?? "" }}</pre>
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
}
.view-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}
.export-text {
  max-height: 420px;
  overflow: auto;
  padding: 12px;
  background: #f7f8fc;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
