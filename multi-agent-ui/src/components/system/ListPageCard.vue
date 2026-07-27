<script setup lang="ts">
// 系统管理列表页通用卡片骨架：工具栏（标题/副标题 + 操作区）+ 内容区 + 可选分页底栏。
// 配合全局 layout.css 的 list-panel/list-scroll/list-footer 高度链使用：
// 默认插槽放 el-table（自带 list-scroll 类），footer 插槽放 Pagination。
withDefaults(
    defineProps<{
        title?: string;
        subtitle?: string;
        loading?: boolean;
    }>(),
    { title: "", subtitle: "", loading: false }
);
</script>

<template>
    <section class="content-card list-panel" :class="{ 'no-footer': !$slots.footer }" v-loading="loading"
        element-loading-text="加载中…">
        <div class="toolbar">
            <!-- title 插槽用于自定义标题区（如钻取视图的返回按钮） -->
            <slot name="title">
                <div>
                    <h2>{{ title }}</h2>
                    <span class="subtitle">{{ subtitle }}</span>
                </div>
            </slot>
            <div class="toolbar-actions">
                <slot name="actions" />
            </div>
        </div>
        <slot />
        <div v-if="$slots.footer" class="pagination-bar list-footer">
            <slot name="footer" />
        </div>
    </section>
</template>

<style scoped>
.content-card {
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

/* 无分页底栏时留出内容与卡片底边的呼吸空间 */
.content-card.no-footer {
    padding-bottom: 8px;
}

.toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 19px 20px;
    border-bottom: 1px solid #edf0f5;
}

.toolbar-actions {
    display: flex;
    align-items: center;
    gap: 12px;
}

h2 {
    margin: 0 0 4px;
    font-size: 16px;
}

.subtitle {
    color: #7d879a;
    font-size: 12px;
}

.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 16px 20px;
    border-top: 1px solid #edf0f5;
}
</style>
