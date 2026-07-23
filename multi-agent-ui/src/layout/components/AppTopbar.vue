<script setup lang="ts">
import { computed } from 'vue'

interface Props { sidebarCollapsed: boolean }
interface Emits { toggleSidebar: [] }
const props = defineProps<Props>()
const emit = defineEmits<Emits>()
const menuButtonLabel = computed(() => props.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏')
</script>

<template>
    <header class="app-topbar">
        <div class="topbar-leading"><button class="icon-button" type="button" :aria-label="menuButtonLabel"
                :title="menuButtonLabel" @click="emit('toggleSidebar')"><span aria-hidden="true">☰</span></button>
            <div class="breadcrumb"><span>工作区</span><span aria-hidden="true">/</span><strong>产品团队</strong></div>
        </div>
        <div class="topbar-actions"><label class="search-box"><span aria-hidden="true">⌕</span><input
                    placeholder="搜索智能体、任务或会话" aria-label="全局搜索" /><kbd>⌘ K</kbd></label><button
                class="icon-button notification-button" type="button" aria-label="查看通知"><span
                    aria-hidden="true">♧</span><span class="notification-dot"></span></button><button
                class="create-button" type="button"><span aria-hidden="true">＋</span>新建</button></div>
    </header>
</template>

<style scoped>
.app-topbar {
    display: flex;
    min-height: 76px;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 0 32px;
    border-bottom: 1px solid #e9ecf3;
    background: rgb(255 255 255 / 86%);
    backdrop-filter: blur(12px);
}

.topbar-leading,
.topbar-actions {
    display: flex;
    align-items: center;
    gap: 15px;
}

.icon-button {
    position: relative;
    display: grid;
    width: 36px;
    height: 36px;
    place-items: center;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 9px;
    color: #56617a;
    background: transparent;
    font-size: 19px;
    transition: border-color 150ms ease, background-color 150ms ease;
}

.icon-button:hover {
    border-color: #e2e6f0;
    background: #f4f6fa;
}

.breadcrumb {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #9aa3b5;
    font-size: 13px;
}

.breadcrumb strong {
    color: #374157;
    font-weight: 600;
}

.search-box {
    display: flex;
    width: min(300px, 28vw);
    height: 37px;
    align-items: center;
    gap: 8px;
    padding: 0 10px;
    border: 1px solid #e4e8f0;
    border-radius: 9px;
    color: #8d97aa;
    background: #fafbfc;
}

.search-box input {
    width: 100%;
    min-width: 0;
    border: 0;
    outline: 0;
    color: #344056;
    background: transparent;
    font-size: 12px;
}

.search-box input::placeholder {
    color: #aab2c2;
}

.search-box kbd {
    padding: 2px 4px;
    border: 1px solid #e5e8ef;
    border-radius: 4px;
    color: #a5adbd;
    background: #fff;
    font-family: inherit;
    font-size: 10px;
    white-space: nowrap;
}

.notification-dot {
    position: absolute;
    top: 7px;
    right: 7px;
    width: 6px;
    height: 6px;
    border: 1px solid #fff;
    border-radius: 50%;
    background: #5e77ee;
}

.create-button {
    display: inline-flex;
    height: 36px;
    align-items: center;
    gap: 3px;
    padding: 0 13px;
    border: 0;
    border-radius: 8px;
    color: #fff;
    background: #526ae2;
    box-shadow: 0 5px 12px rgb(82 106 226 / 22%);
    font-size: 13px;
    font-weight: 600;
}

@media (max-width: 900px) {
    .app-topbar {
        padding: 0 20px;
    }

    .search-box {
        display: none;
    }
}

@media (max-width: 520px) {
    .breadcrumb {
        display: none;
    }

    .app-topbar {
        padding: 0 12px;
    }
}
</style>
