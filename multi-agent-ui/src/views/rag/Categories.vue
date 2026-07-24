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

// 分类树节点：携带层级深度与是否含子分类，用于卡片缩进和展开箭头
interface CategoryNode {
    category: Category
    depth: number
    hasChildren: boolean
}

// 已展开的分类 id 集合：默认全部收起，仅展示顶级；点击箭头时才渲染其子分类（懒加载）
const expandedIds = ref<Set<string>>(new Set())

function toggleExpand(category: Category) {
    const next = new Set(expandedIds.value)
    if (next.has(category.id)) next.delete(category.id)
    else next.add(category.id)
    expandedIds.value = next
}

// 各分类的直接子分类数量（parent_id 指向该分类）
const childCountMap = computed(() => {
    const map: Record<string, number> = {}
    for (const c of categories.value) {
        if (c.parent_id) map[c.parent_id] = (map[c.parent_id] ?? 0) + 1
    }
    return map
})

// 排序：先按 sort_order，再按名称，保证同级顺序稳定
function sortSiblings(a: Category, b: Category) {
    return a.sort_order - b.sort_order || a.name.localeCompare(b.name)
}

// 按 parent_id 归组子分类；父节点缺失的分类（孤儿）归入顶级
const treeIndex = computed(() => {
    const idSet = new Set(categories.value.map((c) => c.id))
    const childrenMap = new Map<string, Category[]>()
    const roots: Category[] = []
    for (const c of categories.value) {
        if (c.parent_id && idSet.has(c.parent_id)) {
            const arr = childrenMap.get(c.parent_id)
            if (arr) arr.push(c)
            else childrenMap.set(c.parent_id, [c])
        } else {
            roots.push(c)
        }
    }
    roots.sort(sortSiblings)
    for (const arr of childrenMap.values()) arr.sort(sortSiblings)
    return { childrenMap, roots }
})

// 列表呈现：无关键词时按树形展示（默认仅顶级，展开的节点才渲染其子分类）；
// 搜索时按名称过滤并平铺（depth=0，不展开）。
const orderedCategories = computed<CategoryNode[]>(() => {
    const kw = keyword.value.trim().toLowerCase()
    if (kw) {
        return categories.value
            .filter((c) => c.name.toLowerCase().includes(kw))
            .sort(sortSiblings)
            .map((c) => ({ category: c, depth: 0, hasChildren: false }))
    }
    const { childrenMap, roots } = treeIndex.value
    const result: CategoryNode[] = []
    const walk = (node: Category, depth: number) => {
        const children = childrenMap.get(node.id) ?? []
        result.push({ category: node, depth, hasChildren: children.length > 0 })
        if (expandedIds.value.has(node.id)) {
            for (const child of children) walk(child, depth + 1)
        }
    }
    for (const root of roots) walk(root, 0)
    return result
})

// 顶部计数展示分类总数（搜索时为匹配数）
const displayCount = computed(() => {
    const kw = keyword.value.trim().toLowerCase()
    if (kw) return orderedCategories.value.length
    return categories.value.length
})

async function loadCategories() {
    loading.value = true
    try {
        // 树形结构需要完整的祖先链，一次性拉取全量（size 上限 200）并在前端组装与过滤
        const res = await listCategories({ page: 1, size: 200 })
        categories.value = res.data?.items ?? []
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
        <div class="category-toolbar">
            <span class="toolbar-count">共 {{ displayCount }} 个分类</span>
            <div class="toolbar-actions">
                <SearchInput v-model="keyword" placeholder="搜索分类名称" />
                <button class="primary-button" type="button" @click="openCreate">＋ 新建分类</button>
            </div>
        </div>
        <section v-if="orderedCategories.length" class="category-tree">
            <CategoryCard v-for="(node, index) in orderedCategories" :key="node.category.id" :category="node.category"
                :depth="node.depth" :color="markColors[index % markColors.length]"
                :child-count="childCountMap[node.category.id] ?? 0" :has-children="node.hasChildren"
                :expanded="expandedIds.has(node.category.id)" @toggle="toggleExpand" @edit="openEdit"
                @remove="removeCategory" />
        </section>
        <el-empty v-else :description="keyword ? '未找到匹配的分类' : '暂无分类，点击右上角新建'" />

        <CategoryFormDialog v-model:visible="dialogVisible" :record="editing" :categories="categories"
            :submitting="submitting" @submit="handleSubmit" />
    </section>
</template>

<style scoped>
.categories-page {
    display: grid;
    gap: 20px;
    color: #273249
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

.category-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px
}

.toolbar-actions {
    display: flex;
    align-items: center;
    gap: 12px
}

.toolbar-count {
    color: #7d879a;
    font-size: 13px;
    font-weight: 600
}

.category-tree {
    display: grid;
    gap: 12px
}

@media(max-width:720px) {
    .category-toolbar {
        align-items: stretch;
        flex-direction: column
    }

    .toolbar-actions {
        justify-content: space-between
    }

    .category-tree {
        grid-template-columns: 1fr
    }
}
</style>
