<script setup lang="ts">
/**
 * 项目创建/编辑表单对话框（标题 + 故事设定）。
 */
import { computed, reactive, ref, watch } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import type { StoryProjectPayload, StoryProjectVO } from "@/api/story";

const props = defineProps<{
  visible: boolean;
  record: StoryProjectVO | null;
  submitting: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "submit", payload: StoryProjectPayload): void;
}>();

const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit("update:visible", value),
});

const formRef = ref<FormInstance>();
const form = reactive({
  title: "",
  description: "",
});

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return;
    Object.assign(form, {
      title: props.record?.title ?? "",
      description: props.record?.description ?? "",
    });
    formRef.value?.clearValidate();
  }
);

const rules = computed<FormRules>(() => ({
  title: [{ required: true, message: "请输入项目标题", trigger: "blur" }],
}));

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  emit("submit", {
    title: form.title.trim(),
    description: form.description.trim() || null,
  });
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    :title="record ? '编辑项目' : '新建项目'"
    width="560px"
    destroy-on-close
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="项目标题" prop="title">
        <el-input v-model="form.title" maxlength="100" placeholder="如：山海奇谭" />
      </el-form-item>
      <el-form-item label="故事设定">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="5"
          placeholder="故事设定/需求描述，是剧本生成的输入"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
