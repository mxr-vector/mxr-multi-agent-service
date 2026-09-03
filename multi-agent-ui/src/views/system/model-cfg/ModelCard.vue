<script setup lang="ts">
// 单个模型角色配置卡片：展示只读字段，编辑动作向上冒泡由页面统一处理。
import { computed } from "vue";
import type { ModelConfig } from "@/api/system/modelConfig";
import { useDictStore } from "@/stores/dictStore";

const props = defineProps<{ config: ModelConfig }>();
defineEmits<{ edit: [config: ModelConfig] }>();

const dictStore = useDictStore();
dictStore.ensureLoaded();

/** 上下文窗口展示文案：命中字典取 label，未命中回退原始数值 */
const contextWindowLabel = computed(() =>
  dictStore.getLabel("context_window", String(props.config.context_window))
);

/** Provider 展示文案：命中字典（embedding_provider）取 label，未命中回退原始值 */
const providerLabel = computed(() =>
  props.config.provider ? dictStore.getLabel("embedding_provider", props.config.provider) : ""
);

/** 模型角色分类（字典 model_types：value 为角色 key，label 为中文名） */
const modelTypes = computed(() => dictStore.getOptions("model_types"));

/** 角色标签配色（仅视觉区分，无业务语义；按字典顺序循环取色，新增角色自动分配） */
const ROLE_COLORS = ["primary", "success", "warning", "info", "danger"];

function tagType(role: string) {
  const idx = modelTypes.value.findIndex((d) => d.value === role);
  return idx >= 0 ? ROLE_COLORS[idx % ROLE_COLORS.length] : "info";
}

/** 角色展示名：命中字典 model_types 取中文 label，未命中回退英文 role */
const roleLabel = computed(() => dictStore.getLabel("model_types", props.config.role));

// ---------- 图像角色生图规格（存于 extra，由后端 model/image/factory.py 消费） ----------
/** 是否为图像模型（仅该角色展示/可配生图规格参数） */
const isImage = computed(() => props.config.role === "image");

const imageExtra = computed(() => (props.config.extra ?? {}) as Record<string, unknown>);

/** 取 extra 中的字符串型规格值，非字符串/空白视为未配置 */
function extraText(key: string): string {
  const raw = imageExtra.value[key];
  return typeof raw === "string" && raw.trim() ? raw.trim() : "";
}

/** 枚举型规格展示文案：命中字典取 label，未命中回退原始值，未配置显示占位 */
function extraDictLabel(dictType: string, key: string): string {
  const value = extraText(key);
  return value ? dictStore.getLabel(dictType, value) : "—";
}

const imageSizeLabel = computed(() => extraDictLabel("image_size", "size"));
const imageQualityLabel = computed(() => extraDictLabel("image_quality", "quality"));
</script>

<template>
  <el-card class="model-card" shadow="hover">
    <template #header>
      <div class="model-card__header">
        <span class="model-card__title">{{ config.name }}</span>
        <el-tag :type="tagType(config.role)" size="small">{{ roleLabel }}</el-tag>
      </div>
    </template>

    <dl class="model-card__body">
      <div class="model-card__row">
        <dt>模型名</dt>
        <dd>{{ config.model_name }}</dd>
      </div>
      <div class="model-card__row">
        <dt>接口地址</dt>
        <dd class="model-card__mono">{{ config.api_url }}</dd>
      </div>
      <div class="model-card__row">
        <dt>API 密钥</dt>
        <dd class="model-card__mono">{{ config.api_key || "—" }}</dd>
      </div>
      <div v-if="config.provider" class="model-card__row">
        <dt>Provider</dt>
        <dd>{{ providerLabel }}</dd>
      </div>
      <div v-if="config.timeout !== null || config.max_retries !== null" class="model-card__row">
        <dt>超时 / 重试</dt>
        <dd>{{ config.timeout ?? "—" }}s / {{ config.max_retries ?? "—" }} 次</dd>
      </div>
      <div v-if="config.role === 'chat'" class="model-card__row">
        <dt>上下文窗口</dt>
        <dd>{{ contextWindowLabel }}</dd>
      </div>
      <!-- 图像模型：可调生图规格（extra）；输出侧后端写死 webp + 压缩率 80，不入配置也不展示 -->
      <template v-if="isImage">
        <div class="model-card__row">
          <dt>生图尺寸</dt>
          <dd>{{ imageSizeLabel }}</dd>
        </div>
        <div class="model-card__row">
          <dt>图像质量</dt>
          <dd>{{ imageQualityLabel }}</dd>
        </div>
      </template>
    </dl>

    <template #footer>
      <el-button link type="primary" size="small" @click="$emit('edit', config)">编辑</el-button>
    </template>
  </el-card>
</template>

<style scoped>
.model-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.model-card__title {
  font-weight: 600;
  color: #273249;
}

.model-card__body {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.model-card__row {
  display: flex;
  gap: 12px;
  font-size: 13px;
}

.model-card__row dt {
  flex: 0 0 76px;
  color: #8a94a6;
}

.model-card__row dd {
  margin: 0;
  flex: 1;
  color: #273249;
  word-break: break-all;
}

.model-card__mono {
  font-family: var(--el-font-family-mono, monospace);
}
</style>
