<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
    listDocuments,
    uploadDocument,
    vectorizeDocument,
    type RagDocument,
} from '@/api/rag/document'
import { listKnowledgeBases, type KnowledgeBase } from '@/api/rag/knowledgeBase'
import DocumentUploader from '@/components/rag/DocumentUploader.vue'
import DocumentTable from '@/components/rag/DocumentTable.vue'
import Pagination from '@/components/rag/Pagination.vue'

const loading = ref(false)
const uploading = ref(false)
const vectorizingId = ref<string | null>(null)
const documents = ref<RagDocument[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const selectedKbId = ref<string | null>(null)
const statusFilter = ref('')

// 分页状态（服务端分页）
const page = ref(1)
const size = ref(20)
const total = ref(0)

const uploaderRef = ref<InstanceType<typeof DocumentUploader>>()

const statusOptions = [
    { label: '全部状态', value: '' },
    { label: '待处理', value: 'pending' },
    { label: '已完成', value: 'active' },
    { label: '向量化中', value: 'reindexing' },
]

// 按状态服务端过滤（下拉选项）
async function loadKnowledgeBases() {
    const res = await listKnowledgeBases()
    knowledgeBases.value = res.data?.items ?? []
    if (!selectedKbId.value && knowledgeBases.value.length) {
        selectedKbId.value = knowledgeBases.value[0].id
    }
}

async function loadDocuments() {
    if (!selectedKbId.value) {
        documents.value = []
        total.value = 0
        return
    }
    loading.value = true
    try {
        const res = await listDocuments({
            knowledge_base_id: selectedKbId.value,
            page: page.value,
            size: size.value,
            status: statusFilter.value || undefined,
        })
        documents.value = res.data?.items ?? []
        total.value = res.data?.total ?? 0
    } finally {
        loading.value = false
    }
}

function triggerUpload() {
    uploaderRef.value?.open()
}

function onBlocked() {
    ElMessage.warning('请先选择目标知识库')
}

async function onFileSelected(file: File) {
    if (!selectedKbId.value) return
    uploading.value = true
    try {
        await uploadDocument({ file, knowledge_base_id: selectedKbId.value })
        ElMessage.success('上传成功，已完成解析与切块')
        await loadDocuments()
    } finally {
        uploading.value = false
    }
}

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

// 切换知识库或状态过滤：回到第 1 页并重新拉取
watch([selectedKbId, statusFilter], () => {
    page.value = 1
    loadDocuments()
})

onMounted(async () => {
    await loadKnowledgeBases()
    await loadDocuments()
})
</script>

<template>
    <section class="document-page" v-loading="loading" element-loading-text="加载中…">
        <header class="page-header">
            <div>
                <p class="eyebrow">RAG SYSTEM / DOCUMENTS</p>
                <h1>文档管理</h1>
                <p>将文档导入知识库，并跟踪解析与向量化状态。</p>
            </div><button class="primary-button" type="button" :disabled="uploading" @click="triggerUpload">{{ uploading
                ? '上传中…' : '上传文档' }}</button>
        </header>
        <DocumentUploader ref="uploaderRef" :uploading="uploading" :disabled="!selectedKbId" @blocked="onBlocked"
            @file-selected="onFileSelected" />
        <section class="content-card">
            <div class="toolbar">
                <div>
                    <h2>全部文档</h2><span>共 {{ total }} 份文档</span>
                </div>
                <div class="filters">
                    <el-select v-model="selectedKbId" placeholder="选择知识库" style="width: 200px">
                        <el-option v-for="b in knowledgeBases" :key="b.id" :label="b.name" :value="b.id" />
                    </el-select>
                    <el-select v-model="statusFilter" style="width: 140px">
                        <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
                    </el-select>
                </div>
            </div>
            <DocumentTable :documents="documents" :knowledge-bases="knowledgeBases" :vectorizing-id="vectorizingId"
                @vectorize="handleVectorize" />
            <div class="pagination-bar">
                <Pagination v-model:page="page" v-model:size="size" :total="total" @change="loadDocuments" />
            </div>
        </section>
    </section>
</template>

<style scoped>
.document-page {
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

.primary-button:disabled {
    opacity: .6;
    cursor: not-allowed
}

.content-card {
    overflow: hidden;
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%)
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

.toolbar span {
    color: #7d879a;
    font-size: 12px
}

.filters {
    display: flex;
    gap: 8px
}

@media(max-width:720px) {

    .page-header,
    .toolbar {
        align-items: flex-start;
        flex-direction: column
    }

    .filters {
        width: 100%
    }
}
</style>
