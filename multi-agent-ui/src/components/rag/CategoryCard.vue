<script setup lang="ts">
import type { Category } from '@/api/rag/categories'
import { formatDateTime } from '@/utils/format'

defineProps<{
    category: Category
    color: string
    childCount: number
    parentName: string
}>()

defineEmits<{
    (e: 'edit', category: Category): void
    (e: 'remove', category: Category): void
}>()
</script>

<template>
    <article class="category-card"><span class="category-mark" :style="{ background: color }"></span>
        <div class="card-heading">
            <h2>{{ category.name }}</h2>
            <div class="card-actions">
                <button type="button" @click="$emit('edit', category)">编辑</button>
                <button type="button" class="danger" @click="$emit('remove', category)">删除</button>
            </div>
        </div>
        <p>上级：{{ parentName }} · 排序 {{ category.sort_order }}</p>
        <footer><strong>{{ childCount }}</strong><span>个子分类</span><span class="time">{{
            formatDateTime(category.updated_at) }}</span>
        </footer>
    </article>
</template>

<style scoped>
.category-card {
    position: relative;
    padding: 22px;
    overflow: hidden;
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%)
}

.category-mark {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 4px
}

.card-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px
}

.card-heading h2 {
    margin: 0;
    font-size: 16px
}

.card-actions {
    display: flex;
    gap: 12px
}

.card-actions button {
    padding: 0;
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer
}

.card-actions button.danger {
    color: #d05a5a
}

.category-card>p {
    min-height: 39px;
    margin: 13px 0 20px;
    color: #788397;
    font-size: 13px;
    line-height: 1.5
}

.category-card footer {
    display: flex;
    align-items: baseline;
    gap: 5px;
    padding-top: 15px;
    border-top: 1px solid #eff1f5
}

.category-card footer strong {
    font-size: 21px
}

.category-card footer span {
    color: #8993a5;
    font-size: 12px
}

.category-card footer .time {
    margin-left: auto;
    color: #9aa3b5;
    font-size: 12px
}
</style>
