<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { listChunks, type Chunk } from '@/api/rag/chunks'

const props = defineProps<{
    /** 所属文档 id */
    documentId: string
    /** 文档当前版本，仅拉取该版本的分块，避免混入历史版本 */
    documentVersion: number
}>()

// 分块树节点：携带层级深度，用于左侧缩进体现「父块 → 叶块」的归属
interface ChunkNode {
    chunk: Chunk
    depth: number
}

const loading = ref(false)
const nodes = ref<ChunkNode[]>([])

// 按 chunk_index 升序，保证同级顺序与原文一致
function sortByIndex(a: Chunk, b: Chunk) {
    return a.chunk_index - b.chunk_index
}

// 把扇平的 parent_chunk_id 列表组装为前序遍历的树：
// level 1 父块在前，其下 level 0 叶块紧随其后；父块缺失的叶块视为顶级。
function buildChunkTree(list: Chunk[]): ChunkNode[] {
    const idSet = new Set(list.map((c) => c.id))
    const childrenMap = new Map<string, Chunk[]>()
    const roots: Chunk[] = []
    for (const c of list) {
        if (c.parent_chunk_id && idSet.has(c.parent_chunk_id)) {
            const arr = childrenMap.get(c.parent_chunk_id)
            if (arr) arr.push(c)
            else childrenMap.set(c.parent_chunk_id, [c])
        } else {
            roots.push(c)
        }
    }
    roots.sort(sortByIndex)
    for (const arr of childrenMap.values()) arr.sort(sortByIndex)

    const result: ChunkNode[] = []
    const walk = (node: Chunk, depth: number) => {
        result.push({ chunk: node, depth })
        for (const child of childrenMap.get(node.id) ?? []) walk(child, depth + 1)
    }
    for (const root of roots) walk(root, 0)
    return result
}

async function loadChunks() {
    loading.value = true
    try {
        // 组装完整的父子树需要全量分块，一次性拉取（size 上限 200）
        const res = await listChunks({
            document_id: props.documentId,
            document_version: props.documentVersion,
            page: 1,
            size: 200,
        })
        nodes.value = buildChunkTree(res.data?.items ?? [])
    } finally {
        loading.value = false
    }
}

// 内容预览：折叠多余空白并截断，避免展开区过长
function preview(content: string) {
    const text = content.replace(/\s+/g, ' ').trim()
    return text.length > 160 ? `${text.slice(0, 160)}…` : text
}

watch(() => [props.documentId, props.documentVersion], loadChunks)
onMounted(loadChunks)
</script>

<template>
    <div class="chunk-tree" v-loading="loading" element-loading-text="加载分块…">
        <ul v-if="nodes.length" class="chunk-list">
            <li v-for="node in nodes" :key="node.chunk.id" class="chunk-item"
                :style="{ marginLeft: `${node.depth * 22}px` }">
                <span v-if="node.depth" class="chunk-branch" aria-hidden="true"></span>
                <span class="chunk-badge" :class="node.chunk.level === 1 ? 'parent' : 'leaf'">
                    {{ node.chunk.level === 1 ? '父块' : '叶块' }}
                </span>
                <span class="chunk-index">#{{ node.chunk.chunk_index }}</span>
                <div class="chunk-body">
                    <strong v-if="node.chunk.chapter_title" class="chunk-title">{{ node.chunk.chapter_title }}</strong>
                    <p class="chunk-content">{{ preview(node.chunk.content) }}</p>
                    <span class="chunk-meta">
                        <template v-if="node.chunk.token_count != null">{{ node.chunk.token_count }} tokens</template>
                        <template v-if="node.chunk.page_start != null"> · P{{ node.chunk.page_start
                            }}<template
                                v-if="node.chunk.page_end != null && node.chunk.page_end !== node.chunk.page_start">-{{
                                    node.chunk.page_end }}</template></template>
                    </span>
                </div>
            </li>
        </ul>
        <p v-else-if="!loading" class="chunk-empty">该文档暂无分块，请先完成解析与切块</p>
    </div>
</template>

<style scoped>
.chunk-tree {
    min-height: 40px;
    padding: 12px 8px;
    background: #fafbff
}

.chunk-list {
    display: grid;
    gap: 8px;
    margin: 0;
    padding: 0;
    list-style: none
}

.chunk-item {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 14px;
    border: 1px solid #e8ebf2;
    border-radius: 10px;
    background: #fff
}

/* 子块 L 形连接线，视觉上从父块「垂下」到当前叶块 */
.chunk-branch {
    position: absolute;
    top: -8px;
    left: -13px;
    width: 12px;
    height: 26px;
    border-left: 1.5px solid #d7ddec;
    border-bottom: 1.5px solid #d7ddec;
    border-bottom-left-radius: 6px
}

.chunk-badge {
    flex: 0 0 auto;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700
}

.chunk-badge.parent {
    color: #5a6bd6;
    background: #eef1ff
}

.chunk-badge.leaf {
    color: #328161;
    background: #eaf7f1
}

.chunk-index {
    flex: 0 0 auto;
    padding-top: 2px;
    color: #9aa3b5;
    font-size: 12px;
    font-weight: 600
}

.chunk-body {
    min-width: 0;
    flex: 1 1 auto
}

.chunk-title {
    display: block;
    margin-bottom: 4px;
    color: #364158;
    font-size: 13px
}

.chunk-content {
    margin: 0;
    color: #4d5970;
    font-size: 13px;
    line-height: 1.6;
    word-break: break-word
}

.chunk-meta {
    display: block;
    margin-top: 6px;
    color: #9aa3b5;
    font-size: 11px
}

.chunk-empty {
    margin: 0;
    padding: 8px;
    color: #9aa3b5;
    font-size: 13px;
    text-align: center
}
</style>
