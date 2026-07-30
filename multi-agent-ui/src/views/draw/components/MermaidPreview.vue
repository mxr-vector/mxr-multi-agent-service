<script setup lang="ts">
/**
 * Mermaid 预览组件：流式节流渲染（失败静默）+ 终版渲染 + 失败兜底展示源码。
 *
 * - streaming 期间每 500ms 尝试渲染一次当前累积源码，语法不完整的中间态
 *   渲染失败不提示、保留上一帧成功画面；
 * - 流结束（streaming=false）后以完整源码为准渲染终版，仍失败则展示源码
 *   文本与错误说明，并抛出 regenerate 事件供父层提供"重新生成"入口。
 */
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import mermaid from "mermaid";

const props = defineProps<{
    /** Mermaid 源码（流式期间为累积中间态） */
    source: string;
    /** 是否处于流式生成中 */
    streaming?: boolean;
    /** 渲染失败时是否展示重新生成按钮 */
    canRegenerate?: boolean;
}>();

const emit = defineEmits<{ (e: "regenerate"): void }>();

mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });

const containerRef = ref<HTMLDivElement | null>(null);
const failed = ref(false);
const errorText = ref("");

let renderTimer: number | null = null;
let renderSeq = 0;

async function render(source: string, silent: boolean) {
    const target = containerRef.value;
    const code = source.trim();
    if (!target || !code) return;
    const seq = (renderSeq += 1);
    try {
        // 每次用唯一 id，避免 mermaid 内部残留节点冲突
        const { svg } = await mermaid.render(`draw-preview-${seq}`, code);
        if (seq !== renderSeq || !containerRef.value) return;
        // svg 为 mermaid 在 securityLevel=strict 下生成的产物（标签 HTML 已转义、
        // 禁用 click 交互），非用户原始字符串，可安全注入
        containerRef.value.innerHTML = svg;
        failed.value = false;
        errorText.value = "";
    } catch (err: any) {
        // 流式中间态渲染失败静默容忍；终版失败展示源码兜底
        if (!silent) {
            failed.value = true;
            errorText.value = err?.message ?? "Mermaid 渲染失败";
        }
        // mermaid.render 失败可能残留孤儿节点，清理避免污染文档
        document.getElementById(`draw-preview-${seq}`)?.remove();
    }
}

watch(
    () => [props.source, props.streaming] as const,
    ([source, streaming]) => {
        if (streaming) {
            // 节流：500ms 内最多尝试一次中间态渲染
            if (renderTimer != null) return;
            renderTimer = window.setTimeout(() => {
                renderTimer = null;
                void render(props.source, true);
            }, 500);
        } else {
            if (renderTimer != null) {
                window.clearTimeout(renderTimer);
                renderTimer = null;
            }
            void nextTick(() => render(source, false));
        }
    },
    { immediate: true }
);

onBeforeUnmount(() => {
    if (renderTimer != null) window.clearTimeout(renderTimer);
});
</script>

<template>
    <div class="mermaid-preview">
        <div v-show="!failed" ref="containerRef" class="mermaid-canvas"></div>
        <div v-if="failed" class="mermaid-fallback">
            <p class="fallback-title">图表渲染失败，以下为生成的 Mermaid 源码：</p>
            <pre class="fallback-code">{{ source }}</pre>
            <p class="fallback-error">{{ errorText }}</p>
            <button v-if="canRegenerate" type="button" class="primary-button" @click="emit('regenerate')">
                重新生成
            </button>
        </div>
    </div>
</template>

<style scoped>
.mermaid-preview {
    width: 100%;
    height: 100%;
    overflow: auto;
}

.mermaid-canvas {
    display: flex;
    justify-content: center;
    padding: 12px;
}

.mermaid-canvas :deep(svg) {
    max-width: 100%;
    height: auto;
}

.mermaid-fallback {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px;
}

.fallback-title {
    color: #b45309;
    font-size: 13px;
}

.fallback-code {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    font-size: 12px;
    max-height: 260px;
    overflow: auto;
    padding: 12px;
    white-space: pre-wrap;
    word-break: break-all;
}

.fallback-error {
    color: #dc2626;
    font-size: 12px;
}
</style>
