<script setup lang="ts">
/**
 * 剧本面板：多版本列表、保存新版本、切换当前版本、编辑既有版本。
 */
import { nextTick, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { projectApi, scriptApi, type StoryScriptVO } from "@/api/story";
import { formatDateTime } from "@/utils/format";
import Pagination from "@/components/ui/Pagination.vue";

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
const page = ref(1);
const size = ref(10);
const total = ref(0);

const castList = ref<Array<{ id: string; name: string }>>([]);

async function loadCast() {
  try {
    const res = await projectApi.listCasting(props.projectId);
    castList.value = (res.data ?? []).map((c) => ({ id: c.id, name: c.name }));
  } catch {
    castList.value = [];
  }
}

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
  loadCast();
});

const saveTextareaRef = ref<any>(null);
const editTextareaRef = ref<any>(null);
const POSITIONS = ["画面居中", "画面左侧", "画面右侧", "前景", "背景"];

function insertAtForm(isEdit: boolean, text: string) {
  const comp = isEdit ? editTextareaRef.value : saveTextareaRef.value;
  const targetForm = isEdit ? editForm : saveForm;
  const el = comp?.$el?.querySelector("textarea") as HTMLTextAreaElement | null;
  if (!el) {
    targetForm.content = (targetForm.content || "") + text;
    return;
  }
  const start = el.selectionStart ?? targetForm.content.length;
  const end = el.selectionEnd ?? start;
  const old = targetForm.content || "";
  targetForm.content = old.substring(0, start) + text + old.substring(end);
  const nextPos = start + text.length;
  nextTick(() => {
    el.focus();
    el.setSelectionRange(nextPos, nextPos);
  });
}

function insertCharToForm(isEdit: boolean, num: number, name?: string, pos?: string) {
  const charPart = name ? `【角色${num}·${name}】` : `【角色${num}】`;
  const text = pos ? `[${pos}]${charPart}` : charPart;
  insertAtForm(isEdit, text);
}

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
    emit("changed");
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
          <span class="content-brief">
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
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
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

    <!-- 保存新版本 -->
    <el-dialog v-model="saveVisible" title="保存新剧本版本" width="680px" append-to-body destroy-on-close>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="剧本创作规范：每集需注明预估生成秒数（建议最多15s或30s，如：第1集（预估生成时长：15秒））；镜头需标明人物画面出现位置与编号（如：[画面中央]【角色1·角色名】）。"
      />
      <el-form label-width="88px">
        <el-form-item label="版本标题">
          <el-input v-model="saveForm.title" placeholder="可选，如：第二稿" />
        </el-form-item>
        <el-form-item label="剧本内容">
          <div class="textarea-wrapper">
            <div class="character-helper-bar">
              <span class="helper-label">按编号插入人物：</span>
              <div class="helper-chips">
                <template v-if="castList.length > 0">
                  <el-dropdown
                    v-for="(c, idx) in castList"
                    :key="c.id || idx"
                    trigger="click"
                    size="small"
                  >
                    <button type="button" class="helper-btn">
                      <span class="btn-num">角色{{ idx + 1 }}</span>
                      <span>{{ c.name }}</span>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="insertCharToForm(false, idx + 1, c.name)">
                          直接插入：【角色{{ idx + 1 }}·{{ c.name }}】
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-for="pos in POSITIONS"
                          :key="pos"
                          @click="insertCharToForm(false, idx + 1, c.name, pos)"
                        >
                          [{{ pos }}]【角色{{ idx + 1 }}·{{ c.name }}】
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
                <template v-else>
                  <el-dropdown
                    v-for="num in [1, 2, 3]"
                    :key="num"
                    trigger="click"
                    size="small"
                  >
                    <button type="button" class="helper-btn">
                      <span class="btn-num">【角色{{ num }}】</span>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="insertCharToForm(false, num)">
                          直接插入：【角色{{ num }}】
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-for="pos in POSITIONS"
                          :key="pos"
                          @click="insertCharToForm(false, num, undefined, pos)"
                        >
                          [{{ pos }}]【角色{{ num }}】
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
                <span
                  v-for="pos in POSITIONS"
                  :key="pos"
                  class="helper-pos-tag"
                  @click="insertAtForm(false, `[${pos}]`)"
                >
                  {{ pos }}
                </span>
              </div>
            </div>
            <el-input
              ref="saveTextareaRef"
              v-model="saveForm.content"
              type="textarea"
              :rows="11"
              placeholder="完整剧本文本"
            />
          </div>
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
    <el-dialog
      v-model="editVisible"
      :title="`编辑 v${editing?.version ?? ''}`"
      width="680px"
      append-to-body
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="剧本创作规范：每集需注明预估生成秒数（建议最多15s或30s，如：第1集（预估生成时长：15秒））；镜头需标明人物画面出现位置与编号（如：[画面中央]【角色1·角色名】）。"
      />
      <el-form label-width="88px">
        <el-form-item label="版本标题">
          <el-input v-model="editForm.title" placeholder="可选" />
        </el-form-item>
        <el-form-item label="剧本内容">
          <div class="textarea-wrapper">
            <div class="character-helper-bar">
              <span class="helper-label">按编号插入人物：</span>
              <div class="helper-chips">
                <template v-if="castList.length > 0">
                  <el-dropdown
                    v-for="(c, idx) in castList"
                    :key="c.id || idx"
                    trigger="click"
                    size="small"
                  >
                    <button type="button" class="helper-btn">
                      <span class="btn-num">角色{{ idx + 1 }}</span>
                      <span>{{ c.name }}</span>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="insertCharToForm(true, idx + 1, c.name)">
                          直接插入：【角色{{ idx + 1 }}·{{ c.name }}】
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-for="pos in POSITIONS"
                          :key="pos"
                          @click="insertCharToForm(true, idx + 1, c.name, pos)"
                        >
                          [{{ pos }}]【角色{{ idx + 1 }}·{{ c.name }}】
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
                <template v-else>
                  <el-dropdown
                    v-for="num in [1, 2, 3]"
                    :key="num"
                    trigger="click"
                    size="small"
                  >
                    <button type="button" class="helper-btn">
                      <span class="btn-num">【角色{{ num }}】</span>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="insertCharToForm(true, num)">
                          直接插入：【角色{{ num }}】
                        </el-dropdown-item>
                        <el-dropdown-item
                          v-for="pos in POSITIONS"
                          :key="pos"
                          @click="insertCharToForm(true, num, undefined, pos)"
                        >
                          [{{ pos }}]【角色{{ num }}】
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
                <span
                  v-for="pos in POSITIONS"
                  :key="pos"
                  class="helper-pos-tag"
                  @click="insertAtForm(true, `[${pos}]`)"
                >
                  {{ pos }}
                </span>
              </div>
            </div>
            <el-input
              ref="editTextareaRef"
              v-model="editForm.content"
              type="textarea"
              :rows="11"
            />
          </div>
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
.textarea-wrapper {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.character-helper-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 4px 8px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  font-size: 12px;
}
.helper-label {
  color: #64748b;
  font-size: 11px;
}
.helper-chips {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.helper-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}
.helper-btn:hover {
  background: #eef2ff;
  border-color: #6366f1;
  color: #4f46e5;
}
.btn-num {
  font-weight: 600;
  color: #4f46e5;
}
.helper-pos-tag {
  display: inline-block;
  padding: 1px 5px;
  background: #e2e8f0;
  border-radius: 3px;
  font-size: 11px;
  color: #475569;
  cursor: pointer;
  user-select: none;
}
.helper-pos-tag:hover {
  background: #c7d2fe;
  color: #3730a3;
}
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
.panel-pagination {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}
</style>
