<script setup lang="ts">
import { computed } from 'vue'
import type { Category } from '@/api/rag/categories'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
    category: Category
    color: string
    childCount: number
    /** 在分类树中的层级深度（0 为顶级），用于左侧缩进体现父子关系 */
    depth: number
    /** 是否含子分类：有则展示展开箭头 */
    hasChildren: boolean
    /** 当前是否已展开子分类 */
    expanded: boolean
}>()

// 每下钻一级缩进 20px，直观呈现「父 → 子」的树形归属
const indentStyle = computed(() => ({ marginLeft: `${props.depth * 20}px` }))

defineEmits<{
    (e: 'edit', category: Category): void
    (e: 'remove', category: Category): void
    (e: 'toggle', category: Category): void
}>()
</script>

<template>
    <article class="category-row" :class="{ 'is-root': !category.parent_id }" :style="indentStyle">
        <span class="row-mark" :style="{ background: color }"></span>

        <!-- 展开箭头：仅有子分类时可点击，无子分类留占位保持对齐 -->
        <button v-if="hasChildren" type="button" class="caret" :class="{ 'is-open': expanded }"
            :aria-label="expanded ? '收起子分类' : '展开子分类'" @click="$emit('toggle', category)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"
                stroke-linejoin="round">
                <path d="m9 6 6 6-6 6" />
            </svg>
        </button>
        <span v-else class="caret-placeholder" aria-hidden="true"></span>

        <span class="row-dot" :style="{ background: color }"></span>
        <h2 class="row-name" :title="category.name">{{ category.name }}</h2>

        <!-- 元信息 + 操作统一放到行尾，单行不换行 -->
        <span v-if="childCount" class="child-chip">{{ childCount }} 子分类</span>
        <span class="meta sort">排序 {{ category.sort_order }}</span>
        <span class="meta time">{{ formatDateTime(category.updated_at) }}</span>
        <span class="row-actions">
            <button type="button" @click="$emit('edit', category)">编辑</button>
            <button type="button" class="danger" @click="$emit('remove', category)">删除</button>
        </span>
    </article>
</template>

<style scoped>
.category-row {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px 10px 18px;
    overflow: hidden;
    border: 1px solid #e8ebf2;
    border-radius: 10px;
    background: #fff;
    box-shadow: 0 4px 12px rgb(43 56 86 / 3%);
    transition: border-color 150ms ease, box-shadow 150ms ease
}

.category-row:hover {
    border-color: #d3dbf5;
    box-shadow: 0 8px 20px rgb(43 56 86 / 7%)
}

.row-mark {
    position: absolute;
    top: 0;
    left: 0;
    width: 3px;
    height: 100%
}

.caret,
.caret-placeholder {
    width: 18px;
    height: 18px;
    flex: 0 0 auto
}

.caret {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 0;
    border-radius: 5px;
    color: #8b95aa;
    background: transparent;
    cursor: pointer;
    transition: transform 150ms ease, color 150ms ease, background 150ms ease
}

.caret:hover {
    color: #526ae2;
    background: #eef1ff
}

.caret.is-open {
    transform: rotate(90deg);
    color: #526ae2
}

.caret svg {
    width: 14px;
    height: 14px
}

.row-dot {
    width: 8px;
    height: 8px;
    flex: 0 0 auto;
    border-radius: 3px
}

.row-name {
    flex: 1 1 auto;
    min-width: 0;
    margin: 0;
    overflow: hidden;
    color: #273249;
    font-size: 14px;
    font-weight: 600;
    white-space: nowrap;
    text-overflow: ellipsis
}

.child-chip {
    flex: 0 0 auto;
    padding: 2px 8px;
    border-radius: 999px;
    color: #5f6b83;
    background: #f2f4fa;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap
}

.meta {
    flex: 0 0 auto;
    color: #9aa3b5;
    font-size: 12px;
    white-space: nowrap
}

.row-actions {
    display: flex;
    flex: 0 0 auto;
    gap: 10px;
    padding-left: 4px
}

.row-actions button {
    padding: 0;
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: color 150ms ease
}

.row-actions button:hover {
    color: #3550c9
}

.row-actions button.danger {
    color: #d05a5a
}

.row-actions button.danger:hover {
    color: #b83e3e
}

@media(max-width:720px) {

    .meta.time,
    .meta.sort {
        display: none
    }
}
</style>
