<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { type NavigationItem } from "@/router/navigation";
import { resolveAvatarUrl } from "@/api/system";
import { useUserStore } from "@/stores/userStore";
import { confirmDanger } from "@/utils/confirm";
import NavIcon from "@/layout/components/NavIcon.vue";

interface Props {
  sidebarCollapsed: boolean;
}
interface Emits {
  toggleSidebar: [];
}
const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const menuButtonLabel = computed(() => (props.sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"));
const currentLabel = computed(() => (route.meta as NavigationItem).label ?? "工作台");
const currentIcon = computed(() => (route.meta as NavigationItem).icon ?? "");

// 当前登录用户：优先昵称，头像缺失时用首字母占位
const currentUser = computed(() => userStore.userInfo);
const displayName = computed(
  () => currentUser.value?.nickname || currentUser.value?.username || "未登录"
);
const avatarInitial = computed(() => displayName.value.charAt(0).toUpperCase());
const avatarUrl = computed(() => resolveAvatarUrl(currentUser.value?.avatar));

/** 账户下拉菜单命令：个人中心 / 退出登录 */
async function onProfileCommand(command: string) {
  if (command === "profile") {
    router.push("/profile");
    return;
  }
  if (command === "logout") {
    const ok = await confirmDanger("确定退出当前账号吗？", "退出登录", {
      confirmButtonText: "退出登录",
    });
    if (!ok) return;
    await userStore.logout();
    router.push("/login");
  }
}

onMounted(() => {
  // 刷新后内存态丢失时懒拉 /auth/me，失败不阻断（401 由拦截器统一处理）
  if (!userStore.userInfo) {
    userStore.fetchUserInfo().catch(() => {});
  }
});
</script>

<template>
  <header class="app-topbar">
    <div class="topbar-leading">
      <button
        class="icon-button"
        type="button"
        :aria-label="menuButtonLabel"
        :title="menuButtonLabel"
        @click="emit('toggleSidebar')"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
        >
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <nav class="breadcrumb" aria-label="面包屑">
        <RouterLink class="breadcrumb-home" to="/overview" aria-label="首页">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M3 10.5 12 3l9 7.5" />
            <path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" />
            <path d="M9.5 21v-6h5v6" />
          </svg>
        </RouterLink>
        <span class="breadcrumb-sep" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="m9 18 6-6-6-6" />
          </svg>
        </span>
        <span class="breadcrumb-current">
          <NavIcon v-if="currentIcon" class="breadcrumb-icon" :icon="currentIcon" :size="18" />
          <strong>{{ currentLabel }}</strong>
        </span>
      </nav>
    </div>

    <div class="topbar-actions">
      <button class="search-trigger" type="button" aria-label="全局搜索">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <span class="search-text">搜索功能、文档、知识库</span>
        <kbd class="search-kbd" aria-hidden="true">⌘K</kbd>
      </button>
      <button class="icon-button notification-button" type="button" aria-label="查看通知">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        <span class="notification-badge">12</span>
      </button>
      <span class="topbar-divider" aria-hidden="true"></span>
      <el-dropdown trigger="click" @command="onProfileCommand">
        <button class="profile" type="button" aria-label="账户菜单">
          <span class="profile-avatar" aria-hidden="true">
            <span class="profile-avatar-inner">
              <img v-if="avatarUrl" :src="avatarUrl" alt="" />
              <template v-else>{{ avatarInitial }}</template>
            </span>
          </span>
          <span class="profile-copy">
            <strong>{{ displayName }}</strong>
            <small>{{ currentUser?.username ?? "—" }}</small>
          </span>
          <span class="profile-chevron" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">个人中心</el-dropdown-item>
            <el-dropdown-item command="logout" divided>
              <span class="logout-item">退出登录</span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
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
  background: rgb(255 255 255 / 72%);
  backdrop-filter: blur(18px) saturate(1.5);
  -webkit-backdrop-filter: blur(18px) saturate(1.5);
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
  cursor: pointer;
  transition:
    border-color 150ms ease,
    background-color 150ms ease,
    color 150ms ease;
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

/* 全局搜索：类输入框的触发按钮 */
.search-trigger {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 232px;
  height: 38px;
  padding: 0 8px 0 12px;
  border: 1px solid #e6eaf3;
  border-radius: 11px;
  color: #8b95ad;
  background: #f7f9fd;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 150ms ease,
    background-color 150ms ease,
    box-shadow 150ms ease;
}

.search-trigger svg {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  color: #8b95ad;
}

.search-text {
  overflow: hidden;
  flex: 1;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 22px;
  padding: 0 6px;
  border: 1px solid #e3e8f2;
  border-bottom-width: 2px;
  border-radius: 6px;
  color: #9aa4bd;
  background: #fff;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
}

.search-trigger:hover {
  border-color: #cfd9f7;
  background: #fff;
  box-shadow: 0 4px 14px rgb(43 56 86 / 6%);
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
  background: linear-gradient(135deg, #eef2ff 0%, #f3efff 100%);
  text-decoration: none;
  transition:
    background-color 150ms ease,
    color 150ms ease;
}

.breadcrumb-home:hover {
  color: #fff;
  background: linear-gradient(135deg, #5b8bff, #6c63ff);
}

.breadcrumb-home svg {
  width: 19px;
  height: 19px;
}

.breadcrumb-sep {
  display: grid;
  place-items: center;
  color: #cdd4e4;
}

.breadcrumb-sep svg {
  width: 14px;
  height: 14px;
}

.breadcrumb-current {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #1b2337;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.1px;
}

.breadcrumb-icon {
  color: #4c6ef5;
}

.notification-badge {
  position: absolute;
  top: 3px;
  right: 3px;
  display: grid;
  min-width: 17px;
  height: 17px;
  place-items: center;
  padding: 0 4px;
  border: 2px solid #fff;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(135deg, #ff6b81, #f5455c);
  box-shadow: 0 2px 6px rgb(245 69 92 / 35%);
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
  cursor: pointer;
  transition:
    background-color 150ms ease,
    border-color 150ms ease;
}

.profile:hover {
  border-color: #e6ebf7;
  background: #f5f7fd;
}

/* 头像：品牌渐变 ring + 圆形 */
.profile-avatar {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  padding: 2px;
  border-radius: 50%;
  background: linear-gradient(135deg, #5b8bff, #7c5cff);
  box-shadow: 0 4px 12px rgb(92 107 255 / 30%);
}

.profile-avatar-inner {
  display: grid;
  overflow: hidden;
  width: 100%;
  height: 100%;
  place-items: center;
  border-radius: 50%;
  color: #4c6ef5;
  background: #eef1fa;
  font-size: 14px;
  font-weight: 700;
}

.profile-avatar-inner img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.profile-copy {
  display: grid;
  gap: 1px;
  text-align: left;
  white-space: nowrap;
}

.profile-copy strong {
  color: #1b2337;
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
  transition: transform 150ms ease;
}

.profile:hover .profile-chevron {
  transform: rotate(180deg);
}

.profile-chevron svg {
  width: 16px;
  height: 16px;
}

.logout-item {
  color: #f5455c;
}

@media (max-width: 900px) {
  .app-topbar {
    padding: 0 18px;
  }

  .search-trigger {
    width: 40px;
    padding: 0;
    justify-content: center;
  }

  .search-text,
  .search-kbd {
    display: none;
  }
}
</style>
