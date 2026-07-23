<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
    listKnowledgeBases,
    createKnowledgeBase,
    updateKnowledgeBase,
    deleteKnowledgeBase,
    type KnowledgeBase,
} from '@/api/rag/knowledgeBase'
import { listCategories, type Category } from '@/api/rag/categories'
import KnowledgeBaseTable from '@/components/rag/KnowledgeBaseTable.vue'
import KnowledgeBaseFormDialog from '@/components/rag/KnowledgeBaseFormDialog.vue'
import type { KnowledgeBaseFormPayload } from '@/components/rag/types'

const loading = ref(false)
const knowledgeBases = ref<KnowledgeBase[]>([])
const categories = ref<Category[]>([])
const keyword = ref('')

// 列表按关键词过滤（名称 / 描述 / Qdrant 集合）
const filteredList = computed(() => {
    const kw = keyword.value.trim().toLowerCase()
    if (!kw) return knowledgeBases.value
    return knowledgeBases.value.filter((b) =>
        [b.name, b.qdrant_collection, b.description ?? ''].some((f) => f.toLowerCase().includes(kw))
    )
})

// 汇总指标
const totalDocuments = computed(() =>
    knowledgeBases.value.reduce((sum, b) => sum + (b.document_count ?? 0), 0)
)
const totalChunks = computed(() =>
    knowledgeBases.value.reduce((sum, b) => sum + (b.total_chunk_count ?? 0), 0)
)

async function loadKnowledgeBases() {
    loading.value = true
    try {
        const res = await listKnowledgeBases()
        knowledgeBases.value = res.data ?? []
    } finally {
        loading.value = false
    }
}

async function loadCategories() {
    const res = await listCategories()
    categories.value = res.data ?? []
}

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
                qdrant_collection: payload.qdrant_collection,
                description: payload.description || null,
                category_id: payload.category_id,
                visibility: payload.visibility,
            })
            ElMessage.success('知识库已创建')
        }
        dialogVisible.value = false
        await loadKnowledgeBases()
    } finally {
        submitting.value = false
    }
}

async function removeKnowledgeBase(base: KnowledgeBase) {
    try {
        await ElMessageBox.confirm(
            `确定删除知识库「${base.name}」吗？删除后将不再出现在列表中。`,
            '删除确认',
            { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
        )
    } catch {
        return
    }
    await deleteKnowledgeBase(base.id)
    ElMessage.success('知识库已删除')
    await loadKnowledgeBases()
}

onMounted(() => {
    loadKnowledgeBases()
    loadCategories()
})
</script>

<template>
    <section class="rag-page" v-loading="loading">
        <header class="page-header">
            <div>
                <p class="eyebrow">RAG SYSTEM / KNOWLEDGE BASE</p>
                <h1>知识库管理</h1>
                <p>创建并维护为智能体提供检索上下文的知识库。</p>
            </div><button class="primary-button" type="button" @click="openCreate">＋ 新建知识库</button>
        </header>
        <section class="summary-grid">
            <article><span>知识库总数</span><strong>{{ knowledgeBases.length }}</strong><small>全部知识源</small></article>
            <article><span>已收录文档</span><strong>{{ totalDocuments }}</strong><small>所有知识库合计</small></article>
            <article><span>分块总数</span><strong>{{ totalChunks }}</strong><small>已入库块数</small></article>
        </section>
        <section class="content-card">
            <div class="toolbar">
                <div>
                    <h2>知识库列表</h2><span>共 {{ filteredList.length }} 个知识库</span>
                </div><input v-model="keyword" aria-label="搜索知识库" placeholder="搜索名称 / 描述 / 集合" />
            </div>
            <KnowledgeBaseTable :list="filteredList" :categories="categories" @edit="openEdit"
                @remove="removeKnowledgeBase" />
        </section>

        <KnowledgeBaseFormDialog v-model:visible="dialogVisible" :record="editing" :categories="categories"
            :submitting="submitting" @submit="handleSubmit" />
    </section>
</template>

<style scoped>
.rag-page {
    display: grid;
    gap: 24px;
    max-width: 1280px;
    margin: 0 auto;
    color: #273249
}

.page-header,
.toolbar {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 20px
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

h1 {
    margin-bottom: 9px;
    font-size: clamp(26px, 3vw, 34px);
    letter-spacing: -1px
}

.page-header p:not(.eyebrow) {
    margin-bottom: 0;
    color: #788397;
    font-size: 14px
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

h2 {
    margin-bottom: 4px;
    font-size: 16px
}

input {
    width: 205px;
    padding: 9px 11px;
    border: 1px solid #dfe4ef;
    border-radius: 8px;
    outline: 0;
    color: #34405a
}

input:focus {
    border-color: #8091e8;
    box-shadow: 0 0 0 3px rgb(128 145 232 / 12%)
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

    input {
        width: 100%
    }
}
</style>
