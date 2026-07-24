<script setup lang="ts">
import SvgIcon from "@/components/SvgIcon.vue";
import { NAV_ICON_ASSET } from "@/router/navigation";

function createAgent() {
  // TODO: 接入创建智能体接口后替换为真实逻辑
}
</script>

<template>
  <section class="agents-view">
    <div class="page-actions">
      <button class="primary-action" type="button" @click="createAgent">
        <span aria-hidden="true">＋</span>
        创建智能体
      </button>
    </div>

    <article class="empty-state">
      <span class="empty-state-icon" aria-hidden="true">
        <SvgIcon :name="NAV_ICON_ASSET.agent" :size="30" />
      </span>
      <div class="empty-state-copy">
        <h2>还没有智能体</h2>
        <p>创建、配置并监控你的智能体，构建后可在这里查看运行状态与产出。</p>
      </div>
      <button type="button" class="secondary-action" @click="createAgent">创建第一个</button>
    </article>
  </section>
</template>

<style scoped>
.agents-view {
  display: grid;
  gap: 22px;
}

.page-actions {
  display: flex;
  justify-content: flex-end;
}

.primary-action,
.secondary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.primary-action {
  min-height: 40px;
  padding: 0 15px;
  border: 0;
  color: #fff;
  background: #526ae2;
  box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
}

.empty-state {
  display: flex;
  min-height: 250px;
  align-items: center;
  gap: 18px;
  padding: 30px;
  border: 1px dashed #d9dfec;
  border-radius: 14px;
  background: linear-gradient(135deg, #fff, #fafbff);
}

.empty-state-icon {
  display: grid;
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 14px;
  color: #6278db;
  background: #edf0ff;
}

.empty-state-copy {
  min-width: 0;
}

.empty-state h2 {
  margin: 0;
  color: #303b50;
  font-size: 16px;
}

.empty-state p {
  max-width: 540px;
  margin: 8px 0 0;
  color: #818b9d;
  font-size: 13px;
  line-height: 1.65;
}

.secondary-action {
  min-height: 36px;
  margin-left: auto;
  padding: 0 13px;
  border: 1px solid #dfe4ef;
  color: #59657b;
  background: #fff;
  white-space: nowrap;
}

@media (max-width: 560px) {
  .empty-state {
    align-items: flex-start;
    flex-direction: column;
  }

  .secondary-action {
    margin-left: 0;
  }
}
</style>
