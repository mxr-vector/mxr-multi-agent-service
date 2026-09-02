<script setup lang="ts">
/**
 * 键值对编辑器：角色人设/视觉风格等对象字段的逐条录入，替代原始 JSON 文本框。
 * 每行「项 + 值」，支持增删行；值按原文字符串保存（不做类型强转），
 * 回显时非字符串的历史值以 JSON 文本展示。
 */
import { ref, watch } from "vue";
import { Plus, Delete } from "@element-plus/icons-vue";

interface KeyValueRow {
  key: string;
  value: string;
}

const props = withDefaults(
  defineProps<{
    modelValue: Record<string, unknown>;
    keyPlaceholder?: string;
    valuePlaceholder?: string;
  }>(),
  {
    keyPlaceholder: "项，如：性格",
    valuePlaceholder: "内容，如：坚毅",
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", value: Record<string, unknown>): void;
}>();

const rows = ref<KeyValueRow[]>([]);

// 内部编辑触发的回写不再重建行（避免输入中光标丢失）
let skipNextSync = false;

function fromObject(obj: Record<string, unknown> | null | undefined): KeyValueRow[] {
  return Object.entries(obj ?? {}).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

function toObject(list: KeyValueRow[]): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const row of list) {
    const key = row.key.trim();
    if (!key) continue;
    // 值一律按原文存储（不做 JSON 解析），避免 "1.10"→1.1、"true"→boolean
    // 之类的静默类型强转；同名键后者覆盖前者（对象语义）
    result[key] = row.value;
  }
  return result;
}

watch(
  () => props.modelValue,
  (obj) => {
    if (skipNextSync) {
      skipNextSync = false;
      return;
    }
    rows.value = fromObject(obj);
    if (!rows.value.length) rows.value = [{ key: "", value: "" }];
  },
  { immediate: true, deep: true }
);

function sync() {
  skipNextSync = true;
  emit("update:modelValue", toObject(rows.value));
}

function addRow() {
  rows.value.push({ key: "", value: "" });
}

function removeRow(index: number) {
  rows.value.splice(index, 1);
  if (!rows.value.length) rows.value = [{ key: "", value: "" }];
  sync();
}
</script>

<template>
  <div class="kv-editor">
    <div v-for="(row, index) in rows" :key="index" class="kv-row">
      <el-input
        v-model="row.key"
        :placeholder="keyPlaceholder"
        class="kv-key"
        @update:model-value="sync"
      />
      <el-input
        v-model="row.value"
        :placeholder="valuePlaceholder"
        class="kv-value"
        @update:model-value="sync"
      />
      <el-button
        link
        type="danger"
        :icon="Delete"
        class="kv-remove"
        @click="removeRow(index)"
      />
    </div>
    <el-button size="small" :icon="Plus" @click="addRow">添加一项</el-button>
  </div>
</template>

<style scoped>
.kv-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.kv-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.kv-key {
  width: 120px;
  flex-shrink: 0;
}
.kv-value {
  flex: 1;
}
.kv-remove {
  flex-shrink: 0;
}
</style>
