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
    props.config.provider
        ? dictStore.getLabel("embedding_provider", props.config.provider)
        : ""
);

/** 角色标签配色（仅视觉区分，无业务语义） */
const ROLE_TAG: Record<string, string> = {
    chat: "primary",
    rewrite: "success",
    visual: "warning",
    rerank: "info",
};

function tagType(role: string) {
    return ROLE_TAG[role] ?? "info";
}
</script>

<template>
    <el-card class="model-card" shadow="hover">
        <template #header>
            <div class="model-card__header">
                <span class="model-card__title">{{ config.name }}</span>
                <el-tag :type="tagType(config.role)" size="small">{{ config.role }}</el-tag>
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
            <div v-if="config.timeout !== null" class="model-card__row">
                <dt>超时 / 重试</dt>
                <dd>{{ config.timeout }}s / {{ config.max_retries ?? "—" }} 次</dd>
            </div>
            <div v-if="config.role === 'chat'" class="model-card__row">
                <dt>上下文窗口</dt>
                <dd>{{ contextWindowLabel }}</dd>
            </div>
        </dl>

        <template #footer>
            <el-button link type="primary" size="small" @click="$emit('edit', config)">
                编辑
            </el-button>
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
