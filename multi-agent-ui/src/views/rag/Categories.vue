<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
    listCategories,
    createCategory,
    updateCategory,
    deleteCategory,
    type Category,
} from '@/api/rag/categories'
import { confirmDanger } from '@/utils/confirm'
import CategoryCard from '@/components/rag/CategoryCard.vue'
import CategoryFormDialog from '@/components/rag/CategoryFormDialog.vue'
import SearchInput from '@/components/rag/SearchInput.vue'
import type { CategoryFormPayload } from '@/components/rag/types'

// 顶部色带循环取色
const markColors = ['#6279df', '#40a67b', '#a276d7', '#df9b4f', '#e0637a', '#3fa7c4']

const loading = ref(false)
const categories = ref<Category[]>([])
const keyword = ref('')

// 按关键词过滤（名称），子分类数与上级名称仍基于全量数据计算
const filteredCategories = computed(() => {
    const kw = keyword.value.trim().toLowerCase()
    if (!kw) return categories.value
    return categories.value.filter((c) => c.name.toLowerCase().includes(kw))
})

// 各分类的直接子分类数量（parent_id 指向该分类）
const childCountMap = computed(() => {
    const map: Record<string, number> = {}
    for (const c of categories.value) {
        if (c.parent_id) map[c.parent_id] = (map[c.parent_id] ?? 0) + 1
    }
    return map
})

function parentName(parentId: string | null) {
    if (!parentId) return '顶级分类'
    return categories.value.find((c) => c.id === parentId)?.name ?? '未知分类'
}

async function loadCategories() {
    loading.value = true
    try {
        const res = await listCategories()
        categories.value = res.data ?? []
    } finally {
        loading.value = false
    }
}

// 新建 / 编辑弹窗
const dialogVisible = ref(false)
const submitting = ref(false)
const editing = ref<Category | null>(null)

function openCreate() {
    editing.value = null
    dialogVisible.value = true
}

function openEdit(category: Category) {
    editing.value = category
    dialogVisible.value = true
}

async function handleSubmit(payload: CategoryFormPayload) {
    submitting.value = true
    try {
        if (editing.value) {
            await updateCategory(editing.value.id, payload)
            ElMessage.success('分类已更新')
        } else {
            await createCategory(payload)
            ElMessage.success('分类已创建')
        }
        dialogVisible.value = false
        await loadCategories()
    } finally {
        submitting.value = false
    }
}

async function removeCategory(category: Category) {
    const confirmed = await confirmDanger(
        `确定删除分类「${category.name}」吗？仅空分类可删除。`
    )
    if (!confirmed) return
    await deleteCategory(category.id)
    ElMessage.success('分类已删除')
    await loadCategories()
}

onMounted(loadCategories)
</script>

<template>
    <section class="categories-page" v-loading="loading" element-loading-text="加载中…">
        <header class="page-header">
            <div>
                <p class="eyebrow">RAG SYSTEM / CATEGORIES</p>
                <h1>分类管理</h1>
                <p>使用分类组织文档，让检索范围更清晰、更可控。</p>
            </div><button class="primary-button" type="button" @click="openCreate">＋ 新建分类</button>
        </header>
        <section class="category-intro"><span>⌘</span>
            <div><strong>分类是文档的检索标签</strong>
                <p>为文档分配分类后，可在智能体检索时按业务范围筛选内容。</p>
            </div>
        </section>
        <div class="category-toolbar">
            <span class="toolbar-count">共 {{ filteredCategories.length }} 个分类</span>
            <SearchInput v-model="keyword" placeholder="搜索分类名称" />
        </div>
        <section v-if="filteredCategories.length" class="category-grid">
            <CategoryCard v-for="(category, index) in filteredCategories" :key="category.id" :category="category"
                :color="markColors[index % markColors.length]" :child-count="childCountMap[category.id] ?? 0"
                :parent-name="parentName(category.parent_id)" @edit="openEdit" @remove="removeCategory" />
        </section>
        <el-empty v-else :description="keyword ? '未找到匹配的分类' : '暂无分类，点击右上角新建'" />

        <CategoryFormDialog v-model:visible="dialogVisible" :record="editing" :categories="categories"
            :submitting="submitting" @submit="handleSubmit" />
    </section>
</template>

<style scoped>
.categories-page {
    display: grid;
    gap: 24px;
    max-width: 1280px;
    margin: 0 auto;
    color: #273249
}

.page-header {
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

.category-intro {
    display: flex;
    align-items: center;
    gap: 13px;
    padding: 17px 19px;
    border: 1px solid #dfe5f9;
    border-radius: 12px;
    background: #f4f6ff
}

.category-intro>span {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 9px;
    color: #526ae2;
    background: #e3e8ff
}

.category-intro strong {
    font-size: 13px
}

.category-intro p {
    margin: 4px 0 0;
    color: #728098;
    font-size: 12px
}

.category-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px
}

.toolbar-count {
    color: #7d879a;
    font-size: 12px
}

.category-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px
}

@media(max-width:720px) {
    .page-header {
        align-items: flex-start;
        flex-direction: column
    }

    .category-toolbar {
        align-items: flex-start;
        flex-direction: column
    }

    .category-grid {
        grid-template-columns: 1fr
    }
}
</style>
