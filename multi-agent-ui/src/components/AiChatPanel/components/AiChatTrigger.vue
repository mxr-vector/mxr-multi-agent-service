<template>
  <div
    class="afc-trigger"
    :class="triggerClasses"
    :style="triggerStyle"
    @mouseenter="emit('fab-mouseenter')"
    @mouseleave="emit('fab-mouseleave')"
  >
    <el-badge
      :value="unreadCount || undefined"
      :max="99"
      :hidden="!unreadCount || isPanelOpen"
      type="danger"
    >
      <button
        class="afc-fab"
        :class="{ 'is-open': isPanelOpen }"
        :aria-label="isPanelOpen ? '关闭助手' : '打开助手'"
        @pointerdown="emit('fab-pointerdown', $event)"
        @click="emit('fab-click')"
      >
        <span class="afc-fab__pulse" v-show="!isPanelOpen" />
        <el-icon class="afc-fab__ico afc-fab__ico--chat" :size="22">
          <ChatDotRound />
        </el-icon>
        <el-icon class="afc-fab__ico afc-fab__ico--close" :size="20">
          <Close />
        </el-icon>
      </button>
    </el-badge>
  </div>
</template>

<script setup lang="ts">
import { ChatDotRound, Close } from "@element-plus/icons-vue";

defineProps<{
  isPanelOpen: boolean;
  unreadCount: number;
  triggerStyle: Record<string, string>;
  triggerClasses: Record<string, boolean>;
}>();

const emit = defineEmits<{
  (e: "fab-pointerdown", event: PointerEvent): void;
  (e: "fab-click"): void;
  (e: "fab-mouseenter"): void;
  (e: "fab-mouseleave"): void;
}>();
</script>

<style src="../styles/AiChatTrigger.css"></style>
