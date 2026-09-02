<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import SvgIcon from "@/components/ui/SvgIcon.vue";
import { NAV_ICON_ASSET } from "@/router/navigation";

const router = useRouter();

// 时间感知问候：让工作台的第一句话随当下时刻变化
const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 12) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
});

// 顶部概览指标（接入接口前为静态占位）
const stats = computed(() => [
  { label: "运行中的智能体", value: "12", trend: "+18%", up: true },
  { label: "本周已完成任务", value: "248", trend: "+12%", up: true },
  { label: "平均响应时间", value: "1.8s", trend: "0.4s", up: false },
  { label: "活跃工作流", value: "9", trend: "+3", up: true },
]);

// 快捷入口：跳转到各业务模块（tone 决定图标块的渐变配色）
const shortcuts = computed(() => [
  {
    icon: "workflow",
    tone: "workflow",
    title: "工作流",
    desc: "编排可复用的自动化流程",
    to: "/workflows",
  },
  {
    icon: "agent",
    tone: "agent",
    title: "智能体",
    desc: "创建、配置并监控你的智能体",
    to: "/agents",
  },
  {
    icon: "rag",
    tone: "rag",
    title: "RAG 系统",
    desc: "管理知识库与文档",
    to: "/rag/knowledge-base",
  },
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
    <div class="hero">
      <div class="hero-glow hero-glow--blue" aria-hidden="true"></div>
      <div class="hero-glow hero-glow--violet" aria-hidden="true"></div>
      <div class="hero-copy">
        <p class="hero-eyebrow">Multi-Agent Test Platform</p>
        <h1 class="hero-title">{{ greeting }}，欢迎回来</h1>
        <p class="hero-sub">你的智能体运行、任务进度与知识库状态，都在这一个界面里。</p>
      </div>
    </div>

    <div class="stat-grid">
      <article
        v-for="(stat, i) in stats"
        :key="stat.label"
        class="stat-card"
        :style="{ '--d': `${80 + i * 70}ms` }"
      >
        <p class="stat-label">{{ stat.label }}</p>
        <strong class="stat-value">{{ stat.value }}</strong>
        <div class="stat-footer">
          <span class="stat-trend" :class="{ 'stat-trend--down': !stat.up }">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path v-if="stat.up" d="M7 10l5-5 5 5M12 5v14" />
              <path v-else d="M7 14l5 5 5-5M12 19V5" />
            </svg>
            {{ stat.trend }}
          </span>
          <span class="stat-caption">较上周</span>
        </div>
      </article>
    </div>

    <div class="section-head">
      <h2>快捷入口</h2>
      <p>直达常用业务模块，快速开始你的工作。</p>
    </div>
    <div class="shortcut-grid">
      <button
        v-for="(shortcut, i) in shortcuts"
        :key="shortcut.to"
        type="button"
        class="shortcut-card"
        :style="{ '--d': `${360 + i * 80}ms` }"
        @click="go(shortcut.to)"
      >
        <span class="shortcut-icon" :class="`shortcut-icon--${shortcut.tone}`" aria-hidden="true">
          <SvgIcon :name="navIcon(shortcut.icon)" :size="22" />
        </span>
        <span class="shortcut-copy">
          <strong>{{ shortcut.title }}</strong>
          <small>{{ shortcut.desc }}</small>
        </span>
        <span class="shortcut-arrow" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.overview-view {
  display: grid;
  gap: 26px;
}

/* ---------- Hero：时间感知问候 + 品牌光晕 ---------- */
.hero {
  position: relative;
  overflow: hidden;
  padding: 28px 30px;
  border: 1px solid #e8ecfb;
  border-radius: 16px;
  background: linear-gradient(120deg, #f4f7ff 0%, #faf9ff 55%, #f4f8ff 100%);
  animation: rise 500ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
}

.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(6px);
  pointer-events: none;
}

.hero-glow--blue {
  top: -90px;
  right: -40px;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgb(91 139 255 / 16%) 0%, transparent 62%);
}

.hero-glow--violet {
  bottom: -110px;
  right: 160px;
  width: 260px;
  height: 260px;
  background: radial-gradient(circle, rgb(124 92 255 / 12%) 0%, transparent 62%);
}

.hero-copy {
  position: relative;
  display: grid;
  gap: 8px;
}

.hero-eyebrow {
  margin: 0;
  color: #4c6ef5;
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 1.6px;
  text-transform: uppercase;
}

.hero-title {
  margin: 0;
  color: #1b2337;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.hero-sub {
  margin: 0;
  color: #5b6580;
  font-size: 13px;
}

/* ---------- 统计卡片 ---------- */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  display: grid;
  gap: 10px;
  padding: 22px 22px 20px;
  border: 1px solid #e9edf5;
  border-radius: 15px;
  background: #fff;
  box-shadow: 0 6px 20px rgb(43 56 86 / 4%);
  animation: rise 500ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
  animation-delay: var(--d, 0ms);
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
}

.stat-card:hover {
  transform: translateY(-3px);
  border-color: #dde4fb;
  box-shadow: 0 16px 32px rgb(43 56 86 / 9%);
}

.stat-label {
  margin: 0;
  color: #7d879a;
  font-size: 12px;
  font-weight: 500;
}

/* 签名元素：品牌渐变数字 */
.stat-value {
  font-size: 30px;
  font-weight: 650;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  background: linear-gradient(120deg, #3d63f2 0%, #7c5cff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}

.stat-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-trend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  color: #1ea97c;
  background: #e9f9f3;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.stat-trend svg {
  width: 12px;
  height: 12px;
}

.stat-trend--down {
  color: #e07a3f;
  background: #fdf1e7;
}

.stat-caption {
  color: #98a2b8;
  font-size: 12px;
}

/* ---------- 区块标题 ---------- */
.section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  animation: rise 500ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
  animation-delay: 300ms;
}

.section-head::before {
  content: "";
  align-self: stretch;
  width: 3px;
  border-radius: 2px;
  background: linear-gradient(180deg, #5b8bff 0%, #7c5cff 100%);
}

.section-head h2 {
  margin: 0;
  color: #1b2337;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.section-head p {
  margin: 0;
  color: #818b9d;
  font-size: 13px;
}

/* ---------- 快捷入口 ---------- */
.shortcut-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.shortcut-card {
  display: flex;
  align-items: center;
  gap: 15px;
  padding: 19px 21px;
  border: 1px solid #e9edf5;
  border-radius: 15px;
  background: #fff;
  box-shadow: 0 4px 16px rgb(43 56 86 / 3%);
  text-align: left;
  cursor: pointer;
  animation: rise 500ms cubic-bezier(0.22, 1, 0.36, 1) backwards;
  animation-delay: var(--d, 0ms);
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
}

.shortcut-card:hover {
  transform: translateY(-2px);
  border-color: #dde4fb;
  box-shadow: 0 14px 28px rgb(43 56 86 / 8%);
}

/* 图标块：同色系三种渐变，构成模块识别 */
.shortcut-icon {
  display: grid;
  width: 48px;
  height: 48px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 13px;
  color: #fff;
  box-shadow: 0 6px 14px rgb(76 110 245 / 28%);
  transition: transform 180ms ease;
}

.shortcut-icon--workflow {
  background: linear-gradient(135deg, #5b8bff 0%, #4c6ef5 100%);
}

.shortcut-icon--agent {
  background: linear-gradient(135deg, #8f7bff 0%, #6c63ff 100%);
}

.shortcut-icon--rag {
  background: linear-gradient(135deg, #4fc3f0 0%, #4c8df5 100%);
}

.shortcut-card:hover .shortcut-icon {
  transform: scale(1.06);
}

.shortcut-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.shortcut-copy strong {
  color: #1b2337;
  font-size: 15px;
  font-weight: 600;
}

.shortcut-copy small {
  overflow: hidden;
  color: #818b9d;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shortcut-arrow {
  display: grid;
  margin-left: auto;
  place-items: center;
  color: #b6bfd6;
  transition:
    color 180ms ease,
    transform 180ms ease;
}

.shortcut-arrow svg {
  width: 17px;
  height: 17px;
}

.shortcut-card:hover .shortcut-arrow {
  color: #4c6ef5;
  transform: translateX(3px);
}

/* ---------- 动效 ---------- */
@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero,
  .stat-card,
  .section-head,
  .shortcut-card {
    animation: none;
  }

  .stat-card:hover,
  .shortcut-card:hover,
  .shortcut-card:hover .shortcut-icon,
  .shortcut-card:hover .shortcut-arrow {
    transform: none;
  }
}

@media (max-width: 1000px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
