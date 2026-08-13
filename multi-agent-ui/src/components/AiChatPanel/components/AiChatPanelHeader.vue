<template>
  <header class="afc-header">
    <div class="afc-header__left">
      <span class="afc-header__ava">
        <SvgIcon name="智能优化" :size="15" />
      </span>
      <div>
        <p class="afc-header__name">{{ title }}</p>
        <p class="afc-header__status">
          <span class="afc-dot" :class="isLoading ? 'afc-dot--thinking' : 'afc-dot--online'" />
          {{ isLoading ? `思考中… ${elapsedSeconds}s` : "在线" }}
        </p>
      </div>
    </div>
    <div class="afc-header__right">
      <el-tooltip content="历史会话" placement="bottom" :show-after="100">
        <button
          class="afc-hbtn"
          :class="{ 'is-active': showHistory }"
          @click="emit('toggle-history')"
          aria-label="历史会话"
        >
          <el-icon :size="15">
            <Clock />
          </el-icon>
          <span>历史</span>
        </button>
      </el-tooltip>
      <div class="afc-divider" />
      <el-tooltip content="清空会话" placement="bottom" :show-after="100">
        <span style="display: inline-flex">
          <button class="afc-icon-btn" :disabled="!canClear" @click="emit('clear')">
            <el-icon :size="16">
              <Delete />
            </el-icon>
          </button>
        </span>
      </el-tooltip>
      <el-tooltip :content="isMaximized ? '还原' : '最大化'" placement="bottom" :show-after="100">
        <button class="afc-icon-btn" aria-label="最大化切换" @click="emit('toggle-maximize')">
          <el-icon :size="16">
            <ScaleToOriginal v-if="isMaximized" />
            <FullScreen v-else />
          </el-icon>
        </button>
      </el-tooltip>
      <button class="afc-icon-btn" aria-label="关闭" @click="emit('close')">
        <el-icon :size="16">
          <Close />
        </el-icon>
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { Clock, Close, Delete, FullScreen, ScaleToOriginal } from "@element-plus/icons-vue";
import SvgIcon from "@/components/ui/SvgIcon.vue";
defineProps<{
  title: string;
  isLoading: boolean;
  elapsedSeconds: number;
  showHistory: boolean;
  isMaximized: boolean;
  canClear: boolean;
}>();

const emit = defineEmits<{
  (e: "toggle-history"): void;
  (e: "clear"): void;
  (e: "toggle-maximize"): void;
  (e: "close"): void;
}>();
</script>

<style src="../styles/AiChatHeader.css"></style>
