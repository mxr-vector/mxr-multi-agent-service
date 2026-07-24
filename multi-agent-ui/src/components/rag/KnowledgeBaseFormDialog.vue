<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import type { KnowledgeBase } from '@/api/rag/knowledgeBase'
import type { Category } from '@/api/rag/categories'
import { buildCategoryTree } from '@/api/rag/categories'
import type { KnowledgeBaseFormPayload } from '@/components/rag/types'

const props = defineProps<{
    visible: boolean
    record: KnowledgeBase | null
    categories: Category[]
    submitting: boolean
}>()

const emit = defineEmits<{
    (e: 'update:visible', value: boolean): void
    (e: 'submit', payload: KnowledgeBaseFormPayload): void
}>()

const formRef = ref<FormInstance>()
const form = reactive<KnowledgeBaseFormPayload>({
    name: '',
    description: '',
    category_id: null,
    visibility: 'private',
    status: 'active',
})
const isEdit = computed(() => Boolean(props.record))
// 分类树（扁平 parent_id 列表组装为树，供树形下拉选择）
const categoryTree = computed(() => buildCategoryTree(props.categories))
const rules: FormRules = {
    name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
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
            description: props.record?.description ?? '',
            category_id: props.record?.category_id ?? null,
            visibility: props.record?.visibility ?? 'private',
            status: props.record?.status ?? 'active',
        })
        formRef.value?.clearValidate()
    }
)

async function handleSubmit() {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    emit('submit', { ...form })
}
</script>

<template>
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑知识库' : '新建知识库'" width="560px">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
            <el-form-item label="名称" prop="name">
                <el-input v-model="form.name" placeholder="请输入知识库名称" maxlength="64" />
            </el-form-item>
            <el-form-item label="分类">
                <el-tree-select v-model="form.category_id" :data="categoryTree"
                    :props="{ label: 'name', children: 'children' }" node-key="id" value-key="id" check-strictly
                    clearable placeholder="未分类" :render-after-expand="false" style="width: 100%" />
            </el-form-item>
            <el-form-item label="可见性">
                <el-select v-model="form.visibility" style="width: 100%">
                    <el-option label="私有" value="private" />
                    <el-option label="公开" value="public" />
                </el-select>
            </el-form-item>
            <el-form-item v-if="isEdit" label="状态">
                <el-select v-model="form.status" style="width: 100%">
                    <el-option label="已启用" value="active" />
                    <el-option label="已归档" value="archived" />
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
