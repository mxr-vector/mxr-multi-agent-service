<script setup lang="ts">
import { computed, type Component } from "vue";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";
import { NAV_ICON_ASSET } from "@/router/navigation";
import SvgIcon from "@/components/SvgIcon.vue";

/**
 * 导航图标：兼容三类 icon 值 —— 静态导航的映射键（NAV_ICON_ASSET）、
 * 后端菜单存的本地 svg 基础名（IconSelect 本地 Tab）与 Element Plus 组件名（IconSelect EP Tab）。
 */
const props = withDefaults(
  defineProps<{
    icon: string;
    size?: number;
  }>(),
  { size: 20 }
);

// 本地图标基础名集合（与 SvgIcon/IconSelect 同源目录），用于识别后端菜单里的本地图标
const localModules = import.meta.glob("../../assets/icon/**/*.svg");
const localSet = new Set(
  Object.keys(localModules).map((path) => (path.split("/").pop() ?? "").replace(/\.svg$/i, ""))
);

const epMap = ElementPlusIconsVue as Record<string, Component>;

// 解析顺序：静态映射键 -> 本地 svg 基础名 -> Element Plus 组件名 -> 兜底 wenjian
const epIcon = computed<Component | undefined>(() =>
  NAV_ICON_ASSET[props.icon] || localSet.has(props.icon) ? undefined : epMap[props.icon]
);
const svgName = computed(() => {
  if (NAV_ICON_ASSET[props.icon]) return NAV_ICON_ASSET[props.icon];
  if (localSet.has(props.icon)) return props.icon;
  return "wenjian";
});
</script>

<template>
  <el-icon v-if="epIcon" :size="size">
    <component :is="epIcon" />
  </el-icon>
  <SvgIcon v-else :name="svgName" :size="size" />
</template>
