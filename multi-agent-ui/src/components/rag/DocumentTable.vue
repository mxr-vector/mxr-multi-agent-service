<script setup lang="ts">
import type { RagDocument } from '@/api/rag/document'
import type { KnowledgeBase } from '@/api/rag/knowledgeBase'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
    documents: RagDocument[]
    knowledgeBases: KnowledgeBase[]
    vectorizingId: string | null
}>()

defineEmits<{
    (e: 'vectorize', doc: RagDocument): void
}>()

// 状态文案映射（后端：pending/active/reindexing/deleted）
const statusText: Record<string, string> = {
    pending: '待处理',
    active: '已完成',
    reindexing: '向量化中',
    deleted: '已删除',
}
function statusLabel(status: string) {
    return statusText[status] ?? status
}

function kbName(kbId: string) {
    return props.knowledgeBases.find((b) => b.id === kbId)?.name ?? '—'
}
</script>

<template>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th>文档</th>
                    <th>所属知识库</th>
                    <th>类型</th>
                    <th>版本</th>
                    <th>更新时间</th>
                    <th>状态</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                <tr v-for="document in documents" :key="document.id">
                    <td><strong>{{ document.title || document.source_uri || document.id }}</strong></td>
                    <td>{{ kbName(document.knowledge_base_id) }}</td>
                    <td>{{ document.doc_type || '—' }}</td>
                    <td>v{{ document.version }}</td>
                    <td>{{ formatDateTime(document.updated_at) }}</td>
                    <td><em
                            :class="{ parsing: document.status === 'reindexing', pending: document.status === 'pending' }">{{
                                statusLabel(document.status) }}</em></td>
                    <td>
                        <button class="text-button" type="button" :disabled="vectorizingId === document.id"
                            @click="$emit('vectorize', document)">{{ vectorizingId === document.id ? '处理中…' : '向量化'
                            }}</button>
                    </td>
                </tr>
                <tr v-if="!documents.length">
                    <td colspan="7" class="empty-row">暂无文档</td>
                </tr>
            </tbody>
        </table>
    </div>
</template>

<style scoped>
.table-wrap {
    overflow-x: auto
}

table {
    width: 100%;
    border-collapse: collapse;
    text-align: left
}

th,
td {
    padding: 16px 20px;
    border-bottom: 1px solid #f0f2f6;
    color: #4d5970;
    font-size: 13px;
    white-space: nowrap
}

th {
    color: #8993a5;
    font-size: 11px;
    font-weight: 600
}

tbody tr {
    transition: background-color 150ms ease
}

tbody tr:hover {
    background: #f7f9ff
}

tbody tr:last-child td {
    border-bottom: 0
}

td strong {
    color: #364158
}

em {
    padding: 4px 8px;
    border-radius: 99px;
    color: #328161;
    background: #eaf7f1;
    font-size: 11px;
    font-style: normal
}

em.parsing {
    color: #a86d19;
    background: #fff4df
}

em.pending {
    color: #6e7890;
    background: #edf0f5
}

.text-button {
    border: 0;
    color: #526ae2;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: color 150ms ease
}

.text-button:not(:disabled):hover {
    color: #3550c9
}

.text-button:disabled {
    color: #9aa3b5;
    cursor: not-allowed
}

.empty-row {
    color: #9aa3b5;
    text-align: center
}
</style>
