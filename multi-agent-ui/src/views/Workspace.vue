<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { NavigationItem } from '@/router/navigation'

const route = useRoute()
const page = computed(() => route.meta as unknown as NavigationItem)
const highlights = computed(() => [
    { label: '运行中的智能体', value: '12', trend: '+18%' },
    { label: '本周已完成任务', value: '248', trend: '+12%' },
    { label: '平均响应时间', value: '1.8s', trend: '−0.4s' },
])
</script>

<template>
    <section class="workspace-view">
        <div class="page-actions">
            <button class="primary-action" type="button"><span aria-hidden="true">＋</span>创建{{ page.label
                }}</button>
        </div>
        <div class="highlight-grid">
            <article v-for="highlight in highlights" :key="highlight.label" class="highlight-card">
                <p>{{ highlight.label }}</p><strong>{{ highlight.value }}</strong><span>{{ highlight.trend }} 较上周</span>
            </article>
        </div>
        <article class="empty-state"><span class="empty-state-icon" aria-hidden="true">{{ page.icon }}</span>
            <div>
                <h2>{{ page.label }}已准备就绪</h2>
                <p>这是静态路由的内容区域。接入接口后，可以在这里展示真实的业务数据。</p>
            </div><button type="button" class="secondary-action">查看示例</button>
        </article>
    </section>
</template>

<style scoped>
.workspace-view {
    display: grid;
    gap: 22px;
}

.page-actions {
    display: flex;
    justify-content: flex-end;
}

.eyebrow {
    margin: 0 0 8px;
    color: #7b89b9;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.15px;
}

.page-heading h1 {
    margin: 0;
    color: #1f293b;
    font-size: clamp(26px, 3vw, 34px);
    letter-spacing: -1px;
}

.page-description {
    margin: 10px 0 0;
    color: #788397;
    font-size: 14px;
}

.primary-action,
.secondary-action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 600;
}

.primary-action {
    min-height: 40px;
    padding: 0 15px;
    border: 0;
    color: #fff;
    background: #526ae2;
    box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
}

.highlight-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
}

.highlight-card {
    display: grid;
    gap: 8px;
    padding: 21px;
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.highlight-card p,
.highlight-card span {
    margin: 0;
    color: #7d879a;
    font-size: 12px;
}

.highlight-card strong {
    color: #273249;
    font-size: 28px;
    letter-spacing: -1px;
}

.highlight-card span {
    color: #4eab83;
}

.empty-state {
    display: flex;
    min-height: 250px;
    align-items: center;
    gap: 18px;
    padding: 30px;
    border: 1px dashed #d9dfec;
    border-radius: 14px;
    background: linear-gradient(135deg, #fff, #fafbff);
}

.empty-state-icon {
    display: grid;
    width: 52px;
    height: 52px;
    flex: 0 0 auto;
    place-items: center;
    border-radius: 14px;
    color: #6278db;
    background: #edf0ff;
    font-size: 25px;
}

.empty-state h2 {
    margin: 0;
    color: #303b50;
    font-size: 16px;
}

.empty-state p {
    max-width: 540px;
    margin: 8px 0 0;
    color: #818b9d;
    font-size: 13px;
    line-height: 1.65;
}

.secondary-action {
    min-height: 36px;
    margin-left: auto;
    padding: 0 13px;
    border: 1px solid #dfe4ef;
    color: #59657b;
    background: #fff;
    white-space: nowrap;
}

@media (max-width: 800px) {
    .highlight-grid {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 560px) {

    .empty-state {
        align-items: flex-start;
        flex-direction: column;
    }

    .secondary-action {
        margin-left: 0;
    }
}
</style>
