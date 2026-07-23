<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { navigationItems, type NavigationItem } from '@/router/navigation'

interface Props { collapsed: boolean }
const props = defineProps<Props>()
const route = useRoute()
const expandedItemNames = ref<string[]>(['rag'])
const workbenchItems = computed<NavigationItem[]>(() => navigationItems.filter((item) => item.group === '工作台'))
const managementItems = computed<NavigationItem[]>(() => navigationItems.filter((item) => item.group === '管理'))
function isExpanded(name: string) { return expandedItemNames.value.includes(name) }
function toggleChildren(name: string) { expandedItemNames.value = isExpanded(name) ? expandedItemNames.value.filter((itemName) => itemName !== name) : [...expandedItemNames.value, name] }
function hasActiveChild(path: string) { return route.path.startsWith(`${path}/`) }
</script>

<template>
    <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': props.collapsed }">
        <RouterLink class="brand" to="/overview" aria-label="Multi Agent 首页"><span class="brand-mark">M</span><span
                class="brand-copy"><strong>Multi Agent</strong><small>ORCHESTRATION</small></span></RouterLink>
        <nav class="navigation" aria-label="主导航">
            <section class="navigation-section">
                <p class="navigation-label">工作台</p>
                <RouterLink v-for="item in workbenchItems" :key="item.name" :to="item.path" class="navigation-link"
                    :title="props.collapsed ? item.label : undefined"><span class="navigation-icon"
                        aria-hidden="true">{{ item.icon }}</span><span class="navigation-text">{{ item.label }}</span>
                </RouterLink>
            </section>
            <section class="navigation-section navigation-section--management">
                <p class="navigation-label">管理</p>
                <template v-for="item in managementItems" :key="item.name">
                    <div v-if="item.children?.length" class="navigation-parent">
                        <button class="navigation-link navigation-parent-trigger" :class="{ 'navigation-link--active': hasActiveChild(item.path) }"
                            type="button" :title="props.collapsed ? item.label : undefined" :aria-expanded="isExpanded(item.name)"
                            @click="toggleChildren(item.name)"><span class="navigation-icon" aria-hidden="true">{{ item.icon }}</span>
                            <span class="navigation-text">{{ item.label }}</span><span class="navigation-chevron" aria-hidden="true">⌄</span></button>
                        <div v-show="isExpanded(item.name) && !props.collapsed" class="navigation-children">
                            <RouterLink v-for="child in item.children" :key="child.name" :to="child.path" class="navigation-child-link">
                                <span class="navigation-child-dot" aria-hidden="true"></span>{{ child.label }}
                            </RouterLink>
                        </div>
                    </div>
                    <RouterLink v-else :to="item.path" class="navigation-link" :title="props.collapsed ? item.label : undefined">
                        <span class="navigation-icon" aria-hidden="true">{{ item.icon }}</span><span class="navigation-text">{{ item.label }}</span>
                    </RouterLink>
                </template>
            </section>
        </nav>
        <div class="usage-card">
            <div class="usage-icon" aria-hidden="true">✦</div>
            <div class="usage-copy"><strong>升级你的工作区</strong><span>解锁更强大的协作能力</span></div><button class="usage-button"
                type="button">查看方案</button>
        </div>
        <div class="profile"><span class="profile-avatar">L</span><span class="profile-copy"><strong>Lin
                    Chen</strong><small>管理员</small></span><span class="profile-more" aria-hidden="true">•••</span></div>
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
    padding: 22px 14px 16px;
    color: #edf2ff;
    background: #121a2c;
    transition: padding 180ms ease;
}

.brand {
    display: flex;
    align-items: center;
    gap: 11px;
    min-width: 0;
    padding: 0 8px 27px;
    color: inherit;
    text-decoration: none;
}

.brand-mark {
    display: grid;
    width: 34px;
    height: 34px;
    flex: 0 0 auto;
    place-items: center;
    border-radius: 11px;
    color: #172039;
    background: linear-gradient(135deg, #a4b6ff, #e6eafe);
    box-shadow: 0 8px 22px rgb(136 154 255 / 25%);
    font-weight: 800;
}

.brand-copy,
.profile-copy,
.usage-copy {
    display: grid;
    min-width: 0;
    gap: 2px;
    white-space: nowrap;
}

.brand-copy strong {
    font-size: 14px;
    letter-spacing: -.2px;
}

.brand-copy small {
    color: #8491b5;
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 1.05px;
}

.navigation {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 28px;
}

.navigation-section {
    display: grid;
    gap: 5px;
}

.navigation-section--management {
    margin-top: auto;
}

.navigation-label {
    margin: 0 10px 7px;
    color: #7481a5;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .7px;
}

.navigation-link {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 42px;
    padding: 0 10px;
    border-radius: 9px;
    color: #9ba8c7;
    text-decoration: none;
    transition: background-color 150ms ease, color 150ms ease;
}

.navigation-link:hover {
    color: #f8f9ff;
    background: rgb(255 255 255 / 6%);
}

.navigation-link.router-link-active,
.navigation-link--active {
    color: #eff1ff;
    background: linear-gradient(90deg, rgb(130 149 255 / 23%), rgb(130 149 255 / 7%));
}

.navigation-parent-trigger { width: 100%; border: 0; background: transparent; text-align: left; }
.navigation-chevron { margin-left: auto; color: #8491b5; font-size: 16px; line-height: 1; transition: transform 150ms ease; }
.navigation-parent-trigger[aria-expanded='true'] .navigation-chevron { transform: rotate(180deg); }
.navigation-children { display: grid; gap: 3px; margin: 3px 0 4px 20px; padding-left: 14px; border-left: 1px solid rgb(157 174 243 / 18%); }
.navigation-child-link { display: flex; align-items: center; gap: 8px; min-height: 33px; color: #8e9bbd; font-size: 12px; text-decoration: none; }
.navigation-child-link:hover, .navigation-child-link.router-link-active { color: #e8ecff; }
.navigation-child-dot { width: 5px; height: 5px; flex: 0 0 auto; border-radius: 50%; background: currentcolor; opacity: .7; }

.navigation-icon {
    display: grid;
    width: 20px;
    flex: 0 0 20px;
    place-items: center;
    color: currentcolor;
    font-size: 18px;
    line-height: 1;
}

.navigation-text {
    overflow: hidden;
    font-size: 14px;
    font-weight: 500;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.usage-card {
    display: grid;
    gap: 9px;
    margin: 18px 3px;
    padding: 15px;
    border: 1px solid rgb(169 182 255 / 16%);
    border-radius: 13px;
    background: linear-gradient(145deg, #202d52, #17213a);
}

.usage-icon {
    color: #b9c6ff;
    font-size: 20px;
}

.usage-copy strong {
    font-size: 12px;
}

.usage-copy span {
    color: #a3afce;
    font-size: 11px;
    line-height: 1.45;
}

.usage-button {
    width: fit-content;
    padding: 0;
    border: 0;
    color: #c7d0ff;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
}

.profile {
    display: flex;
    align-items: center;
    gap: 9px;
    min-height: 50px;
    padding: 8px;
    border-top: 1px solid rgb(151 165 211 / 14%);
}

.profile-avatar {
    display: grid;
    width: 29px;
    height: 29px;
    flex: 0 0 auto;
    place-items: center;
    border-radius: 9px;
    color: #1d2440;
    background: linear-gradient(145deg, #f8cdb3, #d993a8);
    font-size: 12px;
    font-weight: 800;
}

.profile-copy strong {
    font-size: 12px;
}

.profile-copy small {
    color: #8592b3;
    font-size: 11px;
}

.profile-more {
    margin-left: auto;
    color: #8592b3;
    letter-spacing: 1px;
}

.app-sidebar--collapsed {
    align-items: center;
    padding-right: 10px;
    padding-left: 10px;
}

.app-sidebar--collapsed .brand {
    padding-right: 0;
    padding-left: 0;
}

.app-sidebar--collapsed .brand-copy,
.app-sidebar--collapsed .navigation-label,
.app-sidebar--collapsed .navigation-text,
.app-sidebar--collapsed .usage-card,
.app-sidebar--collapsed .profile-copy,
.app-sidebar--collapsed .profile-more {
    display: none;
}

.app-sidebar--collapsed .navigation-link {
    justify-content: center;
    padding: 0;
}

.app-sidebar--collapsed .navigation-chevron,
.app-sidebar--collapsed .navigation-children { display: none; }

.app-sidebar--collapsed .profile {
    padding: 8px 0;
}

@media (max-width: 720px) {
    .app-sidebar {
        align-items: center;
        padding-right: 10px;
        padding-left: 10px;
    }

    .brand-copy,
    .navigation-label,
    .navigation-text,
    .usage-card,
    .profile-copy,
    .profile-more {
        display: none;
    }

    .brand {
        padding-right: 0;
        padding-left: 0;
    }

    .navigation-link {
        justify-content: center;
        padding: 0;
    }

    .profile {
        padding: 8px 0;
    }
}
</style>
