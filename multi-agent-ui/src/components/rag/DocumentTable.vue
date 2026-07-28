<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { documentApi, type RagDocument, type DocumentUpdatePayload } from "@/api/rag/document";
import type { KnowledgeBase } from "@/api/rag/knowledgeBase";
import { folderApi, type Folder } from "@/api/rag/folders";
import { confirmDanger } from "@/utils/confirm";
import { useUserStore } from "@/stores/userStore";
import DocumentCard from "@/components/rag/DocumentCard.vue";
import DocumentChunkTree from "@/components/rag/DocumentChunkTree.vue";
import DocumentDetailDialog from "@/components/rag/DocumentDetailDialog.vue";
import DocumentUploadDialog from "@/components/rag/DocumentUploadDialog.vue";
import FolderFormDialog from "@/components/rag/FolderFormDialog.vue";
import KnowledgeTree from "@/components/rag/KnowledgeTree.vue";
import DeptTreePanel from "@/components/DeptTreePanel.vue";
import type { Dept } from "@/api/system/dept";
import Pagination from "@/components/Pagination.vue";
import SvgIcon from "@/components/SvgIcon.vue";
import type { FolderFormPayload, DocumentUploadFormPayload } from "@/components/rag/types";

// —— 顶部同步状态图例（与 DocumentCard 圆点保持一致）——
const syncLegend = [
    { label: "未同步", cls: "pending" },
    { label: "同步中", cls: "syncing" },
    { label: "已同步", cls: "synced" },
    { label: "同步失败", cls: "failed" },
];

// —— 部门树筛选：通用 DeptTreePanel，仅 data_scope=all 渲染（其余档位后端强制边界）——
// 部门选中驱动文档列表的 dept_ids 过滤，并联动知识库树按同一部门边界重载；
// showDeptTree 用 computed：store 已缓存 data_scope 时同步渲染，
// 避免每次进入页面都等 /auth/me 返回后才异步插入树（概率性闪现/缺失）
const userStore = useUserStore();
const showDeptTree = computed(() => userStore.dataScope === "all");
const deptFilterIds = ref<string[] | null>(null);
// 部门树当前选中的节点（上传文档时作为归属部门）
const selectedDept = ref<Dept | null>(null);

function onDeptSelect(deptIds: string[] | null, dept: Dept | null) {
    selectedDept.value = dept;
    // 重复点击同一部门（子树集合不变）时跳过，避免整链路无谓重刷
    if (sameIdSet(deptIds, deptFilterIds.value)) return;
    deptFilterIds.value = deptIds;
    page.value = 1;
    // 文档重拉统一由 KnowledgeTree 重载后 emit select 驱动（onTreeSelect 消费
    // pendingDeptReload），列表为空时走 @cleared 清空——不在此处直接重查，
    // 避免「旧知识库 + 新部门」的一次多余请求
    pendingDeptReload = true;
}

/** 比较两个部门 id 集合是否等价（均为子树展开集，忽略顺序） */
function sameIdSet(a: string[] | null, b: string[] | null) {
    if (a === b) return true;
    if (!a || !b || a.length !== b.length) return false;
    const set = new Set(b);
    return a.every((id) => set.has(id));
}

// 部门边界变化后的待重拉标记：树重载会重新 emit select，
// 即便选中的仍是同一知识库，也需按新 dept_ids 补拉一次文档
let pendingDeptReload = false;

onMounted(() => {
    // data_scope 懒加载（登录响应不含），showDeptTree 由 computed 响应式跟随；
    // /auth/me 失败不阻断页面主体，仅部门树入口缺失
    userStore.ensureDataScope().catch(() => { });
});

// —— 数据源 ——
// 知识库与文件夹的加载全部封装在左侧 KnowledgeTree 中（懒加载），
// 本组件只持有「当前选中的知识库对象」与「该知识库的扁平文件夹列表」。
const loading = ref(false);
const uploading = ref(false);
const vectorizingId = ref<string | null>(null);
const allDocuments = ref<RagDocument[]>([]);
const activeKb = ref<KnowledgeBase | null>(null);
const folders = ref<Folder[]>([]);

const knowledgeTreeRef = ref<InstanceType<typeof KnowledgeTree>>();
const selectedFolderId = ref<string | null>(null);

// —— 文件夹导航：前进/后退历史 + 面包屑 ——
const history = ref<(string | null)[]>([null]);
const histIndex = ref(0);
const canBack = computed(() => histIndex.value > 0);
const canForward = computed(() => histIndex.value < history.value.length - 1);

function selectFolder(id: string | null, pushHistory = true) {
    selectedFolderId.value = id;
    page.value = 1;
    if (pushHistory) {
        history.value = history.value.slice(0, histIndex.value + 1);
        history.value.push(id);
        histIndex.value = history.value.length - 1;
    }
    // 根目录时高亮回知识库节点本身
    nextTick(() => knowledgeTreeRef.value?.setCurrentKey(id ?? activeKb.value?.id ?? null));
}
function goBack() {
    if (!canBack.value) return;
    histIndex.value -= 1;
    selectFolder(history.value[histIndex.value], false);
}
function goForward() {
    if (!canForward.value) return;
    histIndex.value += 1;
    selectFolder(history.value[histIndex.value], false);
}
function goUp() {
    const cur = folders.value.find((f) => f.id === selectedFolderId.value);
    selectFolder(cur?.parent_id ?? null);
}
// 知识库切换时重置文件夹导航：选中态、前进/后退历史与面包屑回到根目录
function resetFolderNav() {
    selectedFolderId.value = null;
    history.value = [null];
    histIndex.value = 0;
}

// 面包屑：知识库（根） → …祖先链 → 当前文件夹
const breadcrumb = computed(() => {
    const path: { id: string | null; name: string }[] = [
        { id: null, name: activeKb.value?.name ?? "根目录" },
    ];
    if (selectedFolderId.value) {
        const byId = new Map(folders.value.map((f) => [f.id, f]));
        const chain: Folder[] = [];
        let cur = byId.get(selectedFolderId.value);
        while (cur) {
            chain.unshift(cur);
            cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
        }
        for (const c of chain) path.push({ id: c.id, name: c.name });
    }
    return path;
});

// —— 筛选表单：草稿（编辑中）与已应用（生效）分离，点击「搜索」才提交 ——
type FilterState = {
    keyword: string;
    dateRange: [string, string] | null;
    tableType: "" | "yes" | "no";
    remark: string;
};
function emptyFilter(): FilterState {
    return { keyword: "", dateRange: null, tableType: "", remark: "" };
}
const draft = reactive<FilterState>(emptyFilter());
const applied = reactive<FilterState>(emptyFilter());
const tableTypeOptions = [
    { label: "全部", value: "" },
    { label: "是", value: "yes" },
    { label: "否", value: "no" },
];
// 表格类判定：doc_type 命中电子表格类扩展视为「表格类」
const SPREADSHEET = new Set(["excel", "xlsx", "xls"]);
function isSpreadsheet(doc: RagDocument) {
    return SPREADSHEET.has((doc.doc_type ?? "").toLowerCase());
}

// —— 分页（本视图为客户端分页：后端 list 仅支持按知识库分页，
//     文件夹/多字段筛选在前端对当前知识库全量数据上完成）——
const page = ref(1);
const size = ref(12);

// 过滤链：文件夹 → 手册名称 → 生效时间 → 表格类 → 备注
const filteredDocuments = computed(() => {
    const kw = applied.keyword.trim().toLowerCase();
    const remark = applied.remark.trim().toLowerCase();
    const [from, to] = applied.dateRange ?? [null, null];
    return allDocuments.value.filter((doc) => {
        if (selectedFolderId.value && doc.folder_id !== selectedFolderId.value) return false;
        if (kw) {
            const name = (doc.title || doc.source_uri || "").toLowerCase();
            if (!name.includes(kw)) return false;
        }
        if (applied.tableType === "yes" && !isSpreadsheet(doc)) return false;
        if (applied.tableType === "no" && isSpreadsheet(doc)) return false;
        if (from && to && doc.valid_from) {
            const t = doc.valid_from.slice(0, 10);
            if (t < from.slice(0, 10) || t > to.slice(0, 10)) return false;
        }
        if (remark) {
            const r = String(doc.metadata?.remark ?? "").toLowerCase();
            if (!r.includes(remark)) return false;
        }
        return true;
    });
});
const total = computed(() => filteredDocuments.value.length);
const pagedDocuments = computed(() => {
    const start = (page.value - 1) * size.value;
    return filteredDocuments.value.slice(start, start + size.value);
});

// —— 加载 ——
// 未选择知识库时禁用新建文件/文件夹等操作
const hasKb = computed(() => Boolean(activeKb.value));

async function loadDocuments() {
    const kbId = activeKb.value?.id;
    if (!kbId) {
        allDocuments.value = [];
        return;
    }
    loading.value = true;
    try {
        const res = await documentApi.list({
            knowledge_base_id: kbId,
            page: 1,
            size: 200,
            dept_ids: deptFilterIds.value ?? undefined,
        });
        allDocuments.value = res.data?.items ?? [];
    } finally {
        loading.value = false;
    }
    // 新列表里可能存在 reindexing 文档（如其他入口触发），确保轮询跟上
    ensurePolling();
}

// —— 知识库树回调 ——
// 树内点选知识库/文件夹：知识库变化（或部门边界刚变化）时重置导航并重拉文档，
// 文件夹变化只改过滤
async function onTreeSelect({ kb, folder }: { kb: KnowledgeBase; folder: Folder | null }) {
    const kbChanged = kb.id !== activeKb.value?.id;
    if (kbChanged || pendingDeptReload) {
        pendingDeptReload = false;
        // 切库先停掉旧库的轮询，新列表加载完成后由 loadDocuments 重新 ensure
        stopPolling();
        activeKb.value = kb;
        folders.value = [];
        resetFolderNav();
        await loadDocuments();
    }
    if (folder) selectFolder(folder.id);
    else if (!kbChanged) selectFolder(null);
}
// 树内懒加载完成某知识库的文件夹后同步到本地（供面包屑/弹窗使用）
function onFoldersLoaded(kbId: string, list: Folder[]) {
    if (kbId === activeKb.value?.id) folders.value = list;
}
// 部门过滤后无可见知识库：清空选中态与文档列表（待重拉标记一并消费）
function onTreeCleared() {
    pendingDeptReload = false;
    stopPolling();
    activeKb.value = null;
    allDocuments.value = [];
    folders.value = [];
    resetFolderNav();
}

// 搜索：提交草稿并回到第 1 页（知识库切换已由左侧树承担）
function applySearch() {
    Object.assign(applied, draft);
    page.value = 1;
}
function resetFilters() {
    Object.assign(draft, emptyFilter());
    Object.assign(applied, emptyFilter());
    page.value = 1;
}

// —— 新建文件（上传文档）——
const uploadDialogVisible = ref(false);
function openUpload() {
    // 文档必须归属部门：all 档且左树未选部门时，存量游离库（知识库无归属部门）
    // 无法继承归属，前置拦截；后端守卫为权威兜底，报错由响应拦截器自动 toast
    if (showDeptTree.value && !selectedDept.value && !activeKb.value?.dept_id) {
        ElMessage.warning("当前知识库未归属部门，请先在左侧部门树选择归属部门");
        return;
    }
    uploadDialogVisible.value = true;
}
async function onUploadSubmit(payload: DocumentUploadFormPayload) {
    uploading.value = true;
    try {
        await documentApi.upload({
            file: payload.file,
            knowledge_base_id: payload.knowledge_base_id,
            folder_id: payload.folder_id,
            title: payload.title,
            valid_from: payload.valid_from,
            valid_until: payload.valid_until,
            remark: payload.remark,
            chunk_strategy: payload.chunk_strategy,
            // 左树选中了部门时挂到所选部门（仅 data_scope=all 生效），
            // 未选中由服务端注入（本人部门→继承知识库归属部门，不可为空）
            dept_id: selectedDept.value?.id ?? null,
        });
        ElMessage.success("上传成功，已完成解析与切块");
        uploadDialogVisible.value = false;
        await loadDocuments();
    } finally {
        uploading.value = false;
    }
}

// —— 文件夹管理（新建 / 修改 / 删除）——
const folderDialogVisible = ref(false);
const folderSubmitting = ref(false);
const editingFolder = ref<Folder | null>(null);
function openCreateFolder() {
    editingFolder.value = null;
    folderDialogVisible.value = true;
}
function openEditFolder() {
    const cur = folders.value.find((f) => f.id === selectedFolderId.value);
    if (!cur) {
        ElMessage.warning("请先在左侧选择要修改的文件夹");
        return;
    }
    editingFolder.value = cur;
    folderDialogVisible.value = true;
}
// 文件夹增删改后：让左侧树失效缓存并重拉当前知识库的子树（同时回流 folders）
async function refreshFolders() {
    const kbId = activeKb.value?.id;
    if (kbId) await knowledgeTreeRef.value?.refreshFolders(kbId);
}

async function onFolderSubmit(payload: FolderFormPayload) {
    folderSubmitting.value = true;
    try {
        if (editingFolder.value) {
            // knowledge_base_id 创建后不可变，更新时不传
            await folderApi.update(editingFolder.value.id, {
                name: payload.name,
                parent_id: payload.parent_id,
                sort_order: payload.sort_order,
            });
            ElMessage.success("文件夹已更新");
        } else {
            await folderApi.create(payload);
            ElMessage.success("文件夹已创建");
        }
        folderDialogVisible.value = false;
        await refreshFolders();
    } finally {
        folderSubmitting.value = false;
    }
}
async function deleteFolder() {
    const cur = folders.value.find((f) => f.id === selectedFolderId.value);
    if (!cur) {
        ElMessage.warning("请先在左侧选择要删除的文件夹");
        return;
    }
    const confirmed = await confirmDanger(`确定删除文件夹「${cur.name}」吗？仅空文件夹可删除。`);
    if (!confirmed) return;
    await folderApi.remove(cur.id);
    ElMessage.success("文件夹已删除");
    selectFolder(cur.parent_id ?? null);
    await refreshFolders();
}

// 新建文件夹时默认以当前选中文件夹为上级
const folderDefaultParentId = computed(() =>
    editingFolder.value ? null : selectedFolderId.value
);

// —— 向量化（异步）：快速触发 + 轮询同步状态 ——
async function handleVectorize(doc: RagDocument) {
    vectorizingId.value = doc.id;
    try {
        await documentApi.vectorize(doc.id);
        // 不弹提示，成功与否由状态圆点体现；就地改状态而非全量重拉，避免筛选/分页跳动
        const target = allDocuments.value.find((d) => d.id === doc.id);
        if (target) target.status = "reindexing";
        ensurePolling();
    } finally {
        vectorizingId.value = null;
    }
}

// —— 删除文档：二次确认后后端联动清理 PG 分块与 Qdrant 向量点 ——
async function handleDeleteDoc(doc: RagDocument) {
    const confirmed = await confirmDanger(
        `确定删除文档「${doc.title || doc.source_uri || doc.id}」吗？将同步清理其全部分块与向量数据。`
    );
    if (!confirmed) return;
    await documentApi.remove(doc.id);
    ElMessage.success("文档已删除");
    // 就地移除避免分页跳动，再静默重拉对齐服务端（含知识库计数变化）
    allDocuments.value = allDocuments.value.filter((d) => d.id !== doc.id);
    await loadDocuments();
}

// 轮询器：仅当列表中存在 reindexing 文档时运行单一定时器，全部终态后自动停止
const POLL_INTERVAL = 2500;
let pollTimer: ReturnType<typeof setInterval> | null = null;

function stopPolling() {
    if (pollTimer != null) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

function ensurePolling() {
    if (pollTimer != null) return;
    if (!allDocuments.value.some((d) => d.status === "reindexing")) return;
    pollTimer = setInterval(pollStatuses, POLL_INTERVAL);
}

async function pollStatuses() {
    const ids = allDocuments.value.filter((d) => d.status === "reindexing").map((d) => d.id);
    if (!ids.length) {
        stopPolling();
        return;
    }
    try {
        const res = await documentApi.batchStatus(ids);
        for (const item of res.data ?? []) {
            const doc = allDocuments.value.find((d) => d.id === item.id);
            if (!doc || doc.status === item.status) continue;
            // 终态不弹提示：active 圆点变绿、failed 圆点变红即信号
            doc.status = item.status;
        }
    } catch {
        // 单次轮询失败静默吞掉，下一轮重试
    }
    if (!allDocuments.value.some((d) => d.status === "reindexing")) stopPolling();
}

onUnmounted(stopPolling);

// —— 查看分块（抽屉）——
const chunkDrawerVisible = ref(false);
const chunkDoc = ref<RagDocument | null>(null);
// 分块策略展示：structure→章节分块，char/缺省（存量文档）→通用分块
const chunkStrategyLabel = computed(() =>
    chunkDoc.value?.metadata?.chunk_strategy === "structure" ? "章节分块" : "通用分块"
);
function openChunks(doc: RagDocument) {
    chunkDoc.value = doc;
    chunkDrawerVisible.value = true;
}

// —— 文档详情（查看 + 修改元数据）——
const detailDialogVisible = ref(false);
const detailDoc = ref<RagDocument | null>(null);
const detailSubmitting = ref(false);
function openDetail(doc: RagDocument) {
    detailDoc.value = doc;
    detailDialogVisible.value = true;
}
async function onDetailSubmit(payload: DocumentUpdatePayload) {
    if (!detailDoc.value) return;
    detailSubmitting.value = true;
    try {
        const res = await documentApi.update(detailDoc.value.id, payload);
        ElMessage.success("文档已更新");
        detailDialogVisible.value = false;
        // 用服务端回传就地替换，避免全量重拉引起筛选/分页跳动
        const updated = res.data;
        if (updated) {
            const idx = allDocuments.value.findIndex((d) => d.id === updated.id);
            if (idx >= 0) allDocuments.value[idx] = updated;
        }
    } finally {
        detailSubmitting.value = false;
    }
}
</script>

<template>
    <section class="doc-page list-page">
        <!-- 顶部导航条：前进/后退/向上 + 面包屑 -->
        <div class="nav-bar">
            <div class="nav-btns">
                <button type="button" :disabled="!canBack" @click="goBack">‹ 后退</button>
                <button type="button" :disabled="!canForward" @click="goForward">前进 ›</button>
                <button type="button" @click="goUp">↑ 向上</button>
            </div>
            <nav class="crumbs">
                <template v-for="(crumb, i) in breadcrumb" :key="crumb.id ?? 'root'">
                    <span v-if="i" class="sep">/</span>
                    <button type="button" class="crumb" :class="{ active: i === breadcrumb.length - 1 }"
                        @click="selectFolder(crumb.id)">
                        {{ crumb.name }}
                    </button>
                </template>
            </nav>
        </div>

        <div class="doc-layout">
            <!-- 左侧：部门树（仅 data_scope=all）+ 知识库/文件夹树，两棵树并列、职责独立 -->
            <aside class="side">
                <DeptTreePanel v-if="showDeptTree" class="side-dept-panel" @select="onDeptSelect" />
                <div class="side-card">
                    <div class="side-head">知识库</div>
                    <!-- 知识库/文件夹的加载与懒加载全部封装在此组件内，dept-ids 变化时按部门边界重载 -->
                    <KnowledgeTree ref="knowledgeTreeRef" :dept-ids="deptFilterIds" @select="onTreeSelect"
                        @folders-loaded="onFoldersLoaded" @cleared="onTreeCleared" />
                </div>
            </aside>

            <!-- 右侧主区 -->
            <section class="main" v-loading="loading" element-loading-text="加载中…">
                <!-- 筛选表单 -->
                <div class="filter-card">
                    <div class="filter-grid">
                        <label class="fi">
                            <span>手册名称</span>
                            <el-input v-model="draft.keyword" placeholder="文件名称" clearable />
                        </label>
                        <label class="fi fi-wide">
                            <span>生效时间</span>
                            <el-date-picker v-model="draft.dateRange" type="daterange" range-separator="至"
                                start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" />
                        </label>
                        <label class="fi">
                            <span>表格类</span>
                            <el-select v-model="draft.tableType" placeholder="全部">
                                <el-option v-for="o in tableTypeOptions" :key="o.value" :label="o.label"
                                    :value="o.value" />
                            </el-select>
                        </label>
                        <label class="fi">
                            <span>备注</span>
                            <el-input v-model="draft.remark" placeholder="模糊查询" clearable />
                        </label>
                        <div class="fi-actions">
                            <button type="button" class="primary-button" @click="applySearch">搜索</button>
                            <button type="button" class="ghost-button" @click="resetFilters">重置</button>
                        </div>
                    </div>
                </div>

                <!-- 操作栏 + 图例 -->
                <div class="action-bar">
                    <!-- 未选择知识库时禁用新建/修改/删除操作 -->
                    <div class="actions">
                        <button type="button" class="primary-button" :disabled="!hasKb" @click="openUpload">
                            ＋ 新建文件
                        </button>
                        <button type="button" class="ghost-button" :disabled="!hasKb" @click="openCreateFolder">
                            ＋ 新建文件夹
                        </button>
                        <button type="button" class="ghost-button" :disabled="!hasKb" @click="openEditFolder">
                            修改文件夹
                        </button>
                        <button type="button" class="ghost-button danger" :disabled="!hasKb" @click="deleteFolder">
                            删除文件夹
                        </button>
                    </div>
                    <div class="legend">
                        <span v-for="item in syncLegend" :key="item.cls" class="legend-item">
                            <i class="sync-dot" :class="item.cls"></i>
                            {{ item.label }}
                        </span>
                    </div>
                </div>

                <!-- 卡片网格 -->
                <div class="doc-content list-scroll">
                    <div v-if="pagedDocuments.length" class="card-grid">
                        <DocumentCard v-for="doc in pagedDocuments" :key="doc.id" :document="doc"
                            :vectorizing="vectorizingId === doc.id" @open="openChunks" @view-chunks="openChunks"
                            @vectorize="handleVectorize" @detail="openDetail" @delete="handleDeleteDoc" />
                    </div>
                    <el-empty v-else class="doc-empty" description="暂无文档" :image-size="110">
                        <template #image>
                            <SvgIcon class="empty-icon" name="wenjian" :size="96" />
                        </template>
                    </el-empty>
                </div>

                <div class="pagination-bar list-footer">
                    <Pagination v-model:page="page" v-model:size="size" :total="total" :page-sizes="[12, 24, 48, 96]" />
                </div>
            </section>
        </div>

        <!-- 弹窗与抽屉 -->
        <DocumentUploadDialog v-model:visible="uploadDialogVisible" :uploading="uploading" :knowledge-base="activeKb"
            :folders="folders" :default-folder-id="selectedFolderId" @submit="onUploadSubmit" />
        <DocumentDetailDialog v-model:visible="detailDialogVisible" :submitting="detailSubmitting" :document="detailDoc"
            :knowledge-base-name="activeKb?.name ?? ''" :folders="folders" @submit="onDetailSubmit" />
        <FolderFormDialog v-model:visible="folderDialogVisible" :record="editingFolder" :folders="folders"
            :knowledge-base-id="activeKb?.id ?? ''" :submitting="folderSubmitting"
            :default-parent-id="folderDefaultParentId" @submit="onFolderSubmit" />
        <el-drawer v-model="chunkDrawerVisible" size="640px" direction="rtl">
            <template #header>
                <span>{{ chunkDoc?.title || '文档分块' }}</span>
                <el-tag size="small" type="info">{{ chunkStrategyLabel }}</el-tag>
            </template>
            <DocumentChunkTree v-if="chunkDoc" :document-id="chunkDoc.id" :document-version="chunkDoc.version" />
        </el-drawer>
    </section>
</template>

<style scoped>
.doc-page {
    gap: 14px;
    color: #273249;
}

/* 顶部导航条 */
.nav-bar {
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 10px 16px;
    border: 1px solid #e8ebf2;
    border-radius: 12px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.nav-btns {
    display: flex;
    gap: 6px;
}

.nav-btns button {
    padding: 5px 12px;
    border: 1px solid #e2e7f2;
    border-radius: 7px;
    color: #4d5970;
    background: #fff;
    font-size: 12px;
    cursor: pointer;
    transition:
        border-color 150ms ease,
        color 150ms ease;
}

.nav-btns button:not(:disabled):hover {
    border-color: #b9c4ea;
    color: #526ae2;
}

.nav-btns button:disabled {
    color: #c2c9d6;
    cursor: not-allowed;
}

.crumbs {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

.crumb {
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
}

.crumb.active {
    color: #273249;
    cursor: default;
}

.sep {
    color: #b9c1d2;
}

/* 两列布局 */
.doc-layout {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    gap: 16px 24px;
    align-items: stretch;
    flex: 1;
    min-height: 0;
}

.side {
    display: grid;
    gap: 14px;
    align-content: start;
}

.side-card {
    display: grid;
    gap: 10px;
    padding: 14px;
    border: 1px solid #e8ebf2;
    border-radius: 12px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.side-head {
    color: #8993a5;
    font-size: 12px;
    font-weight: 700;
}

/* 侧栏卡片内的搜索框随卡片宽度自适应：
   SearchInput 默认固定 240px，超出 240px 侧栏（含内边距）会横向溢出，覆盖树列表 */
.side-card :deep(.search-input) {
    width: 100%;
}

/* 部门树面板在 240px grid 侧栏内：限高走内部滚动，避免挤压下方知识库树 */
.side-dept-panel :deep(.dept-tree-panel__tree) {
    max-height: 300px;
    overflow: auto;
}

/* 右侧主区 */
.main {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-height: 0;
}

.filter-card {
    padding: 16px;
    border: 1px solid #e8ebf2;
    border-radius: 12px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.filter-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 14px 20px;
    align-items: center;
}

.fi {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    font-size: 13px;
}

.fi>span {
    flex: 0 0 auto;
    color: #5f6b83;
}

/* 表单控件填满各自网格单元：宽度可预测，不会横向溢出挤压左侧菜单 */
.fi :deep(.el-input),
.fi :deep(.el-select),
.fi :deep(.el-date-editor) {
    flex: 1 1 auto;
    width: auto;
    min-width: 0;
}

/* 生效时间日期区间较宽，占两列 */
.fi-wide {
    grid-column: span 2;
}

.fi-actions {
    grid-column: 1 / -1;
    display: flex;
    gap: 10px;
    justify-content: flex-end;
}

/* 操作栏 */
.action-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
}

.actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.legend {
    display: flex;
    gap: 16px;
}

.legend-item {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: #8993a5;
    font-size: 12px;
}

.sync-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #c2c9d6;
}

.sync-dot.pending {
    background: #c2c9d6;
}

.sync-dot.syncing {
    background: #e6a23c;
}

.sync-dot.synced {
    background: #3fa77b;
}

.sync-dot.failed {
    background: #e0637a;
}

/* 卡片网格：撑满剩余高度与内部滚动的骨架由全局 list-scroll 提供，
   此处只保留空状态居中所需的列式布局。 */
.doc-content {
    display: flex;
    flex-direction: column;
}

.doc-empty {
    margin: auto;
}

/* 空状态占位图标：统一走本地图标资源，弱化为浅灰 */
.empty-icon {
    color: #cfd6e4;
}

.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 16px;
    padding: 4px 0;
}

.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding-top: 12px;
    border-top: 1px solid #eef1f7;
}

/* 按钮 */
.primary-button {
    min-height: 36px;
    padding: 0 16px;
    border: 0;
    border-radius: 9px;
    color: #fff;
    background: #526ae2;
    box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
}

.ghost-button {
    min-height: 36px;
    padding: 0 14px;
    border: 1px solid #dfe4ef;
    border-radius: 9px;
    color: #4d5970;
    background: #fff;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition:
        border-color 150ms ease,
        color 150ms ease;
}

.primary-button:disabled,
.ghost-button:disabled {
    color: #c2c9d6;
    background: #f4f6fa;
    box-shadow: none;
    cursor: not-allowed;
}

.ghost-button:disabled {
    border-color: #e8ebf2;
}

.ghost-button:not(:disabled):hover {
    border-color: #b9c4ea;
    color: #526ae2;
}

.ghost-button.danger:not(:disabled):hover {
    border-color: #edb4b4;
    color: #d05a5a;
}

@media (max-width: 900px) {
    .doc-page {
        height: auto;
    }

    .doc-layout {
        grid-template-columns: 1fr;
        flex: none;
    }

    .doc-content {
        min-height: 320px;
        overflow: visible;
    }
}
</style>
