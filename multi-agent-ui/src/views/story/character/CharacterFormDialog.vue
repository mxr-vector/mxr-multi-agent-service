<script setup lang="ts">
/**
 * 角色创建/编辑表单对话框。
 * 人设（profile）与视觉风格（style）以键值对逐条录入（KeyValueEditor），
 * 无需手写 JSON；每行「项 + 值」，如 性格=坚毅。
 */
import { computed, reactive, ref, watch } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import type { StoryCharacterPayload, StoryCharacterVO, StoryRoleType } from "@/api/story";
import KeyValueEditor from "./KeyValueEditor.vue";

const props = defineProps<{
  visible: boolean;
  record: StoryCharacterVO | null;
  submitting: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "submit", payload: StoryCharacterPayload): void;
}>();

const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit("update:visible", value),
});

const ROLE_TYPE_OPTIONS: { value: StoryRoleType; label: string }[] = [
  { value: "protagonist", label: "主角" },
  { value: "supporting", label: "配角" },
  { value: "antagonist", label: "反派" },
  { value: "npc", label: "NPC" },
  { value: "other", label: "其他" },
];

const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  role_type: "" as StoryRoleType | "",
  appearance_prompt: "",
  negative_prompt: "",
  profile: {} as Record<string, unknown>,
  style: {} as Record<string, unknown>,
});

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return;
    const record = props.record;
    Object.assign(form, {
      name: record?.name ?? "",
      role_type: record?.role_type ?? "",
      appearance_prompt: record?.appearance_prompt ?? "",
      negative_prompt: record?.negative_prompt ?? "",
      profile: { ...(record?.profile ?? {}) },
      style: { ...(record?.style ?? {}) },
    });
    formRef.value?.clearValidate();
  }
);

const rules = computed<FormRules>(() => ({
  name: [{ required: true, message: "请输入角色名", trigger: "blur" }],
}));

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  emit("submit", {
    name: form.name.trim(),
    role_type: form.role_type || null,
    appearance_prompt: form.appearance_prompt.trim() || null,
    negative_prompt: form.negative_prompt.trim() || null,
    profile: form.profile,
    style: form.style,
  });
}
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    :title="record ? '编辑角色' : '新建角色'"
    width="640px"
    destroy-on-close
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item label="角色名" prop="name">
        <el-input v-model="form.name" maxlength="100" placeholder="如：林晚" />
      </el-form-item>
      <el-form-item label="角色分类">
        <el-select v-model="form.role_type" clearable placeholder="默认分类（跨项目可不同）">
          <el-option
            v-for="option in ROLE_TYPE_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="外观描述">
        <el-input
          v-model="form.appearance_prompt"
          type="textarea"
          :rows="3"
          placeholder="供生图模型复用的外观描述，如：黑发少年，琥珀色眼睛…"
        />
      </el-form-item>
      <el-form-item label="负向提示词">
        <el-input v-model="form.negative_prompt" type="textarea" :rows="2" placeholder="可选" />
      </el-form-item>
      <el-form-item label="人设">
        <KeyValueEditor
          v-model="form.profile"
          key-placeholder="项，如：性格"
          value-placeholder="内容，如：坚毅"
        />
      </el-form-item>
      <el-form-item label="视觉风格">
        <KeyValueEditor
          v-model="form.style"
          key-placeholder="项，如：画风"
          value-placeholder="内容，如：手绘"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
