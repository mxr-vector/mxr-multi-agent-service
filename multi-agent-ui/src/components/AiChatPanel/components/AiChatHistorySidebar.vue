<template>
  <aside class="afc-history">
    <div class="afc-history__hd">
      <span>历史会话</span>
      <div class="afc-history__actions">
        <button class="afc-new-btn" @click="emit('create-session')">
          <el-icon :size="11">
            <Plus />
          </el-icon>
          新对话
        </button>
        <button
          class="afc-new-btn afc-new-btn--danger"
          :disabled="!sessions.length"
          @click="emit('delete-all')"
        >
          <el-icon :size="11">
            <Delete />
          </el-icon>
          清空全部
        </button>
      </div>
    </div>
    <el-scrollbar class="afc-history__scroll">
      <div v-if="!sessions.length" class="afc-history__empty">
        <el-icon :size="30" color="#d1d5db">
          <Document />
        </el-icon>
        <p>暂无历史会话</p>
      </div>
      <template v-for="group in groupedSessions" :key="group.label">
        <p class="afc-history__date">{{ group.label }}</p>
        <div
          v-for="session in group.items"
          :key="session.id"
          class="afc-session"
          :class="{ 'is-active': session.id === currentSessionId }"
          @click="emit('load-session', session)"
        >
          <el-icon :size="12" class="afc-session__ico">
            <ChatLineRound />
          </el-icon>
          <span class="afc-session__title">{{ session.title }}</span>
          <button
            class="afc-session__del"
            @click.stop="emit('delete-session', session.id)"
            aria-label="删除"
          >
            <el-icon :size="10">
              <Close />
            </el-icon>
          </button>
        </div>
      </template>
    </el-scrollbar>
  </aside>
</template>

<script setup lang="ts">
import { ChatLineRound, Close, Delete, Document, Plus } from "@element-plus/icons-vue";
import type { ChatSession } from "../types";

defineProps<{
  sessions: ChatSession[];
  groupedSessions: { label: string; items: ChatSession[] }[];
  currentSessionId: string | null;
}>();

const emit = defineEmits<{
  (e: "create-session"): void;
  (e: "delete-all"): void;
  (e: "load-session", session: ChatSession): void;
  (e: "delete-session", id: string): void;
}>();
</script>

<style src="../styles/AiChatHistorySidebar.css"></style>
