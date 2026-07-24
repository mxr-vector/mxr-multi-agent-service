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
    display: grid;
    grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
    min-height: 100vh;
    background: linear-gradient(160deg, #eef1f8 0%, #f6f8fc 100%);
    transition: grid-template-columns 180ms ease;
}

.main-layout--collapsed {
    --sidebar-width: 78px;
}

.main-layout-content {
    display: flex;
    min-width: 0;
    flex-direction: column;
}

.main-layout-main {
    flex: 1;
    min-width: 0;
    padding: 0;
}

/* 页面内容直接铺满主区，紧贴侧边栏，无左右留白 */
.main-layout-main> :deep(*) {
    max-width: none;
    margin-inline: 0;
}

@media (max-width: 720px) {
    .main-layout {
        --sidebar-width: 78px;
    }

    .main-layout-main {
        padding: 0;
    }
}
</style>
