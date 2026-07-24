<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
    listKnowledgeBases,
    createKnowledgeBase,
    updateKnowledgeBase,
    deleteKnowledgeBase,
    type KnowledgeBase,
} from '@/api/rag/knowledgeBase'
import { listCategories, type Category } from '@/api/rag/categories'
import { getRagStats, type RagStats } from '@/api/rag/stats'
import { confirmDanger } from '@/utils/confirm'
import KnowledgeBaseTable from '@/components/rag/KnowledgeBaseTable.vue'
import KnowledgeBaseFormDialog from '@/components/rag/KnowledgeBaseFormDialog.vue'
import SearchInput from '@/components/rag/SearchInput.vue'
import Pagination from '@/components/rag/Pagination.vue'
import type { KnowledgeBaseFormPayload } from '@/components/rag/types'

const loading = ref(false)
const knowledgeBases = ref<KnowledgeBase[]>([])
const categories = ref<Category[]>([])
const keyword = ref('')

// 分页状态（服务端分页）
const page = ref(1)
const size = ref(20)
const total = ref(0)

// 全局统计（汇总卡片数据源）
const stats = ref<RagStats>({
    knowledge_base_count: 0,
    document_count: 0,
    total_chunk_count: 0,
})

async function loadKnowledgeBases() {
    loading.value = true
    try {
        const res = await listKnowledgeBases({
            page: page.value,
            size: size.value,
            keyword: keyword.value.trim() || undefined,
        })
        knowledgeBases.value = res.data?.items ?? []
        total.value = res.data?.total ?? 0
    } finally {
        loading.value = false
    }
}

async function loadCategories() {
    const res = await listCategories()
    categories.value = res.data?.items ?? []
}

async function loadStats() {
    const res = await getRagStats()
    if (res.data) stats.value = res.data
}

// 关键词防抖：变更后回到第 1 页并触发服务端重载
let keywordTimer: ReturnType<typeof setTimeout> | undefined
watch(keyword, () => {
    if (keywordTimer) clearTimeout(keywordTimer)
    keywordTimer = setTimeout(() => {
        page.value = 1
        loadKnowledgeBases()
    }, 300)
})

// 新建 / 编辑弹窗
const dialogVisible = ref(false)
const submitting = ref(false)
const editing = ref<KnowledgeBase | null>(null)

function openCreate() {
    editing.value = null
    dialogVisible.value = true
}

function openEdit(base: KnowledgeBase) {
    editing.value = base
    dialogVisible.value = true
}

async function handleSubmit(payload: KnowledgeBaseFormPayload) {
    submitting.value = true
    try {
        if (editing.value) {
            await updateKnowledgeBase(editing.value.id, {
                name: payload.name,
                description: payload.description || null,
                category_id: payload.category_id,
                visibility: payload.visibility,
                status: payload.status,
            })
            ElMessage.success('知识库已更新')
        } else {
            await createKnowledgeBase({
                name: payload.name,
                description: payload.description || null,
                category_id: payload.category_id,
                visibility: payload.visibility,
            })
            ElMessage.success('知识库已创建')
        }
        dialogVisible.value = false
        await loadKnowledgeBases()
        await loadStats()
    } finally {
        submitting.value = false
    }
}

async function removeKnowledgeBase(base: KnowledgeBase) {
    const confirmed = await confirmDanger(
        `确定删除知识库「${base.name}」吗？删除后将不再出现在列表中。`
    )
    if (!confirmed) return
    await deleteKnowledgeBase(base.id)
    ElMessage.success('知识库已删除')
    await loadKnowledgeBases()
    await loadStats()
}

onMounted(() => {
    loadKnowledgeBases()
    loadCategories()
    loadStats()
})
</script>

<template>
    <section class="rag-page" v-loading="loading" element-loading-text="加载中…">
        <section class="summary-grid">
            <article><span>知识库总数</span><strong>{{ stats.knowledge_base_count }}</strong><small>全部知识源</small></article>
            <article><span>已收录文档</span><strong>{{ stats.document_count }}</strong><small>所有知识库合计</small></article>
            <article><span>分块总数</span><strong>{{ stats.total_chunk_count }}</strong><small>已入库块数</small></article>
        </section>
        <section class="content-card">
            <div class="toolbar">
                <div>
                    <h2>知识库列表</h2><span>共 {{ total }} 个知识库</span>
                </div>
                <div class="toolbar-actions">
                    <SearchInput v-model="keyword" placeholder="搜索名称 / 描述" />
                    <button class="primary-button" type="button" @click="openCreate">＋ 新建知识库</button>
                </div>
            </div>
            <KnowledgeBaseTable :list="knowledgeBases" :categories="categories" @edit="openEdit"
                @remove="removeKnowledgeBase" />
            <div class="pagination-bar">
                <Pagination v-model:page="page" v-model:size="size" :total="total" @change="loadKnowledgeBases" />
            </div>
        </section>

        <KnowledgeBaseFormDialog v-model:visible="dialogVisible" :record="editing" :categories="categories"
            :submitting="submitting" @submit="handleSubmit" />
    </section>
</template>

<style scoped>
.rag-page {
    display: grid;
    gap: 20px;
    color: #273249
}

.page-header,
.toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px
}

.toolbar-actions {
    display: flex;
    align-items: center;
    gap: 12px
}

.eyebrow {
    margin: 0 0 8px;
    color: #7b89b9;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.15px
}

h1,
h2,
p {
    margin-top: 0
}

.primary-button {
    min-height: 40px;
    padding: 0 16px;
    border: 0;
    border-radius: 9px;
    color: #fff;
    background: #526ae2;
    box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
    font-size: 13px;
    font-weight: 600
}

.summary-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px
}

.summary-grid article,
.content-card {
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%)
}

.summary-grid article {
    display: grid;
    gap: 7px;
    padding: 20px
}

.summary-grid span,
.summary-grid small,
.toolbar span {
    color: #7d879a;
    font-size: 12px
}

.summary-grid strong {
    font-size: 28px;
    letter-spacing: -1px
}

.summary-grid small {
    color: #4eab83
}

.toolbar {
    align-items: center;
    padding: 19px 20px;
    border-bottom: 1px solid #edf0f5
}

.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 16px 20px
}

h2 {
    margin-bottom: 4px;
    font-size: 16px
}

@media(max-width:720px) {

    .page-header,
    .toolbar {
        align-items: flex-start;
        flex-direction: column
    }

    .summary-grid {
        grid-template-columns: 1fr
    }
}
</style>
