<script setup lang="ts">
/**
 * 剧本面板：多版本列表、保存新版本、切换当前版本、编辑既有版本。
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { scriptApi, type StoryScriptVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";
import Pagination from "@/components/ui/Pagination.vue";

const props = defineProps<{
  projectId: string;
}>();

const emit = defineEmits<{
  (e: "changed"): void;
}>();

const router = useRouter();

const SOURCE_LABEL: Record<string, string> = {
  ai: "AI 生成",
  user: "手动编辑",
  upload: "上传",
};

const loading = ref(false);
const list = ref<StoryScriptVO[]>([]);
const page = ref(1);
const size = ref(10);
const total = ref(0);

async function loadScripts() {
  loading.value = true;
  try {
    const res = await scriptApi.list(props.projectId, { page: page.value, size: size.value });
    list.value = res.data?.items ?? [];
    total.value = res.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadScripts();
});

// —— 跳转独立剧本编辑页面 ——
function openSave() {
  router.push(`/story/projects/${props.projectId}/script-edit`);
}

function openEdit(script: StoryScriptVO) {
  router.push({
    path: `/story/projects/${props.projectId}/script-edit`,
    query: { scriptId: script.id },
  });
}

// —— 切换当前版本 ——
async function handleSwitch(script: StoryScriptVO) {
  await scriptApi.switchCurrent(script.id);
  ElMessage.success(`已切换到 v${script.version}`);
  await loadScripts();
  emit("changed");
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
      <el-table-column label="内容摘要" min-width="240">
        <template #default="{ row }">
          <span class="content-brief clickable-brief" title="点击新页面编辑与查看完整剧本" @click="openEdit(row)">
            {{ row.content.slice(0, 60) }}{{ row.content.length > 60 ? "…" : "" }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button v-if="!row.is_current" size="small" link @click="handleSwitch(row)">
            设为当前
          </el-button>
          <el-button size="small" link type="primary" @click="openEdit(row)">编辑/浏览</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有剧本版本" :image-size="80" />
      </template>
    </el-table>

    <div v-if="total > 0" class="panel-pagination">
      <Pagination
        v-model:page="page"
        v-model:size="size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        @change="loadScripts"
      />
    </div>
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
.clickable-brief {
  cursor: pointer;
  transition: color 0.15s;
}
.clickable-brief:hover {
  color: #409eff;
  text-decoration: underline;
}
.panel-pagination {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
</style>
