<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import type { Category } from '@/api/rag/categories'
import type { CategoryFormPayload } from '@/components/rag/types'

const props = defineProps<{
    visible: boolean
    record: Category | null
    categories: Category[]
    submitting: boolean
}>()

const emit = defineEmits<{
    (e: 'update:visible', value: boolean): void
    (e: 'submit', payload: CategoryFormPayload): void
}>()

const formRef = ref<FormInstance>()
const form = reactive<CategoryFormPayload>({
    name: '',
    parent_id: null,
    sort_order: 0,
})
const isEdit = computed(() => Boolean(props.record))
// 上级分类候选：编辑时排除自身，避免自引用
const parentOptions = computed(() => props.categories.filter((c) => c.id !== props.record?.id))
const rules: FormRules = {
    name: [{ required: true, message: '请输入分类名称', trigger: 'blur' }],
}

const dialogVisible = computed({
    get: () => props.visible,
    set: (v) => emit('update:visible', v),
})

// 弹窗打开时，依据 record 初始化表单
watch(
    () => props.visible,
    (v) => {
        if (!v) return
        Object.assign(form, {
            name: props.record?.name ?? '',
            parent_id: props.record?.parent_id ?? null,
            sort_order: props.record?.sort_order ?? 0,
        })
        formRef.value?.clearValidate()
    }
)

async function handleSubmit() {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    emit('submit', { name: form.name, parent_id: form.parent_id, sort_order: form.sort_order })
}
</script>

<template>
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑分类' : '新建分类'" width="460px">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
            <el-form-item label="名称" prop="name">
                <el-input v-model="form.name" placeholder="请输入分类名称" maxlength="64" />
            </el-form-item>
            <el-form-item label="上级分类">
                <el-select v-model="form.parent_id" clearable placeholder="顶级分类" style="width: 100%">
                    <el-option v-for="c in parentOptions" :key="c.id" :label="c.name" :value="c.id" />
                </el-select>
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
