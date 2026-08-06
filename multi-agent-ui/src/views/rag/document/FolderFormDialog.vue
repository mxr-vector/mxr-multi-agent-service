<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import type { Folder } from "@/api/rag/folders";
import { buildFolderTree, collectSubtreeIds } from "@/api/rag/folders";
import type { FolderFormPayload } from "@/views/rag/document/types";

const props = defineProps<{
  visible: boolean;
  record: Folder | null;
  /** 当前知识库内的文件夹列表（上级候选仅限同库） */
  folders: Folder[];
  /** 当前知识库 id，随提交载荷回传；创建后不可变 */
  knowledgeBaseId: string;
  submitting: boolean;
  /** 新建时默认上级文件夹（取自左侧当前选中的文件夹），编辑时忽略 */
  defaultParentId?: string | null;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "submit", payload: FolderFormPayload): void;
}>();

const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  parent_id: null as string | null,
  sort_order: 0,
});
const isEdit = computed(() => Boolean(props.record));
// 上级文件夹候选树：编辑时排除自身及其后代，避免自引用与成环
const parentTree = computed(() => {
  const excluded = props.record ? collectSubtreeIds(props.folders, props.record.id) : null;
  const candidates = excluded ? props.folders.filter((f) => !excluded.has(f.id)) : props.folders;
  return buildFolderTree(candidates);
});
const rules: FormRules = {
  name: [{ required: true, message: "请输入文件夹名称", trigger: "blur" }],
};

const dialogVisible = computed({
  get: () => props.visible,
  set: (v) => emit("update:visible", v),
});

// 弹窗打开时，依据 record 初始化表单
watch(
  () => props.visible,
  (v) => {
    if (!v) return;
    Object.assign(form, {
      name: props.record?.name ?? "",
      parent_id: props.record?.parent_id ?? props.defaultParentId ?? null,
      sort_order: props.record?.sort_order ?? 0,
    });
    formRef.value?.clearValidate();
  }
);

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  emit("submit", {
    name: form.name,
    parent_id: form.parent_id,
    sort_order: form.sort_order,
    knowledge_base_id: props.knowledgeBaseId,
  });
}
</script>

<template>
  <el-dialog v-model="dialogVisible" :title="isEdit ? '修改文件夹' : '新建文件夹'" width="460px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="请输入文件夹名称" maxlength="64" />
      </el-form-item>
      <el-form-item label="上级文件夹">
        <el-tree-select
          v-model="form.parent_id"
          :data="parentTree"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          value-key="id"
          check-strictly
          clearable
          placeholder="顶级文件夹"
          :render-after-expand="false"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="排序">
        <el-input-number v-model="form.sort_order" :min="0" :max="9999" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
