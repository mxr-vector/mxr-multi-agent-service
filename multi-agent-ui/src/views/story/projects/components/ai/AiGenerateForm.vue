<script setup lang="ts">
/**
 * 生成表单：风格/画幅/集数/基调 + 需求输入 + 发送/停止（纯展示，状态由父级持有）。
 */
import { computed } from "vue";
import type { StoryGeneratePayload, StoryStyleVO } from "@/api/story";

const form = defineModel<StoryGeneratePayload>({ required: true });

const props = defineProps<{
  styles: StoryStyleVO[];
  generating: boolean;
}>();

const emit = defineEmits<{
  (e: "send"): void;
  (e: "stop"): void;
}>();

/** 当前风格可用画幅（注册表预设；未选风格时为空） */
const aspectOptions = computed(
  () => props.styles.find((s) => s.key === form.value.style_key)?.aspect_ratios ?? []
);

/** 切换风格时画幅回落到该风格首选 */
function onStyleChange() {
  if (!aspectOptions.value.includes(form.value.aspect_ratio ?? "")) {
    form.value.aspect_ratio = aspectOptions.value[0] ?? null;
  }
}
</script>

<template>
  <div class="gen-form">
    <div class="form-row">
      <el-select v-model="form.style_key" placeholder="视频风格" size="small" @change="onStyleChange">
        <el-option
          v-for="style in styles"
          :key="style.key"
          :value="style.key"
          :label="style.name"
        />
      </el-select>
      <el-select v-model="form.aspect_ratio" placeholder="画幅" size="small" class="aspect-select">
        <el-option v-for="ratio in aspectOptions" :key="ratio" :value="ratio" :label="ratio" />
      </el-select>
      <el-input-number
        v-model="form.episodes"
        :min="1"
        :max="50"
        size="small"
        controls-position="right"
        placeholder="集数"
        class="episodes-input"
      />
      <el-input v-model="form.tone" size="small" placeholder="基调" class="tone-input" />
    </div>
    <div class="input-row">
      <el-input
        v-model="form.idea"
        type="textarea"
        :rows="3"
        :disabled="generating"
        placeholder="描述你的故事设定/需求，如题材、主人公、核心冲突…"
      />
    </div>
    <div class="action-row">
      <el-button v-if="!generating" type="primary" size="small" @click="emit('send')">
        生成剧本
      </el-button>
      <el-button v-else type="warning" size="small" @click="emit('stop')">停止生成</el-button>
    </div>
  </div>
</template>

<style scoped>
.gen-form {
  border-top: 1px solid #e5e9f2;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.form-row > .el-select {
  flex: 1;
  min-width: 96px;
}
.aspect-select {
  max-width: 88px;
}
.episodes-input {
  width: 92px;
}
.tone-input {
  flex: 1;
  min-width: 72px;
  max-width: 110px;
}
.action-row {
  display: flex;
  justify-content: flex-end;
}
</style>
