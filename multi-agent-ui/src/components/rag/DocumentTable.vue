<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { ElTree } from 'element-plus'
import {
    listDocuments,
    uploadDocument,
    vectorizeDocument,
    type RagDocument,
} from '@/api/rag/document'
import { listKnowledgeBases, type KnowledgeBase } from '@/api/rag/knowledgeBase'
import {
    buildCategoryTree,
    createCategory,
    deleteCategory,
    listCategories,
    updateCategory,
    type Category,
} from '@/api/rag/categories'
import { confirmDanger } from '@/utils/confirm'
import DocumentCard from '@/components/rag/DocumentCard.vue'
import DocumentChunkTree from '@/components/rag/DocumentChunkTree.vue'
import DocumentUploadDialog from '@/components/rag/DocumentUploadDialog.vue'
import CategoryFormDialog from '@/components/rag/CategoryFormDialog.vue'
import SearchInput from '@/components/SearchInput.vue'
import Pagination from '@/components/Pagination.vue'
import type { CategoryFormPayload, DocumentUploadFormPayload } from '@/components/rag/types'

// —— 顶部同步状态图例（与 DocumentCard 圆点保持一致）——
const syncLegend = [
    { label: '未同步', cls: 'pending' },
    { label: '同步中', cls: 'syncing' },
    { label: '已同步', cls: 'synced' },
    { label: '同步失败', cls: 'failed' },
]

// —— 部门树：后端暂未提供部门维度，先以静态占位数据呈现层级导航 ——
interface DeptNode { id: string; label: string; children?: DeptNode[] }
const departmentTree: DeptNode[] = [
    {
        id: 'dept-root', label: 'MXR组织', children: [
            {
                id: 'dept-ky', label: '开源小组', children: [
                    {
                        id: 'dept-sw', label: '声纹识别项目组', children: [
                            { id: 'dept-yx', label: '音频模型微调项目组' },
                            { id: 'dept-ocr', label: 'RAG项目组' },
                        ],
                    },
                    { id: 'dept-yqc', label: '艺启唱项目组' },
                    { id: 'dept-ocr', label: 'OCR文档识别项目组' },
                ],
            },
            { id: 'dept-by', label: '闭源小组' },
        ],
    },
]
const deptTreeRef = ref<InstanceType<typeof ElTree>>()
const deptKeyword = ref('')
function filterDept(value: string, data: DeptNode) {
    return value ? data.label.includes(value) : true
}
watch(deptKeyword, (v) => deptTreeRef.value?.filter(v))

// —— 数据源 ——
const loading = ref(false)
const uploading = ref(false)
const vectorizingId = ref<string | null>(null)
const allDocuments = ref<RagDocument[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const categories = ref<Category[]>([])

// 文件夹（分类）树
const folderTree = computed(() => buildCategoryTree(categories.value))
const folderTreeRef = ref<InstanceType<typeof ElTree>>()
const selectedCategoryId = ref<string | null>(null)

// —— 文件夹导航：前进/后退历史 + 面包屑 ——
const history = ref<(string | null)[]>([null])
const histIndex = ref(0)
const canBack = computed(() => histIndex.value > 0)
const canForward = computed(() => histIndex.value < history.value.length - 1)

function selectFolder(id: string | null, pushHistory = true) {
    selectedCategoryId.value = id
    page.value = 1
    if (pushHistory) {
        history.value = history.value.slice(0, histIndex.value + 1)
        history.value.push(id)
        histIndex.value = history.value.length - 1
    }
    nextTick(() => folderTreeRef.value?.setCurrentKey(id ?? undefined))
}
function goBack() {
    if (!canBack.value) return
    histIndex.value -= 1
    selectFolder(history.value[histIndex.value], false)
}
function goForward() {
    if (!canForward.value) return
    histIndex.value += 1
    selectFolder(history.value[histIndex.value], false)
}
function goUp() {
    const cur = categories.value.find((c) => c.id === selectedCategoryId.value)
    selectFolder(cur?.parent_id ?? null)
}
function onFolderClick(node: Category) {
    selectFolder(node.id)
}

// 面包屑：根目录 → …祖先链 → 当前文件夹
const breadcrumb = computed(() => {
    const path: { id: string | null; name: string }[] = [{ id: null, name: '根目录' }]
    if (selectedCategoryId.value) {
        const byId = new Map(categories.value.map((c) => [c.id, c]))
        const chain: Category[] = []
        let cur = byId.get(selectedCategoryId.value)
        while (cur) {
            chain.unshift(cur)
            cur = cur.parent_id ? byId.get(cur.parent_id) : undefined
        }
        for (const c of chain) path.push({ id: c.id, name: c.name })
    }
    return path
})

// —— 筛选表单：草稿（编辑中）与已应用（生效）分离，点击「搜索」才提交 ——
type FilterState = {
    kbId: string
    keyword: string
    dateRange: [string, string] | null
    tableType: '' | 'yes' | 'no'
    aiTag: string
    remark: string
}
function emptyFilter(): FilterState {
    return { kbId: '', keyword: '', dateRange: null, tableType: '', aiTag: '', remark: '' }
}
const draft = reactive<FilterState>(emptyFilter())
const applied = reactive<FilterState>(emptyFilter())
const tableTypeOptions = [
    { label: '全部', value: '' },
    { label: '是', value: 'yes' },
    { label: '否', value: 'no' },
]
// 表格类判定：doc_type 命中电子表格类扩展视为「表格类」
const SPREADSHEET = new Set(['excel', 'xlsx', 'xls'])
function isSpreadsheet(doc: RagDocument) {
    return SPREADSHEET.has((doc.doc_type ?? '').toLowerCase())
}

// —— 分页（本视图为客户端分页：后端 list 仅支持按知识库分页，
//     文件夹/多字段筛选在前端对当前知识库全量数据上完成）——
const page = ref(1)
const size = ref(12)

// 过滤链：文件夹 → 手册名称 → 生效时间 → 表格类 → 备注（AI 标签后端暂缺，占位不参与）
const filteredDocuments = computed(() => {
    const kw = applied.keyword.trim().toLowerCase()
    const remark = applied.remark.trim().toLowerCase()
    const [from, to] = applied.dateRange ?? [null, null]
    return allDocuments.value.filter((doc) => {
        if (selectedCategoryId.value && doc.category_id !== selectedCategoryId.value) return false
        if (kw) {
            const name = (doc.title || doc.source_uri || '').toLowerCase()
            if (!name.includes(kw)) return false
        }
        if (applied.tableType === 'yes' && !isSpreadsheet(doc)) return false
        if (applied.tableType === 'no' && isSpreadsheet(doc)) return false
        if (from && to && doc.valid_from) {
            const t = doc.valid_from.slice(0, 10)
            if (t < from.slice(0, 10) || t > to.slice(0, 10)) return false
        }
        if (remark) {
            const r = String((doc.metadata?.remark ?? '')).toLowerCase()
            if (!r.includes(remark)) return false
        }
        return true
    })
})
const total = computed(() => filteredDocuments.value.length)
const pagedDocuments = computed(() => {
    const start = (page.value - 1) * size.value
    return filteredDocuments.value.slice(start, start + size.value)
})

// —— 加载 ——
async function loadKnowledgeBases() {
    const res = await listKnowledgeBases()
    knowledgeBases.value = res.data?.items ?? []
    if (!applied.kbId && knowledgeBases.value.length) {
        applied.kbId = knowledgeBases.value[0].id
        draft.kbId = applied.kbId
    }
}
async function loadCategories() {
    const res = await listCategories({ page: 1, size: 200 })
    categories.value = res.data?.items ?? []
}
async function loadDocuments() {
    if (!applied.kbId) {
        allDocuments.value = []
        return
    }
    loading.value = true
    try {
        const res = await listDocuments({ knowledge_base_id: applied.kbId, page: 1, size: 200 })
        allDocuments.value = res.data?.items ?? []
    } finally {
        loading.value = false
    }
}

// 搜索：提交草稿；知识库变化则重新拉取；回到第 1 页
async function applySearch() {
    const kbChanged = draft.kbId !== applied.kbId
    Object.assign(applied, draft)
    page.value = 1
    if (kbChanged) await loadDocuments()
}
function resetFilters() {
    const kb = applied.kbId
    Object.assign(draft, emptyFilter(), { kbId: kb })
    Object.assign(applied, emptyFilter(), { kbId: kb })
    page.value = 1
}

// —— 新建文件（上传文档）——
const uploadDialogVisible = ref(false)
function openUpload() {
    uploadDialogVisible.value = true
}
async function onUploadSubmit(payload: DocumentUploadFormPayload) {
    uploading.value = true
    try {
        await uploadDocument({
            file: payload.file,
            knowledge_base_id: payload.knowledge_base_id,
            category_id: payload.category_id,
            title: payload.title,
            valid_from: payload.valid_from,
            valid_until: payload.valid_until,
            remark: payload.remark,
        })
        ElMessage.success('上传成功，已完成解析与切块')
        uploadDialogVisible.value = false
        if (payload.knowledge_base_id !== applied.kbId) {
            applied.kbId = payload.knowledge_base_id
            draft.kbId = payload.knowledge_base_id
        }
        await loadDocuments()
    } finally {
        uploading.value = false
    }
}

// —— 文件夹管理（新建 / 修改 / 删除）——
const folderDialogVisible = ref(false)
const folderSubmitting = ref(false)
const editingFolder = ref<Category | null>(null)
function openCreateFolder() {
    editingFolder.value = null
    folderDialogVisible.value = true
}
function openEditFolder() {
    const cur = categories.value.find((c) => c.id === selectedCategoryId.value)
    if (!cur) {
        ElMessage.warning('请先在左侧选择要修改的文件夹')
        return
    }
    editingFolder.value = cur
    folderDialogVisible.value = true
}
async function onFolderSubmit(payload: CategoryFormPayload) {
    folderSubmitting.value = true
    try {
        if (editingFolder.value) {
            await updateCategory(editingFolder.value.id, payload)
            ElMessage.success('文件夹已更新')
        } else {
            await createCategory(payload)
            ElMessage.success('文件夹已创建')
        }
        folderDialogVisible.value = false
        await loadCategories()
    } finally {
        folderSubmitting.value = false
    }
}
async function deleteFolder() {
    const cur = categories.value.find((c) => c.id === selectedCategoryId.value)
    if (!cur) {
        ElMessage.warning('请先在左侧选择要删除的文件夹')
        return
    }
    const confirmed = await confirmDanger(`确定删除文件夹「${cur.name}」吗？仅空文件夹可删除。`)
    if (!confirmed) return
    await deleteCategory(cur.id)
    ElMessage.success('文件夹已删除')
    selectFolder(cur.parent_id ?? null)
    await loadCategories()
}

// 新建文件夹时默认以当前选中文件夹为上级
const folderDefaultParentId = computed(() => (editingFolder.value ? null : selectedCategoryId.value))

// —— 向量化 ——
async function handleVectorize(doc: RagDocument) {
    vectorizingId.value = doc.id
    try {
        await vectorizeDocument(doc.id)
        ElMessage.success('向量化已触发')
        await loadDocuments()
    } finally {
        vectorizingId.value = null
    }
}

// —— 查看分块（抽屉）——
const chunkDrawerVisible = ref(false)
const chunkDoc = ref<RagDocument | null>(null)
function openChunks(doc: RagDocument) {
    chunkDoc.value = doc
    chunkDrawerVisible.value = true
}

onMounted(async () => {
    await Promise.all([loadKnowledgeBases(), loadCategories()])
    await loadDocuments()
})
</script>

<template>
    <section class="doc-page">
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
                        @click="selectFolder(crumb.id)">{{ crumb.name }}</button>
                </template>
            </nav>
        </div>

        <div class="doc-layout">
            <!-- 左侧：部门树 + 文件夹树 -->
            <aside class="side">
                <div class="side-card">
                    <div class="side-head">部门</div>
                    <SearchInput v-model="deptKeyword" placeholder="请输入部门名称" />
                    <el-tree ref="deptTreeRef" class="side-tree" :data="departmentTree" node-key="id"
                        :props="{ label: 'label', children: 'children' }" :filter-node-method="filterDept"
                        highlight-current :expand-on-click-node="false" default-expand-all />
                </div>
                <div class="side-card">
                    <div class="side-head">文件夹</div>
                    <el-tree ref="folderTreeRef" class="side-tree" :data="folderTree" node-key="id"
                        :props="{ label: 'name', children: 'children' }" highlight-current :expand-on-click-node="false"
                        @node-click="onFolderClick" />
                    <el-empty v-if="!folderTree.length" description="暂无文件夹" :image-size="48" />
                </div>
            </aside>

            <!-- 右侧主区 -->
            <section class="main" v-loading="loading" element-loading-text="加载中…">
                <!-- 筛选表单 -->
                <div class="filter-card">
                    <div class="filter-grid">
                        <label class="fi"><span>手册名称</span>
                            <el-input v-model="draft.keyword" placeholder="文件名称" clearable />
                        </label>
                        <label class="fi fi-wide"><span>生效时间</span>
                            <el-date-picker v-model="draft.dateRange" type="daterange" range-separator="至"
                                start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD"
                                style="width: 100%" />
                        </label>
                        <label class="fi"><span>表格类</span>
                            <el-select v-model="draft.tableType" placeholder="全部">
                                <el-option v-for="o in tableTypeOptions" :key="o.value" :label="o.label"
                                    :value="o.value" />
                            </el-select>
                        </label>
                        <label class="fi"><span>AI知识库</span>
                            <el-select v-model="draft.kbId" placeholder="选择知识库">
                                <el-option v-for="b in knowledgeBases" :key="b.id" :label="b.name" :value="b.id" />
                            </el-select>
                        </label>
                        <!-- AI 标签：后端暂未提供标签维度，占位以匹配设计稿 -->
                        <label class="fi"><span>AI标签</span>
                            <el-select v-model="draft.aiTag" placeholder="选择标签" disabled>
                                <el-option label="全部" value="" />
                            </el-select>
                        </label>
                        <label class="fi"><span>备注</span>
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
                    <div class="actions">
                        <button type="button" class="primary-button" @click="openUpload">＋ 新建文件</button>
                        <button type="button" class="ghost-button" @click="openCreateFolder">＋ 新建文件夹</button>
                        <button type="button" class="ghost-button" @click="openEditFolder">修改文件夹</button>
                        <button type="button" class="ghost-button danger" @click="deleteFolder">删除文件夹</button>
                    </div>
                    <div class="legend">
                        <span v-for="item in syncLegend" :key="item.cls" class="legend-item">
                            <i class="sync-dot" :class="item.cls"></i>{{ item.label }}
                        </span>
                    </div>
                </div>

                <!-- 卡片网格 -->
                <div class="doc-content">
                    <div v-if="pagedDocuments.length" class="card-grid">
                        <DocumentCard v-for="doc in pagedDocuments" :key="doc.id" :document="doc"
                            :vectorizing="vectorizingId === doc.id" @open="openChunks" @view-chunks="openChunks"
                            @vectorize="handleVectorize" />
                    </div>
                    <el-empty v-else class="doc-empty" description="暂无文档" :image-size="110" />
                </div>

                <div v-if="total" class="pagination-bar">
                    <Pagination v-model:page="page" v-model:size="size" :total="total" :page-sizes="[12, 24, 48, 96]" />
                </div>
            </section>
        </div>

        <!-- 弹窗与抽屉 -->
        <DocumentUploadDialog v-model:visible="uploadDialogVisible" :uploading="uploading"
            :knowledge-bases="knowledgeBases" :default-kb-id="applied.kbId" :default-category-id="selectedCategoryId"
            @submit="onUploadSubmit" />
        <CategoryFormDialog v-model:visible="folderDialogVisible" :record="editingFolder" :categories="categories"
            :submitting="folderSubmitting" :default-parent-id="folderDefaultParentId" @submit="onFolderSubmit" />
        <el-drawer v-model="chunkDrawerVisible" :title="chunkDoc?.title || '文档分块'" size="640px" direction="rtl">
            <DocumentChunkTree v-if="chunkDoc" :document-id="chunkDoc.id" :document-version="chunkDoc.version" />
        </el-drawer>
    </section>
</template>

<style scoped>
.doc-page {
    display: grid;
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
    transition: border-color 150ms ease, color 150ms ease;
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
    gap: 16px;
    align-items: start;
}

.side {
    display: grid;
    gap: 14px;
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

.side-tree {
    max-height: 360px;
    overflow: auto;
    font-size: 13px;
    background: transparent;
}

/* 右侧主区 */
.main {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.filter-card {
    padding: 16px;
    border: 1px solid #e8ebf2;
    border-radius: 12px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.filter-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 14px 20px;
    align-items: center;
}

.fi {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
}

.fi>span {
    flex: 0 0 auto;
    color: #5f6b83;
}

.fi :deep(.el-input),
.fi :deep(.el-select) {
    width: 200px;
}

.fi-wide :deep(.el-date-editor) {
    width: 300px;
}

.fi-actions {
    display: flex;
    gap: 10px;
    margin-left: auto;
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

/* 卡片网格 */
.doc-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 320px;
}

.doc-empty {
    margin: auto;
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
    transition: border-color 150ms ease, color 150ms ease;
}

.ghost-button:hover {
    border-color: #b9c4ea;
    color: #526ae2;
}

.ghost-button.danger:hover {
    border-color: #edb4b4;
    color: #d05a5a;
}

@media (max-width: 900px) {
    .doc-layout {
        grid-template-columns: 1fr;
    }
}
</style>
