<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'

const isSidebarCollapsed = shallowRef(false)
const layoutClasses = computed(() => ({
    'main-layout': true,
    'main-layout--collapsed': isSidebarCollapsed.value,
}))
function toggleSidebar() { isSidebarCollapsed.value = !isSidebarCollapsed.value }
</script>

<template>
    <div :class="layoutClasses">
        <AppSidebar :collapsed="isSidebarCollapsed" />
        <section class="main-layout-content">
            <AppTopbar :sidebar-collapsed="isSidebarCollapsed" @toggle-sidebar="toggleSidebar" />
            <main class="main-layout-main">
                <RouterView />
            </main>
        </section>
    </div>
</template>

<style scoped>
.main-layout {
    --sidebar-width: 260px;
    --content-max-width: 1600px;
    --content-gap: 16px;
    display: grid;
    grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
    height: 100vh;
    overflow: hidden;
    background: linear-gradient(160deg, #eef1f8 0%, #f6f8fc 100%);
    transition: grid-template-columns 180ms ease;
}

.main-layout--collapsed {
    --sidebar-width: 78px;
}

/* 白色内容容器：承载顶栏与主内容，浮于渐变背景之上 */
.main-layout-content {
    display: flex;
    min-width: 0;
    flex-direction: column;
    margin: var(--content-gap) var(--content-gap) var(--content-gap) 0;
    overflow: hidden;
    background: #fff;
    border: 1px solid #e8ebf2;
    border-radius: 16px;
    box-shadow: 0 18px 40px rgb(37 50 82 / 7%);
}

.main-layout-main {
    flex: 1;
    min-height: 0;
    min-width: 0;
    padding: 24px 28px;
    overflow-y: auto;
}

/* 页面内容铺满白色容器内部，无额外左右留白 */
.main-layout-main> :deep(*) {
    max-width: none;
    margin-inline: 0;
}

@media (max-width: 720px) {
    .main-layout {
        --sidebar-width: 78px;
        --content-gap: 10px;
    }

    .main-layout-main {
        padding: 16px 14px;
    }
}
</style>
