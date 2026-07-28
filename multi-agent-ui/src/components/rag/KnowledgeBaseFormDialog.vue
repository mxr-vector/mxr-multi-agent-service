<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import type { KnowledgeBase } from "@/api/rag/knowledgeBase";
import { buildDeptTree, type Dept } from "@/api/system/dept";
import { useDictStore } from "@/stores/dictStore";
import type { KnowledgeBaseFormPayload } from "@/components/rag/types";

const props = withDefaults(
    defineProps<{
        visible: boolean;
        record: KnowledgeBase | null;
        submitting: boolean;
        /** 是否展示归属部门选择（仅 data_scope=all；其余档位后端强制本人部门） */
        showDept?: boolean;
        /** 部门扁平列表（复用左树 loaded 事件的数据，避免重复请求） */
        deptList?: Dept[];
        /** 新建时的默认归属部门（左树当前选中节点） */
        defaultDeptId?: string | null;
    }>(),
    { showDept: false, deptList: () => [], defaultDeptId: null },
);

const emit = defineEmits<{
    (e: "update:visible", value: boolean): void;
    (e: "submit", payload: KnowledgeBaseFormPayload): void;
}>();

const dictStore = useDictStore();
dictStore.ensureLoaded();

// 下拉选项均来自全局词典，字典项由字典管理页面维护
const visibilityOptions = computed(() => dictStore.getOptions("visibility_type"));
const statusOptions = computed(() => dictStore.getOptions("status"));

// 归属部门树（仅新建态可选；dept_id 建库后不可变，编辑态只读展示）
const deptTree = computed(() => buildDeptTree(props.deptList));

const formRef = ref<FormInstance>();
const form = reactive<KnowledgeBaseFormPayload>({
    name: "",
    description: "",
    visibility: "private",
    status: "active",
    dept_id: null,
});
const isEdit = computed(() => Boolean(props.record));
// 归属部门必填：仅新建态且 data_scope=all 展示部门选择时生效，
// 与后端“知识库必须归属部门”守卫双重拦截，杜绝游离库
const rules = computed<FormRules>(() => ({
    name: [{ required: true, message: "请输入知识库名称", trigger: "blur" }],
    ...(!isEdit.value && props.showDept
        ? { dept_id: [{ required: true, message: "请选择归属部门", trigger: "change" }] }
        : {}),
}));

const dialogVisible = computed({
    get: () => props.visible,
    set: (v) => emit("update:visible", v),
});

// 弹窗打开时，依据 record 初始化表单；新建态默认挂到左树当前选中部门
watch(
    () => props.visible,
    (v) => {
        if (!v) return;
        Object.assign(form, {
            name: props.record?.name ?? "",
            description: props.record?.description ?? "",
            visibility: props.record?.visibility ?? "private",
            status: props.record?.status ?? "active",
            dept_id: props.record ? null : props.defaultDeptId,
        });
        formRef.value?.clearValidate();
    }
);

async function handleSubmit() {
    const valid = await formRef.value?.validate().catch(() => false);
    if (!valid) return;
    emit("submit", { ...form });
}
</script>

<template>
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑知识库' : '新建知识库'" width="560px">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
            <el-form-item label="名称" prop="name">
                <el-input v-model="form.name" placeholder="请输入知识库名称" maxlength="64" />
            </el-form-item>
            <el-form-item label="可见性">
                <el-select v-model="form.visibility" style="width: 100%">
                    <el-option v-for="opt in visibilityOptions" :key="opt.value" :label="opt.label"
                        :value="opt.value" />
                </el-select>
            </el-form-item>
            <!-- 归属部门：新建态必选（仅 data_scope=all 展示）；编辑态不可变，只读展示 -->
            <el-form-item v-if="!isEdit && showDept" label="归属部门" prop="dept_id">
                <el-tree-select v-model="form.dept_id" :data="deptTree" node-key="id"
                    :props="{ label: 'name', children: 'children' }" check-strictly placeholder="请选择归属部门"
                    style="width: 100%" />
            </el-form-item>
            <el-form-item v-if="isEdit" label="归属部门">
                <el-input :model-value="record?.dept_name || '未归属'" disabled />
            </el-form-item>
            <el-form-item v-if="isEdit" label="状态">
                <el-select v-model="form.status" style="width: 100%">
                    <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
            </el-form-item>
            <el-form-item label="描述">
                <el-input v-model="form.description" type="textarea" :rows="3" placeholder="选填" maxlength="255" />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
        </template>
    </el-dialog>
</template>
