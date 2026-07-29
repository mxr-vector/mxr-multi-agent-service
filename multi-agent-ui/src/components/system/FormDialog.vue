<script setup lang="ts">
// 通用表单弹窗：统一「取消/保存」底栏与提交 loading 态，表单内容由默认插槽提供
withDefaults(
  defineProps<{
    title: string;
    width?: string;
    submitting?: boolean;
    confirmText?: string;
  }>(),
  { width: "520px", submitting: false, confirmText: "保存" }
);

const visible = defineModel<boolean>({ default: false });

const emit = defineEmits<{ submit: [] }>();
</script>

<template>
  <el-dialog v-model="visible" :title="title" :width="width">
    <slot />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="emit('submit')">
        {{ confirmText }}
      </el-button>
    </template>
  </el-dialog>
</template>
