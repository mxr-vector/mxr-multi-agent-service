<script setup lang="ts">
import { computed, ref, watch, type Component } from "vue";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";
import SvgIcon from "@/components/SvgIcon.vue";

/** 图标选择器：本地 assets/icon 全量 svg + Element Plus 全量默认图标 */
const model = defineModel<string>({ default: "" });

// 本地图标：懒加载 glob 仅取路径推导基础名，不额外内联文件内容（SvgIcon 已负责渲染）
const localModules = import.meta.glob("../assets/icon/**/*.svg");
const localIcons = Object.keys(localModules)
  .map((path) => (path.split("/").pop() ?? "").replace(/\.svg$/i, ""))
  .sort((a, b) => a.localeCompare(b));
const localSet = new Set(localIcons);

// Element Plus 图标：组件名即图标名（main.ts 中已全局注册，此处直接用组件引用渲染）
const epMap = ElementPlusIconsVue as Record<string, Component>;
const epIcons = Object.keys(epMap).sort((a, b) => a.localeCompare(b));

const visible = ref(false);
const keyword = ref("");
const activeTab = ref<"local" | "ep">("local");

const filteredLocal = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  return kw ? localIcons.filter((n) => n.toLowerCase().includes(kw)) : localIcons;
});
const filteredEp = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  return kw ? epIcons.filter((n) => n.toLowerCase().includes(kw)) : epIcons;
});

// 当前值属于本地图标则用 SvgIcon 预览，否则按 Element Plus 组件预览
const currentIsLocal = computed(() => Boolean(model.value) && localSet.has(model.value));
const currentEpIcon = computed(() =>
  model.value && !currentIsLocal.value ? epMap[model.value] : undefined
);

// 打开/关闭完全交给 el-popover 的 click trigger 控制，避免手动置位与 trigger 冲突导致闪烁；
// 此处仅在弹层打开时重置搜索词并定位到当前值所在 Tab
watch(visible, (opened) => {
  if (!opened) return;
  keyword.value = "";
  activeTab.value = model.value && currentEpIcon.value ? "ep" : "local";
});

function pick(name: string) {
  model.value = name;
  visible.value = false;
}
</script>

<template>
  <el-popover v-model:visible="visible" :width="440" trigger="click" placement="bottom-start">
    <template #reference>
      <el-input
        :model-value="model"
        placeholder="点击选择图标"
        readonly
        clearable
        @clear="model = ''"
      >
        <template #prefix>
          <SvgIcon v-if="currentIsLocal" :name="model" colored :size="16" />
          <el-icon v-else-if="currentEpIcon" :size="16">
            <component :is="currentEpIcon" />
          </el-icon>
        </template>
      </el-input>
    </template>

    <div class="icon-select">
      <el-input v-model="keyword" placeholder="搜索图标名称" clearable size="small" />
      <el-tabs v-model="activeTab" class="icon-select-tabs">
        <el-tab-pane :label="`本地图标（${filteredLocal.length}）`" name="local">
          <div class="icon-grid">
            <button
              v-for="name in filteredLocal"
              :key="name"
              type="button"
              class="icon-cell"
              :class="{ active: name === model }"
              :title="name"
              @click="pick(name)"
            >
              <SvgIcon :name="name" colored :size="18" />
              <span class="icon-cell-name">{{ name }}</span>
            </button>
            <p v-if="!filteredLocal.length" class="icon-empty">未找到匹配图标</p>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="`Element Plus（${filteredEp.length}）`" name="ep">
          <div class="icon-grid">
            <button
              v-for="name in filteredEp"
              :key="name"
              type="button"
              class="icon-cell"
              :class="{ active: name === model }"
              :title="name"
              @click="pick(name)"
            >
              <el-icon :size="18">
                <component :is="epMap[name]" />
              </el-icon>
              <span class="icon-cell-name">{{ name }}</span>
            </button>
            <p v-if="!filteredEp.length" class="icon-empty">未找到匹配图标</p>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-popover>
</template>

<style scoped>
.icon-select-tabs :deep(.el-tabs__header) {
  margin: 8px 0;
}

.icon-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
  padding-right: 4px;
}

.icon-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid #e8ebf2;
  border-radius: 8px;
  background: #fff;
  color: #4a5468;
  font-size: 12px;
  cursor: pointer;
  transition:
    border-color 120ms ease,
    color 120ms ease,
    background 120ms ease;
}

.icon-cell:hover {
  color: #526ae2;
  border-color: #c4cef7;
  background: #f5f7ff;
}

.icon-cell.active {
  color: #526ae2;
  border-color: #526ae2;
  background: #eef1fe;
}

.icon-cell-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.icon-empty {
  grid-column: 1 / -1;
  margin: 24px 0;
  color: #9aa3b5;
  font-size: 12px;
  text-align: center;
}
</style>
