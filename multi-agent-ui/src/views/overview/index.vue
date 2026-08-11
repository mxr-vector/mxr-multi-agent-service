<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import SvgIcon from "@/components/ui/SvgIcon.vue";
import { NAV_ICON_ASSET } from "@/router/navigation";

const router = useRouter();

// 顶部概览指标（接入接口前为静态占位）
const stats = computed(() => [
  { label: "运行中的智能体", value: "12", trend: "+18%", up: true },
  { label: "本周已完成任务", value: "248", trend: "+12%", up: true },
  { label: "平均响应时间", value: "1.8s", trend: "−0.4s", up: false },
  { label: "活跃工作流", value: "9", trend: "+3", up: true },
]);

// 快捷入口：跳转到各业务模块
const shortcuts = computed(() => [
  { icon: "workflow", title: "工作流", desc: "编排可复用的自动化流程", to: "/workflows" },
  { icon: "agent", title: "智能体", desc: "创建、配置并监控你的智能体", to: "/agents" },
  { icon: "rag", title: "RAG 系统", desc: "管理知识库与文档", to: "/rag/knowledge-base" },
]);

function go(path: string) {
  router.push(path);
}
function navIcon(icon: string) {
  return NAV_ICON_ASSET[icon] ?? "wenjian";
}
</script>

<template>
  <section class="overview-view">
    <div class="stat-grid">
      <article v-for="stat in stats" :key="stat.label" class="stat-card">
        <p class="stat-label">{{ stat.label }}</p>
        <strong class="stat-value">{{ stat.value }}</strong>
        <span class="stat-trend" :class="{ 'stat-trend--down': !stat.up }">
          {{ stat.trend }} 较上周
        </span>
      </article>
    </div>

    <div class="section-head">
      <h2>快捷入口</h2>
      <p>直达常用业务模块，快速开始你的工作。</p>
    </div>
    <div class="shortcut-grid">
      <button
        v-for="shortcut in shortcuts"
        :key="shortcut.to"
        type="button"
        class="shortcut-card"
        @click="go(shortcut.to)"
      >
        <span class="shortcut-icon" aria-hidden="true">
          <SvgIcon :name="navIcon(shortcut.icon)" :size="22" />
        </span>
        <span class="shortcut-copy">
          <strong>{{ shortcut.title }}</strong>
          <small>{{ shortcut.desc }}</small>
        </span>
        <span class="shortcut-arrow" aria-hidden="true">→</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.overview-view {
  display: grid;
  gap: 24px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  display: grid;
  gap: 8px;
  padding: 21px;
  border: 1px solid #e8ebf2;
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.stat-label {
  margin: 0;
  color: #7d879a;
  font-size: 12px;
}

.stat-value {
  color: #273249;
  font-size: 28px;
  letter-spacing: -1px;
}

.stat-trend {
  color: #4eab83;
  font-size: 12px;
}

.stat-trend--down {
  color: #e0803a;
}

.section-head h2 {
  margin: 0;
  color: #273249;
  font-size: 17px;
}

.section-head p {
  margin: 6px 0 0;
  color: #818b9d;
  font-size: 13px;
}

.shortcut-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.shortcut-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border: 1px solid #e8ebf2;
  border-radius: 13px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition:
    transform 150ms ease,
    border-color 150ms ease,
    box-shadow 150ms ease;
}

.shortcut-card:hover {
  transform: translateY(-2px);
  border-color: #d5deff;
  box-shadow: 0 12px 26px rgb(76 110 245 / 12%);
}

.shortcut-icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 12px;
  color: #4c6ef5;
  background: #eef2ff;
}

.shortcut-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.shortcut-copy strong {
  color: #273249;
  font-size: 15px;
}

.shortcut-copy small {
  color: #818b9d;
  font-size: 12px;
}

.shortcut-arrow {
  margin-left: auto;
  color: #b6bfd6;
  font-size: 18px;
}

@media (max-width: 1000px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .shortcut-grid {
    grid-template-columns: 1fr;
  }
}
</style>
