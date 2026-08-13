<script setup lang="ts">
/**
 * drawio 编辑弹窗：embed iframe 加载基线版本 → 用户编辑 → 保存产生新版本。
 *
 * - AI 版本（无 drawio_xml）经 mermaid descriptor（wrap:true）加载；
 *   用户编辑版本以其 drawio XML 加载；
 * - 保存：依次 export xml 与 xmlpng（内嵌 XML 的 PNG 预览），交由父层调用
 *   保存接口 append-only 新增版本；关闭未保存不产生任何记录。
 */
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import type { DrawVersionVO } from "@/api/draw";
import { dataUriToBlob, useDrawioEmbed } from "../composables/useDrawioEmbed";

const props = defineProps<{
  visible: boolean;
  /** 编辑基线版本（须已携带 drawio_xml：由父层经版本详情接口取得） */
  version: DrawVersionVO | null;
  saving?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "save", payload: { parent: DrawVersionVO; drawio_xml: string; preview: Blob | null }): void;
}>();

const iframeRef = ref<HTMLIFrameElement | null>(null);
const loading = ref(true);

const embed = useDrawioEmbed(iframeRef, {
  onInit: () => loadCurrentVersion(),
  onLoad: () => {
    loading.value = false;
  },
});

// 每次打开弹窗重新求值，使运行参数中的 drawio 地址修改后免刷新生效
const drawioSrc = computed(() => (props.visible ? embed.embedSrc() : ""));

function loadCurrentVersion() {
  const version = props.version;
  if (!version) return;
  if (version.drawio_xml) {
    // 用户编辑版本：直接加载上次保存的 drawio XML
    embed.loadXml(version.drawio_xml);
  } else if (version.mermaid_source) {
    // AI 版本：mermaid descriptor 导入（wrap:true 保留源可再编辑）
    embed.loadMermaid(version.mermaid_source);
  }
}

// 弹窗每次打开重挂 iframe（:key 驱动），复位协议状态等待新 init
watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      loading.value = true;
      embed.reset();
    }
  }
);

async function handleSave() {
  if (!props.version) return;
  try {
    // 先取 XML（必需），再取 xmlpng 预览（失败不阻塞保存）
    const xmlResult = await embed.exportDiagram("xml");
    const xml = xmlResult.xml ?? "";
    if (!xml) {
      ElMessage.error("未能从编辑器取得图表内容");
      return;
    }
    let preview: Blob | null = null;
    try {
      const pngResult = await embed.exportDiagram("xmlpng");
      if (pngResult.data) preview = dataUriToBlob(pngResult.data);
    } catch {
      // 预览导出失败可容忍：版本仍可保存，预览走 XML 重载
    }
    emit("save", { parent: props.version, drawio_xml: xml, preview });
  } catch (err: any) {
    ElMessage.error(err?.message ?? "导出图表失败，请重试");
  }
}

function handleClose() {
  emit("update:visible", false);
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="编辑图表"
    width="86%"
    top="4vh"
    :close-on-click-modal="false"
    destroy-on-close
    class="drawio-dialog"
    @update:model-value="emit('update:visible', $event)"
  >
    <div
      v-loading="loading"
      element-loading-text="正在加载 drawio 编辑器…"
      class="drawio-editor-wrap"
    >
      <iframe
        v-if="visible"
        :key="version?.id ?? 'blank'"
        ref="iframeRef"
        :src="drawioSrc"
        class="drawio-frame"
        title="drawio 编辑器"
      ></iframe>
    </div>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading" @click="handleSave">
        保存为新版本
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.drawio-editor-wrap {
  height: 72vh;
}

.drawio-frame {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  height: 100%;
  width: 100%;
}
</style>
