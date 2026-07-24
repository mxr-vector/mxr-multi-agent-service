<script setup lang="ts">
import { computed } from 'vue'
import type { RagDocument } from '@/api/rag/document'
import { resolveFileIcon } from '@/utils/fileIcon'
import SvgIcon from '@/components/SvgIcon.vue'

const props = defineProps<{
    document: RagDocument
    /** 该卡片是否正在向量化（禁用重复触发） */
    vectorizing: boolean
}>()

const emit = defineEmits<{
    (e: 'open', doc: RagDocument): void
    (e: 'vectorize', doc: RagDocument): void
    (e: 'view-chunks', doc: RagDocument): void
}>()

// 文档 status -> 同步状态圆点（与顶部图例保持一致）
const SYNC_MAP: Record<string, { label: string; cls: string }> = {
    pending: { label: '未同步', cls: 'pending' },
    reindexing: { label: '同步中', cls: 'syncing' },
    active: { label: '已同步', cls: 'synced' },
    failed: { label: '同步失败', cls: 'failed' },
}
const sync = computed(() => SYNC_MAP[props.document.status] ?? SYNC_MAP.pending)

const fileIcon = computed(() => resolveFileIcon(props.document))

const title = computed(
    () => props.document.title || props.document.source_uri || props.document.id,
)

// 有效期展示：仅取日期部分（YYYY-MM-DD）
const validDate = computed(() => {
    const v = props.document.valid_until
    if (!v) return ''
    const d = new Date(v)
    return Number.isNaN(d.getTime()) ? '' : v.slice(0, 10)
})

// 即将过期：valid_until 落在「未来 30 天内」或已过期时角标提示
const expiring = computed(() => {
    const v = props.document.valid_until
    if (!v) return false
    const until = new Date(v).getTime()
    if (Number.isNaN(until)) return false
    return until - Date.now() <= 30 * 24 * 3600 * 1000
})

function handleCommand(command: string) {
    if (command === 'vectorize') emit('vectorize', props.document)
    else if (command === 'chunks') emit('view-chunks', props.document)
}
</script>

<template>
    <article class="doc-card" :class="{ expiring }" @click="emit('open', document)">
        <!-- 即将过期角标：右上角斜向色带 -->
        <span v-if="expiring" class="ribbon">即将过期</span>

        <!-- 同步状态圆点：左上角 -->
        <span class="sync-dot" :class="sync.cls" :title="sync.label"></span>

        <div class="icon-wrap">
            <SvgIcon :name="fileIcon.name" :colored="fileIcon.colored" :size="46" />
        </div>

        <h3 class="doc-title" :title="title">{{ title }}</h3>

        <div class="doc-foot" @click.stop>
            <span class="doc-date">{{ validDate }}</span>
            <el-dropdown trigger="click" @command="handleCommand">
                <button type="button" class="more-btn" aria-label="更多操作">···</button>
                <template #dropdown>
                    <el-dropdown-menu>
                        <el-dropdown-item command="vectorize" :disabled="vectorizing">
                            {{ vectorizing ? '处理中…' : '向量化' }}
                        </el-dropdown-item>
                        <el-dropdown-item command="chunks">查看分块</el-dropdown-item>
                    </el-dropdown-menu>
                </template>
            </el-dropdown>
        </div>
    </article>
</template>

<style scoped>
.doc-card {
    position: relative;
    display: flex;
    width: 150px;
    height: 168px;
    flex-direction: column;
    align-items: center;
    padding: 16px 12px 8px;
    overflow: hidden;
    border: 1px solid #e8ebf2;
    border-radius: 10px;
    background: #fff;
    box-shadow: 0 4px 12px rgb(43 56 86 / 3%);
    cursor: pointer;
    transition: border-color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
}

.doc-card:hover {
    border-color: #d3dbf5;
    box-shadow: 0 10px 22px rgb(43 56 86 / 8%);
    transform: translateY(-2px);
}

/* 同步状态圆点 */
.sync-dot {
    position: absolute;
    top: 10px;
    left: 10px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #c2c9d6;
}

.sync-dot.pending {
    background: #c2c9d6;
}

.sync-dot.syncing {
    background: #e6a23c;
}

.sync-dot.synced {
    background: #3fa77b;
}

.sync-dot.failed {
    background: #e0637a;
}

/* 即将过期角标：右上角 45° 色带 */
.ribbon {
    position: absolute;
    top: 12px;
    right: -34px;
    width: 120px;
    padding: 2px 0;
    color: #fff;
    background: linear-gradient(135deg, #f0a04b, #e8823c);
    font-size: 11px;
    text-align: center;
    transform: rotate(45deg);
    pointer-events: none;
}

.icon-wrap {
    display: grid;
    flex: 0 0 auto;
    place-items: center;
    width: 56px;
    height: 56px;
    margin-top: 8px;
    color: #8993a5;
}

.doc-title {
    display: -webkit-box;
    width: 100%;
    margin: 12px 0 0;
    overflow: hidden;
    color: #3a465c;
    font-size: 13px;
    font-weight: 500;
    line-height: 1.4;
    text-align: center;
    text-overflow: ellipsis;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
}

.doc-foot {
    display: flex;
    width: 100%;
    height: 22px;
    margin-top: auto;
    align-items: center;
    justify-content: space-between;
}

.doc-date {
    color: #9aa3b5;
    font-size: 11px;
}

.more-btn {
    padding: 0 4px;
    border: 0;
    color: #9aa3b5;
    background: transparent;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    line-height: 1;
    cursor: pointer;
    transition: color 150ms ease;
}

.more-btn:hover {
    color: #526ae2;
}
</style>
