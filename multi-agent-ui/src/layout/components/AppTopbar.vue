<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NAV_ICON_ASSET, type NavigationItem } from '@/router/navigation'
import SvgIcon from '@/components/SvgIcon.vue'

interface Props { sidebarCollapsed: boolean }
interface Emits { toggleSidebar: [] }
const props = defineProps<Props>()
const emit = defineEmits<Emits>()
const route = useRoute()

const menuButtonLabel = computed(() => (props.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'))
const currentLabel = computed(() => (route.meta as NavigationItem).label ?? '工作台')
const currentIcon = computed(() => NAV_ICON_ASSET[(route.meta as NavigationItem).icon] ?? '')
</script>

<template>
    <header class="app-topbar">
        <div class="topbar-leading">
            <button class="icon-button" type="button" :aria-label="menuButtonLabel" :title="menuButtonLabel"
                @click="emit('toggleSidebar')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                    <path d="M4 6h16M4 12h16M4 18h16" />
                </svg>
            </button>
            <nav class="breadcrumb" aria-label="面包屑">
                <RouterLink class="breadcrumb-home" to="/overview" aria-label="首页">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                        stroke-linejoin="round">
                        <path d="M3 10.5 12 3l9 7.5" />
                        <path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" />
                        <path d="M9.5 21v-6h5v6" />
                    </svg>
                </RouterLink>
                <span class="breadcrumb-sep" aria-hidden="true">/</span>
                <span class="breadcrumb-current">
                    <SvgIcon v-if="currentIcon" class="breadcrumb-icon" :name="currentIcon" :size="18" />
                    <strong>{{ currentLabel }}</strong>
                </span>
            </nav>
        </div>

        <div class="topbar-actions">
            <button class="icon-button" type="button" aria-label="全局搜索">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                    stroke-linejoin="round">
                    <circle cx="11" cy="11" r="7" />
                    <path d="m21 21-4.3-4.3" />
                </svg>
            </button>
            <button class="icon-button notification-button" type="button" aria-label="查看通知">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                    stroke-linejoin="round">
                    <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
                    <path d="M13.7 21a2 2 0 0 1-3.4 0" />
                </svg>
                <span class="notification-badge">12</span>
            </button>
            <span class="topbar-divider" aria-hidden="true"></span>
            <button class="profile" type="button" aria-label="账户菜单">
                <span class="profile-avatar" aria-hidden="true">A</span>
                <span class="profile-copy">
                    <strong>Admin</strong>
                    <small>超级管理员</small>
                </span>
                <span class="profile-chevron" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                        stroke-linejoin="round">
                        <path d="m6 9 6 6 6-6" />
                    </svg>
                </span>
            </button>
        </div>
    </header>
</template>

<style scoped>
.app-topbar {
    display: flex;
    min-height: 72px;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 0 28px;
    border-bottom: 1px solid #eef1f8;
    background: rgb(255 255 255 / 88%);
    backdrop-filter: blur(12px);
}

.topbar-leading,
.topbar-actions {
    display: flex;
    align-items: center;
    gap: 12px;
}

.icon-button {
    position: relative;
    display: grid;
    width: 40px;
    height: 40px;
    place-items: center;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 11px;
    color: #64708c;
    background: transparent;
    transition: border-color 150ms ease, background-color 150ms ease, color 150ms ease;
}

.icon-button svg {
    width: 20px;
    height: 20px;
}

.icon-button:hover {
    color: #4c6ef5;
    border-color: #e6ebf7;
    background: #f3f6ff;
}

.breadcrumb {
    display: flex;
    align-items: center;
    gap: 10px;
}

.breadcrumb-home {
    display: grid;
    width: 36px;
    height: 36px;
    place-items: center;
    border-radius: 10px;
    color: #4c6ef5;
    background: #eef2ff;
    text-decoration: none;
}

.breadcrumb-home svg {
    width: 19px;
    height: 19px;
}

.breadcrumb-sep {
    color: #cbd2e2;
    font-size: 14px;
}

.breadcrumb-current {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    color: #2f3a58;
    font-size: 15px;
    font-weight: 600;
}

.breadcrumb-icon {
    color: #4c6ef5;
}

.notification-badge {
    position: absolute;
    top: 4px;
    right: 4px;
    display: grid;
    min-width: 17px;
    height: 17px;
    place-items: center;
    padding: 0 4px;
    border: 2px solid #fff;
    border-radius: 9px;
    color: #fff;
    background: #f5455c;
    font-size: 10px;
    font-weight: 700;
    line-height: 1;
}

.topbar-divider {
    width: 1px;
    height: 26px;
    margin: 0 2px;
    background: #e9edf6;
}

.profile {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 48px;
    padding: 0 8px 0 6px;
    border: 1px solid transparent;
    border-radius: 12px;
    background: transparent;
    transition: background-color 150ms ease, border-color 150ms ease;
}

.profile:hover {
    border-color: #e6ebf7;
    background: #f5f7fd;
}

.profile-avatar {
    display: grid;
    width: 36px;
    height: 36px;
    flex: 0 0 auto;
    place-items: center;
    border-radius: 10px;
    color: #fff;
    background: linear-gradient(145deg, #5b8bff, #6c63ff);
    font-size: 15px;
    font-weight: 700;
}

.profile-copy {
    display: grid;
    gap: 1px;
    text-align: left;
    white-space: nowrap;
}

.profile-copy strong {
    color: #2f3a58;
    font-size: 13px;
    font-weight: 600;
}

.profile-copy small {
    color: #9aa4bd;
    font-size: 11px;
}

.profile-chevron {
    display: grid;
    place-items: center;
    color: #a6afc6;
}

.profile-chevron svg {
    width: 16px;
    height: 16px;
}

@media (max-width: 900px) {
    .app-topbar {
        padding: 0 18px;
    }
}

@media (max-width: 520px) {
    .app-topbar {
        padding: 0 12px;
    }

    .profile-copy {
        display: none;
    }
}
</style>
