<script setup lang="ts">
import { ref } from "vue";

const props = defineProps<{
  uploading: boolean;
  disabled: boolean;
}>();

const emit = defineEmits<{
  (e: "file-selected", file: File): void;
  (e: "blocked"): void;
}>();

const fileInput = ref<HTMLInputElement>();

// 打开系统文件选择框；未选择知识库时通知父组件拦截
function open() {
  if (props.disabled) {
    emit("blocked");
    return;
  }
  fileInput.value?.click();
}

function onChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) emit("file-selected", file);
  input.value = "";
}

defineExpose({ open });
</script>

<template>
  <div>
    <input
      ref="fileInput"
      type="file"
      accept=".pdf,.docx,.md,.markdown,.txt,.xlsx,.xls"
      hidden
      @change="onChange"
    />
    <section class="upload-zone">
      <span class="upload-icon">↑</span>
      <div>
        <strong>选择本地文件上传到当前知识库</strong>
        <p>支持 PDF、DOCX、Markdown、Excel、TXT，上传后自动解析与两级切块</p>
      </div>
      <button type="button" :disabled="uploading" @click="open">选择文件</button>
    </section>
  </div>
</template>

<style scoped>
.upload-zone {
  display: flex;
  align-items: center;
  gap: 15px;
  padding: 20px 24px;
  border: 1px dashed #b8c4ed;
  border-radius: 13px;
  background: #f9faff;
}

.upload-icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 10px;
  color: #526ae2;
  background: #e9edff;
  font-size: 21px;
}

.upload-zone strong {
  font-size: 13px;
}

.upload-zone p {
  margin: 5px 0 0;
  color: #7d879a;
  font-size: 12px;
}

.upload-zone button {
  margin-left: auto;
  padding: 8px 11px;
  border: 1px solid #dfe4ef;
  border-radius: 8px;
  color: #59657b;
  background: #fff;
  font-size: 12px;
}

.upload-zone button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 720px) {
  .upload-zone {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .upload-zone button {
    margin-left: 53px;
  }
}
</style>
