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
      <main class="main-layout-main"><RouterView /></main>
    </section>
  </div>
</template>

<style scoped>
.main-layout { --sidebar-width: 264px; display: grid; grid-template-columns: var(--sidebar-width) minmax(0, 1fr); min-height: 100vh; background: #f7f8fc; transition: grid-template-columns 180ms ease; }
.main-layout--collapsed { --sidebar-width: 82px; }
.main-layout-content { min-width: 0; }
.main-layout-main { padding: 28px 32px 48px; }
@media (max-width: 720px) { .main-layout { --sidebar-width: 82px; } .main-layout-main { padding: 20px; } }
</style>
