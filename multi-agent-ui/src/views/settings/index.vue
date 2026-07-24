<script setup lang="ts">
import { computed } from "vue";

// 系统管理分组（接入接口前为静态占位）
const sections = computed(() => [
  {
    title: "工作区设置",
    desc: "配置工作区名称、语言与默认偏好。",
    items: ["工作区名称", "默认语言", "时区"],
  },
  {
    title: "成员与权限",
    desc: "管理成员账号及其角色权限。",
    items: ["成员列表", "角色管理", "邀请链接"],
  },
  {
    title: "连接配置",
    desc: "维护模型服务、向量库等外部连接。",
    items: ["模型服务", "向量数据库", "API 密钥"],
  },
]);
</script>

<template>
  <section class="settings-view">
    <article v-for="section in sections" :key="section.title" class="settings-card">
      <header class="settings-card-head">
        <h2>{{ section.title }}</h2>
        <p>{{ section.desc }}</p>
      </header>
      <ul class="settings-list">
        <li v-for="item in section.items" :key="item" class="settings-row">
          <span class="settings-row-label">{{ item }}</span>
          <button type="button" class="settings-row-action">配置</button>
        </li>
      </ul>
    </article>
  </section>
</template>

<style scoped>
.settings-view {
  display: grid;
  gap: 18px;
}

.settings-card {
  border: 1px solid #e8ebf2;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.settings-card-head {
  padding: 20px 22px 14px;
  border-bottom: 1px solid #eef1f8;
}

.settings-card-head h2 {
  margin: 0;
  color: #273249;
  font-size: 16px;
}

.settings-card-head p {
  margin: 6px 0 0;
  color: #818b9d;
  font-size: 13px;
}

.settings-list {
  margin: 0;
  padding: 6px 0;
  list-style: none;
}

.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 22px;
}

.settings-row + .settings-row {
  border-top: 1px solid #f2f4fa;
}

.settings-row-label {
  color: #465072;
  font-size: 14px;
}

.settings-row-action {
  min-height: 32px;
  padding: 0 14px;
  border: 1px solid #dfe4ef;
  border-radius: 8px;
  color: #59657b;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition:
    border-color 150ms ease,
    color 150ms ease,
    background-color 150ms ease;
}

.settings-row-action:hover {
  color: #4c6ef5;
  border-color: #d5deff;
  background: #f3f6ff;
}
</style>
