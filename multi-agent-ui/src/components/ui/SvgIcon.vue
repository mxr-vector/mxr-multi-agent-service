<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    /** 资源基础名（不含目录与扩展名），如 shujufenxi、PDF */
    name: string;
    /** 保留原始多色填充（文件类型图标用），默认单色跟随 currentColor */
    colored?: boolean;
    /** 图标尺寸，数字按 px 处理 */
    size?: number | string;
  }>(),
  {
    colored: false,
    size: 20,
  }
);

// 一次性加载 assets/icon 下全部 svg 原文（Vite 构建期内联）
const modules = import.meta.glob("../assets/icon/**/*.svg", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const registry: Record<string, string> = {};
for (const [path, raw] of Object.entries(modules)) {
  const base = (path.split("/").pop() ?? "").replace(/\.svg$/i, "");
  registry[base] = raw;
  registry[base.toLowerCase()] = raw;
}

function extractSvg(raw: string) {
  const i = raw.indexOf("<svg");
  return i >= 0 ? raw.slice(i) : raw;
}

// 归一化：剥离固定宽高/class；单色时移除 fill 并令根节点跟随 currentColor
function normalize(raw: string, colored: boolean) {
  let svg = extractSvg(raw).replace(/<svg\b[^>]*>/, (open) => {
    let tag = open.replace(/\s(?:width|height)="[^"]*"/g, "").replace(/\sclass="[^"]*"/g, "");
    if (!colored) {
      tag = tag.replace(/\sfill="[^"]*"/g, "").replace(/<svg\b/, '<svg fill="currentColor"');
    }
    return tag;
  });
  if (!colored) {
    svg = svg.replace(
      /(<(?:path|rect|circle|polygon|polyline|ellipse|line|g)\b[^>]*?)\sfill="[^"]*"/g,
      "$1"
    );
  }
  return svg;
}

const markup = computed(() => {
  const raw = registry[props.name] ?? registry[props.name?.toLowerCase?.() ?? ""];
  return raw ? normalize(raw, props.colored) : "";
});

const dimension = computed(() => (typeof props.size === "number" ? `${props.size}px` : props.size));
</script>

<template>
  <span class="svg-icon" :style="{ width: dimension, height: dimension }" v-html="markup"></span>
</template>

<style scoped>
.svg-icon {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  line-height: 0;
}

.svg-icon :deep(svg) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
