<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import SvgIcon from "@/components/ui/SvgIcon.vue";
import { NAV_ICON_ASSET } from "@/router/navigation";

const route = useRoute();
const router = useRouter();

// 模块名与图标来自当前路由 meta（后端菜单下发）；映射不到时回退通用值
const label = computed(() => (route.meta.label as string | undefined) ?? "该模块");
const icon = computed(() => {
  const key = route.meta.icon as string | undefined;
  return NAV_ICON_ASSET[key ?? ""] ?? key ?? "wenjian";
});

function backToOverview() {
  router.push("/overview");
}
</script>

<template>
  <article class="under-development">
    <div class="under-development-head">
      <span class="under-development-icon" aria-hidden="true">
        <SvgIcon :name="icon" :size="28" />
      </span>
      <div class="under-development-heading">
        <div class="under-development-title">
          <h2>{{ label }}</h2>
          <span class="under-development-badge">
            <span class="under-development-badge-dot" aria-hidden="true"></span>
            正在开发中
          </span>
        </div>
        <p>这个模块正在开发中，上线后即可使用。先回工作台看看已上线的功能吧。</p>
      </div>
    </div>
    <footer class="under-development-footer">
      <button type="button" class="under-development-action" @click="backToOverview">
        返回工作台
      </button>
    </footer>
  </article>
</template>

<style scoped>
.under-development {
  display: grid;
  gap: 22px;
  padding: 34px 30px 26px;
  border: 1px solid #e8ebf2;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.under-development-head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.under-development-icon {
  display: grid;
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 14px;
  color: #4c6ef5;
  background: #eef2ff;
}

.under-development-heading {
  min-width: 0;
}

.under-development-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.under-development-title h2 {
  margin: 0;
  color: #273249;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.2px;
}

.under-development-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 999px;
  color: #b4641f;
  background: #fdf1e3;
  font-size: 12px;
  font-weight: 600;
}

.under-development-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #e0803a;
  animation: under-development-pulse 1.8s ease-in-out infinite;
}

.under-development-heading p {
  max-width: 520px;
  margin: 8px 0 0;
  color: #818b9d;
  font-size: 13px;
  line-height: 1.65;
}

.under-development-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 18px;
  border-top: 1px solid #eef1f6;
}

.under-development-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 0 15px;
  border: 0;
  border-radius: 9px;
  color: #fff;
  background: #4c6ef5;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 150ms ease;
}

.under-development-action:hover {
  background: #3f5ce0;
}

.under-development-action:focus-visible {
  outline: 2px solid #4c6ef5;
  outline-offset: 2px;
}

@keyframes under-development-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.45;
    transform: scale(0.72);
  }
}

@media (prefers-reduced-motion: reduce) {
  .under-development-badge-dot {
    animation: none;
  }
}

@media (max-width: 560px) {
  .under-development {
    padding: 24px 20px 20px;
  }

  .under-development-footer {
    justify-content: stretch;
  }

  .under-development-action {
    width: 100%;
  }
}
</style>
