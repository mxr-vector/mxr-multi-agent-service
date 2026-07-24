<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'

// RAG 各列表页共用的服务端分页控件：统一布局、每页选项与中文文案（共 X 条 / X条/页）。
const props = withDefaults(
    defineProps<{
        page: number
        size: number
        total: number
        pageSizes?: number[]
    }>(),
    {
        pageSizes: () => [10, 20, 50, 100],
    }
)

const emit = defineEmits<{
    (e: 'update:page', value: number): void
    (e: 'update:size', value: number): void
    (e: 'change'): void
}>()

// 翻页：更新页码后通知外层重新拉取
function onCurrentChange(next: number) {
    emit('update:page', next)
    emit('change')
}

// 改每页数量：重置到第 1 页，保持与后端真分页一致
function onSizeChange(next: number) {
    emit('update:size', next)
    emit('update:page', 1)
    emit('change')
}
</script>

<template>
    <el-config-provider :locale="zhCn">
        <el-pagination background layout="total, sizes, prev, pager, next" :total="props.total"
            :current-page="props.page" :page-size="props.size" :page-sizes="props.pageSizes"
            @current-change="onCurrentChange" @size-change="onSizeChange" />
    </el-config-provider>
</template>
