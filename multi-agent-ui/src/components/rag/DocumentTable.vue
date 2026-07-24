<script setup lang="ts">
import { ref } from 'vue'
import type { RagDocument } from '@/api/rag/document'
import type { KnowledgeBase } from '@/api/rag/knowledgeBase'
import { formatDateTime } from '@/utils/format'
import { resolveFileIcon } from '@/utils/fileIcon'
import SvgIcon from '@/components/SvgIcon.vue'
import DocumentChunkTree from '@/components/rag/DocumentChunkTree.vue'

const props = defineProps<{
    documents: RagDocument[]
    knowledgeBases: KnowledgeBase[]
    vectorizingId: string | null
}>()

defineEmits<{
    (e: 'vectorize', doc: RagDocument): void
}>()

// 已展开的文档 id 集合（支持同时展开多行）；点击文档行向下拓展其分块详情
const expandedIds = ref<Set<string>>(new Set())

function toggleExpand(doc: RagDocument) {
    const next = new Set(expandedIds.value)
    if (next.has(doc.id)) next.delete(doc.id)
    else next.add(doc.id)
    expandedIds.value = next
}

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

function fileIcon(doc: RagDocument) {
    return resolveFileIcon(doc)
}
</script>

<template>
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th class="expand-col"></th>
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
                <template v-for="document in documents" :key="document.id">
                    <tr class="doc-row" :class="{ 'is-expanded': expandedIds.has(document.id) }"
                        @click="toggleExpand(document)">
                        <td class="expand-col">
                            <span class="expand-caret" :class="{ open: expandedIds.has(document.id) }"
                                aria-hidden="true">›</span>
                        </td>
                        <td>
                            <div class="doc-cell">
                                <SvgIcon class="doc-icon" :name="fileIcon(document).name"
                                    :colored="fileIcon(document).colored" :size="24" />
                                <strong>{{ document.title || document.source_uri || document.id }}</strong>
                            </div>
                        </td>
                        <td>{{ kbName(document.knowledge_base_id) }}</td>
                        <td>{{ document.doc_type || '—' }}</td>
                        <td>v{{ document.version }}</td>
                        <td>{{ formatDateTime(document.updated_at) }}</td>
                        <td><em
                                :class="{ parsing: document.status === 'reindexing', pending: document.status === 'pending' }">{{
                                    statusLabel(document.status) }}</em></td>
                        <td>
                            <button class="text-button" type="button" :disabled="vectorizingId === document.id"
                                @click.stop="$emit('vectorize', document)">{{ vectorizingId === document.id ? '处理中…' :
                                    '向量化' }}</button>
                        </td>
                    </tr>
                    <tr v-if="expandedIds.has(document.id)" class="detail-row">
                        <td :colspan="8">
                            <DocumentChunkTree :document-id="document.id" :document-version="document.version" />
                        </td>
                    </tr>
                </template>
                <tr v-if="!documents.length">
                    <td colspan="8" class="empty-row">暂无文档</td>
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

.doc-row {
    cursor: pointer
}

tbody tr:hover {
    background: #f7f9ff
}

.doc-row.is-expanded {
    background: #f2f5ff
}

/* 展开箭头列：紧凑宽度，箭头随展开状态旋转 90° */
.expand-col {
    width: 36px;
    padding-right: 0;
    text-align: center
}

.expand-caret {
    display: inline-block;
    color: #9aa3b5;
    font-size: 16px;
    font-weight: 700;
    transition: transform 150ms ease
}

.expand-caret.open {
    transform: rotate(90deg);
    color: #526ae2
}

/* 分块详情行：整行铺满，去除内边距交由子组件控制 */
.detail-row>td {
    padding: 0;
    background: #fafbff
}

.detail-row:hover {
    background: #fafbff
}

tbody tr:last-child td {
    border-bottom: 0
}

td strong {
    color: #364158;
}

.doc-cell {
    display: flex;
    align-items: center;
    gap: 10px;
}

.doc-icon {
    flex: 0 0 auto;
    color: #8993a5;
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
