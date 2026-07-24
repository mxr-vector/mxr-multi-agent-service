<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import type { KnowledgeBase } from '@/api/rag/knowledgeBase'
import type { DocumentUploadFormPayload } from '@/components/rag/types'

const props = defineProps<{
    visible: boolean
    uploading: boolean
    knowledgeBases: KnowledgeBase[]
    /** 默认选中的知识库（取自筛选栏当前知识库） */
    defaultKbId: string | null
    /** 默认归属文件夹（取自左侧当前选中的文件夹），弹窗内不再提供分类选择 */
    defaultCategoryId: string | null
}>()

const emit = defineEmits<{
    (e: 'update:visible', value: boolean): void
    (e: 'submit', payload: DocumentUploadFormPayload): void
}>()

const formRef = ref<FormInstance>()
const fileInput = ref<HTMLInputElement>()
const selectedFile = ref<File | null>(null)
// 有效期起止（daterange，ISO 字符串数组）；留空表示长期有效
const dateRange = ref<[string, string] | null>(null)
// 表格类：后端依据文件扩展名自动判定 doc_type，这里仅作展示，随所选文件自动勾选，不参与提交
const isSpreadsheet = ref(false)

const form = reactive({
    title: '',
    knowledge_base_id: '' as string,
    remark: '',
})

const dialogVisible = computed({
    get: () => props.visible,
    set: (v) => emit('update:visible', v),
})

const rules: FormRules = {
    title: [{ required: true, message: '请输入手册名称', trigger: 'blur' }],
    knowledge_base_id: [{ required: true, message: '请选择知识库', trigger: 'change' }],
}

// 弹窗打开时重置表单，默认选中当前知识库
watch(
    () => props.visible,
    (v) => {
        if (!v) return
        form.knowledge_base_id = props.defaultKbId ?? ''
        form.title = ''
        form.remark = ''
        selectedFile.value = null
        dateRange.value = null
        isSpreadsheet.value = false
        formRef.value?.clearValidate()
    }
)

const SPREADSHEET_EXT = /\.(xlsx|xls|csv)$/i

function pickFile() {
    fileInput.value?.click()
}

function onFileChange(event: Event) {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    if (file) {
        selectedFile.value = file
        // 文件名缺省作为手册名称，便于用户直接提交
        if (!form.title) form.title = file.name.replace(/\.[^.]+$/, '')
        // 表格类随文件扩展名自动判定
        isSpreadsheet.value = SPREADSHEET_EXT.test(file.name)
    }
    input.value = ''
}

async function handleSubmit() {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    if (!selectedFile.value) {
        ElMessage.warning('请先选择要上传的文件')
        return
    }
    emit('submit', {
        file: selectedFile.value,
        knowledge_base_id: form.knowledge_base_id,
        category_id: props.defaultCategoryId,
        title: form.title.trim() || selectedFile.value.name,
        valid_from: dateRange.value?.[0],
        valid_until: dateRange.value?.[1],
        remark: form.remark.trim(),
    })
}
</script>

<template>
    <el-dialog v-model="dialogVisible" title="新建文档" width="620px">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
            <el-form-item label="手册名称" prop="title">
                <el-input v-model="form.title" placeholder="请输入手册名称" maxlength="50" show-word-limit />
            </el-form-item>
            <el-form-item label="有效期">
                <el-date-picker v-model="dateRange" type="daterange" range-separator="至" start-placeholder="开始日期"
                    end-placeholder="结束日期" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            </el-form-item>
            <el-form-item label="文件" required>
                <div class="file-row">
                    <input ref="fileInput" type="file" accept=".pdf,.docx,.md,.markdown,.txt,.xlsx,.xls,.csv" hidden
                        @change="onFileChange" />
                    <span class="file-name" :class="{ placeholder: !selectedFile }">{{
                        selectedFile ? selectedFile.name : '支持 PDF、DOCX、Markdown、Excel、TXT' }}</span>
                    <el-button link type="primary" @click="pickFile">浏览</el-button>
                </div>
            </el-form-item>
            <el-form-item label="表格类">
                <!-- doc_type 由后端依据文件类型自动判定，此处随所选文件展示 -->
                <el-checkbox v-model="isSpreadsheet" disabled>是</el-checkbox>
            </el-form-item>
            <el-form-item label="AI知识库" prop="knowledge_base_id">
                <el-select v-model="form.knowledge_base_id" placeholder="选择知识库" style="width: 100%">
                    <el-option v-for="b in knowledgeBases" :key="b.id" :label="b.name" :value="b.id" />
                </el-select>
            </el-form-item>
            <!-- AI 标签：后端暂未提供标签维度，占位以匹配设计稿 -->
            <el-form-item label="AI标签">
                <el-select placeholder="选择标签" disabled style="width: 100%">
                    <el-option label="全部" value="" />
                </el-select>
            </el-form-item>
            <el-form-item label="备注">
                <el-input v-model="form.remark" type="textarea" :rows="4" placeholder="选填" maxlength="500"
                    show-word-limit />
            </el-form-item>
        </el-form>
        <template #footer>
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="uploading" @click="handleSubmit">确定</el-button>
        </template>
    </el-dialog>
</template>

<style scoped>
.file-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 0 12px;
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    background: #fff;
}

.file-name {
    flex: 1;
    overflow: hidden;
    color: #4d5970;
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
    line-height: 32px;
}

.file-name.placeholder {
    color: #9aa3b5;
}
</style>
