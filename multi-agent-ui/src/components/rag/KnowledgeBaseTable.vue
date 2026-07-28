<script setup lang="ts">
import type { KnowledgeBase } from "@/api/rag/knowledgeBase";
import { formatDateTime } from "@/utils/format";
import { useDictStore } from "@/stores/dictStore";

defineProps<{
    list: KnowledgeBase[];
}>();

defineEmits<{
    (e: "edit", base: KnowledgeBase): void;
    (e: "remove", base: KnowledgeBase): void;
}>();

const dictStore = useDictStore();
dictStore.ensureLoaded();

// 状态文案来自全局词典（status 类型，字典项由字典管理页面维护）
function statusLabel(status: string) {
    return dictStore.getLabel("status", status);
}
</script>

<template>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>知识库</th>
                    <th>部门</th>
                    <th>文档数量</th>
                    <th>分块数</th>
                    <th>最近更新</th>
                    <th>状态</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                <tr v-for="base in list" :key="base.id">
                    <td>
                        <strong>{{ base.name }}</strong>
                        <span>{{ base.description || "暂无描述" }}</span>
                    </td>
                    <!-- 存量游离库（无归属部门）显式标记“未归属”，新库已由创建守卫强制归属 -->
                    <td>{{ base.dept_name || "未归属" }}</td>
                    <td>{{ base.document_count }} 份</td>
                    <td>{{ base.total_chunk_count }}</td>
                    <td>{{ formatDateTime(base.updated_at) }}</td>
                    <td>
                        <em :class="{ processing: base.status !== 'active' }">
                            {{ statusLabel(base.status) }}
                        </em>
                    </td>
                    <td class="row-actions">
                        <button class="text-button" type="button" @click="$emit('edit', base)">编辑</button>
                        <button class="text-button danger" type="button" @click="$emit('remove', base)">
                            删除
                        </button>
                    </td>
                </tr>
                <tr v-if="!list.length">
                    <td colspan="7" class="empty-row">暂无知识库</td>
                </tr>
            </tbody>
        </table>
    </div>
</template>

<style scoped>
.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
}

th,
td {
    padding: 16px 20px;
    border-bottom: 1px solid #f0f2f6;
    font-size: 13px;
    white-space: nowrap;
}

th {
    color: #8993a5;
    font-size: 11px;
    font-weight: 600;
}

tbody tr {
    transition: background-color 150ms ease;
}

tbody tr:hover {
    background: #f7f9ff;
}

tbody tr:last-child td {
    border-bottom: 0;
}

td:first-child {
    min-width: 270px;
}

td strong,
td span {
    display: block;
}

td span {
    margin-top: 5px;
    color: #7d879a;
    font-size: 12px;
}

em {
    padding: 4px 8px;
    border-radius: 99px;
    color: #328161;
    background: #eaf7f1;
    font-size: 11px;
    font-style: normal;
}

em.processing {
    color: #a86d19;
    background: #fff4df;
}

.text-button {
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: color 150ms ease;
}

.text-button:hover {
    color: #3550c9;
}

.row-actions {
    display: flex;
    gap: 14px;
}

.text-button.danger {
    color: #d05a5a;
}

.text-button.danger:hover {
    color: #b83e3e;
}

.empty-row {
    color: #9aa3b5;
    text-align: center;
}
</style>
