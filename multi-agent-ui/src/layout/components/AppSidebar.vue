<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { navigationItems, type NavigationItem } from '@/router/navigation'

interface Props { collapsed: boolean }
const props = defineProps<Props>()
const route = useRoute()
const expandedItemNames = ref<string[]>(['rag'])

const items = computed<readonly NavigationItem[]>(() => navigationItems)

function isExpanded(name: string) { return expandedItemNames.value.includes(name) }
function toggleChildren(name: string) {
    expandedItemNames.value = isExpanded(name)
        ? expandedItemNames.value.filter((itemName) => itemName !== name)
        : [...expandedItemNames.value, name]
}
function hasActiveChild(path: string) { return route.path.startsWith(`${path}/`) }

/** 线性图标集合，键与 navigation.ts 中的 icon 字段对应。 */
const icons: Record<string, string> = {
    dashboard: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/>',
    chat: '<path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.4 8.4 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.4 8.4 0 0 1 21 11.5Z"/>',
    workflow: '<rect x="3" y="4" width="6" height="6" rx="1.6"/><rect x="15" y="14" width="6" height="6" rx="1.6"/><path d="M9 7h5a4 4 0 0 1 4 4v3"/>',
    rag: '<path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="M3 12l9 5 9-5"/><path d="M3 16.5l9 5 9-5"/>',
    knowledge: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19a1 1 0 0 1 1 1v13.5H6.5A1.5 1.5 0 0 0 5 19V4.5Z"/><path d="M5 19a1.5 1.5 0 0 0 1.5 1.5H20"/>',
    category: '<path d="M20.6 13.4 12 22l-9-9V3h10l7.6 7.6a1.9 1.9 0 0 1 0 2.8Z"/><circle cx="7.8" cy="7.8" r="1.4"/>',
    document: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    agent: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M9 12h.01M15 12h.01"/><path d="M12 3v4M8 19v2M16 19v2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.8l-.1-.1a1.7 1.7 0 0 0-2.8 1.2V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 6 19.7a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.9l.1-.1a1.7 1.7 0 0 0-1.2-2.8H2a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 3.3 6a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.8l.1.1A1.7 1.7 0 0 0 8 2.3h.1A1.7 1.7 0 0 0 9.3 1 2 2 0 0 1 13 1v.1A1.7 1.7 0 0 0 15.9 3l.1-.1a2 2 0 1 1 2.8 2.9l-.1.1a1.7 1.7 0 0 0 1.2 2.8H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1.2Z"/>',
}
</script>

<template>
    <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': props.collapsed }">
        <RouterLink class="brand" to="/overview" aria-label="多智能体测试平台首页">
            <span class="brand-mark" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
                    stroke-linejoin="round">
                    <path d="M12 3 4 6.5v6c0 4.4 3.4 7.6 8 8.5 4.6-.9 8-4.1 8-8.5v-6L12 3Z" />
                    <path d="M9 12l2 2 4-4" />
                </svg>
            </span>
            <span class="brand-copy">
                <strong>多智能体测试平台</strong>
                <small>Multi-Agent Test Platform</small>
            </span>
        </RouterLink>

        <nav class="navigation" aria-label="主导航">
            <template v-for="item in items" :key="item.name">
                <div v-if="item.children?.length" class="navigation-parent">
                    <button class="navigation-link navigation-parent-trigger"
                        :class="{ 'navigation-link--active': hasActiveChild(item.path) }" type="button"
                        :title="props.collapsed ? item.label : undefined" :aria-expanded="isExpanded(item.name)"
                        @click="toggleChildren(item.name)">
                        <span class="navigation-icon" aria-hidden="true" v-html="icons[item.icon]"></span>
                        <span class="navigation-text">{{ item.label }}</span>
                        <span class="navigation-chevron" aria-hidden="true">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                                stroke-linecap="round" stroke-linejoin="round">
                                <path d="m6 9 6 6 6-6" />
                            </svg>
                        </span>
                    </button>
                    <div v-show="isExpanded(item.name) && !props.collapsed" class="navigation-children">
                        <RouterLink v-for="child in item.children" :key="child.name" :to="child.path"
                            class="navigation-child-link">
                            <span class="navigation-child-dot" aria-hidden="true"></span>{{ child.label }}
                        </RouterLink>
                    </div>
                </div>
                <RouterLink v-else :to="item.path" class="navigation-link"
                    :title="props.collapsed ? item.label : undefined">
                    <span class="navigation-icon" aria-hidden="true" v-html="icons[item.icon]"></span>
                    <span class="navigation-text">{{ item.label }}</span>
                </RouterLink>
            </template>
        </nav>

        <div class="promo">
            <div class="promo-art" aria-hidden="true">
                <span class="promo-cube promo-cube--1">AI</span>
                <span class="promo-cube promo-cube--2">AI</span>
                <span class="promo-cube promo-cube--3">AI</span>
            </div>
            <strong class="promo-title">构建 · 测试 · 优化</strong>
            <span class="promo-sub">让智能体应用更高效</span>
        </div>
        <RouterLink class="promo-button" to="/conversations">
            <span aria-hidden="true">＋</span>
            <span class="promo-button-text">创建会话</span>
        </RouterLink>
    </aside>
</template>

<style scoped>
.app-sidebar {
    position: sticky;
    top: 0;
    display: flex;
    height: 100vh;
    flex-direction: column;
    overflow: hidden;
    padding: 20px 16px 18px;
    color: #4a5675;
    background: linear-gradient(180deg, #ffffff 0%, #f4f7ff 100%);
    border-right: 1px solid #eef1f8;
    transition: padding 180ms ease;
}

.brand {
    display: flex;
    align-items: center;
    gap: 11px;
    min-width: 0;
    padding: 4px 8px 22px;
    color: inherit;
    text-decoration: none;
}

.brand-mark {
    display: grid;
    width: 38px;
    height: 38px;
    flex: 0 0 auto;
    place-items: center;
    border-radius: 12px;
    color: #fff;
    background: linear-gradient(135deg, #5b8bff, #6c63ff);
    box-shadow: 0 8px 20px rgb(91 139 255 / 32%);
}

.brand-mark svg {
    width: 21px;
    height: 21px;
}

.brand-copy {
    display: grid;
    min-width: 0;
    gap: 2px;
    white-space: nowrap;
}

.brand-copy strong {
    color: #1f2a44;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -.2px;
}

.brand-copy small {
    color: #9aa4bd;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: .3px;
}

.navigation {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 4px;
    overflow-y: auto;
    padding-top: 4px;
}

.navigation-link {
    display: flex;
    width: 100%;
    align-items: center;
    gap: 12px;
    min-height: 46px;
    padding: 0 12px;
    border: 0;
    border-radius: 11px;
    color: #5b6684;
    background: transparent;
    text-align: left;
    text-decoration: none;
    transition: background-color 150ms ease, color 150ms ease;
}

.navigation-link:hover {
    color: #2f3a58;
    background: #eef2ff;
}

.navigation-link.router-link-active,
.navigation-link--active {
    color: #4c6ef5;
    background: linear-gradient(90deg, #e8edff, #eef2ff);
    font-weight: 600;
}

.navigation-parent-trigger[aria-expanded='true'] {
    color: #2f3a58;
}

.navigation-chevron {
    display: grid;
    margin-left: auto;
    place-items: center;
    color: #a6afc6;
    transition: transform 180ms ease;
}

.navigation-chevron svg {
    width: 16px;
    height: 16px;
}

.navigation-parent-trigger[aria-expanded='true'] .navigation-chevron {
    transform: rotate(180deg);
}

.navigation-children {
    display: grid;
    gap: 2px;
    margin: 2px 0 4px 24px;
    padding-left: 14px;
    border-left: 1.5px solid #e4e9f5;
}

.navigation-child-link {
    display: flex;
    align-items: center;
    gap: 9px;
    min-height: 38px;
    padding: 0 10px;
    border-radius: 9px;
    color: #7b86a3;
    font-size: 13px;
    text-decoration: none;
    transition: background-color 150ms ease, color 150ms ease;
}

.navigation-child-link:hover {
    color: #2f3a58;
    background: #eef2ff;
}

.navigation-child-link.router-link-active {
    color: #4c6ef5;
    font-weight: 600;
}

.navigation-child-dot {
    width: 5px;
    height: 5px;
    flex: 0 0 auto;
    border-radius: 50%;
    background: currentcolor;
    opacity: .55;
}

.navigation-child-link.router-link-active .navigation-child-dot {
    opacity: 1;
}

.navigation-icon {
    display: grid;
    width: 22px;
    height: 22px;
    flex: 0 0 22px;
    place-items: center;
    color: currentcolor;
}

.navigation-icon :deep(svg) {
    width: 20px;
    height: 20px;
}

.navigation-text {
    overflow: hidden;
    font-size: 14px;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.promo {
    position: relative;
    display: grid;
    gap: 4px;
    margin: 14px 4px 12px;
    padding: 74px 16px 16px;
    overflow: hidden;
    border-radius: 16px;
    background: linear-gradient(160deg, #eef3ff 0%, #e4ecff 100%);
    text-align: center;
}

.promo-art {
    position: absolute;
    top: 14px;
    left: 0;
    right: 0;
    display: flex;
    height: 56px;
    align-items: flex-end;
    justify-content: center;
    gap: 8px;
}

.promo-cube {
    display: grid;
    place-items: center;
    border-radius: 10px;
    color: #fff;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: .5px;
    transform: rotate(-8deg);
    box-shadow: 0 10px 18px rgb(91 139 255 / 30%);
}

.promo-cube--1 {
    width: 34px;
    height: 34px;
    background: linear-gradient(145deg, #93b4ff, #6c8dff);
}

.promo-cube--2 {
    width: 44px;
    height: 44px;
    background: linear-gradient(145deg, #6c8dff, #5468ff);
    transform: rotate(6deg);
}

.promo-cube--3 {
    width: 34px;
    height: 34px;
    background: linear-gradient(145deg, #a9c2ff, #7f9dff);
    transform: rotate(12deg);
}

.promo-title {
    font-size: 14px;
    font-weight: 800;
    background: linear-gradient(90deg, #4c6ef5, #7b5bff);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}

.promo-sub {
    color: #8b95b1;
    font-size: 11px;
}

.promo-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 46px;
    margin: 0 4px;
    border-radius: 12px;
    color: #fff;
    background: linear-gradient(135deg, #5b8bff, #4c6ef5);
    box-shadow: 0 10px 22px rgb(76 110 245 / 30%);
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    transition: transform 150ms ease, box-shadow 150ms ease;
}

.promo-button:hover {
    transform: translateY(-1px);
    box-shadow: 0 14px 26px rgb(76 110 245 / 38%);
}

/* 折叠态 */
.app-sidebar--collapsed {
    padding-right: 12px;
    padding-left: 12px;
}

.app-sidebar--collapsed .brand {
    justify-content: center;
    padding-right: 0;
    padding-left: 0;
}

.app-sidebar--collapsed .brand-copy,
.app-sidebar--collapsed .navigation-text,
.app-sidebar--collapsed .navigation-chevron,
.app-sidebar--collapsed .navigation-children,
.app-sidebar--collapsed .promo,
.app-sidebar--collapsed .promo-button-text {
    display: none;
}

.app-sidebar--collapsed .navigation-link {
    justify-content: center;
    padding: 0;
}

.app-sidebar--collapsed .promo-button {
    min-height: 44px;
}

@media (max-width: 720px) {

    .brand-copy,
    .navigation-text,
    .navigation-chevron,
    .navigation-children,
    .promo,
    .promo-button-text {
        display: none;
    }

    .brand {
        justify-content: center;
        padding-right: 0;
        padding-left: 0;
    }

    .navigation-link {
        justify-content: center;
        padding: 0;
    }
}
</style>
