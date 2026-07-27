<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import {
    dictTypeApi,
    dictDataApi,
    type DictType,
    type DictData,
} from "@/api/system/dict";
import { confirmDanger } from "@/utils/confirm";
import SearchInput from "@/components/SearchInput.vue";
import Pagination from "@/components/Pagination.vue";

// ---------- 字典类型（左侧） ----------

const typeLoading = ref(false);
const typeList = ref<DictType[]>([]);
const typeKeyword = ref("");
const typePage = ref(1);
const typeSize = ref(20);
const typeTotal = ref(0);

// 当前选中的类型（右侧字典数据联动数据源）
const selectedType = ref<DictType | null>(null);

async function loadTypes() {
    typeLoading.value = true;
    try {
        const res = await dictTypeApi.list({
            page: typePage.value,
            size: typeSize.value,
            keyword: typeKeyword.value.trim() || undefined,
        });
        typeList.value = res.data?.items ?? [];
        typeTotal.value = res.data?.total ?? 0;
        // 选中项不在当前页时自动纠正选中态
        if (selectedType.value) {
            const hit = typeList.value.find((t) => t.id === selectedType.value?.id);
            selectedType.value = hit ?? null;
        }
        if (!selectedType.value && typeList.value.length) {
            selectedType.value = typeList.value[0];
        }
    } finally {
        typeLoading.value = false;
    }
}

// 关键词防抖：变更后回到第 1 页并触发服务端重载
let typeKeywordTimer: ReturnType<typeof setTimeout> | undefined;
watch(typeKeyword, () => {
    if (typeKeywordTimer) clearTimeout(typeKeywordTimer);
    typeKeywordTimer = setTimeout(() => {
        typePage.value = 1;
        loadTypes();
    }, 300);
});

// 选中类型变化时重载右侧字典数据
watch(selectedType, () => {
    dataPage.value = 1;
    loadDataList();
});

function handleTypeRowClick(row: DictType) {
    selectedType.value = row;
}

// 类型新建 / 编辑弹窗
const typeDialogVisible = ref(false);
const typeSubmitting = ref(false);
const editingType = ref<DictType | null>(null);
const typeFormRef = ref<FormInstance>();
const typeForm = reactive({
    name: "",
    type: "",
    status: "active",
    remark: "",
});
const typeRules: FormRules = {
    name: [{ required: true, message: "请输入字典名称", trigger: "blur" }],
    type: [{ required: true, message: "请输入类型键", trigger: "blur" }],
};

function openTypeCreate() {
    editingType.value = null;
    Object.assign(typeForm, { name: "", type: "", status: "active", remark: "" });
    typeDialogVisible.value = true;
    typeFormRef.value?.clearValidate();
}

function openTypeEdit(row: DictType) {
    editingType.value = row;
    Object.assign(typeForm, {
        name: row.name,
        type: row.type,
        status: row.status,
        remark: row.remark ?? "",
    });
    typeDialogVisible.value = true;
    typeFormRef.value?.clearValidate();
}

async function submitType() {
    const valid = await typeFormRef.value?.validate().catch(() => false);
    if (!valid) return;
    typeSubmitting.value = true;
    try {
        if (editingType.value) {
            await dictTypeApi.update(editingType.value.id, {
                name: typeForm.name,
                type: typeForm.type,
                status: typeForm.status,
                remark: typeForm.remark || null,
            });
            ElMessage.success("字典类型已更新");
        } else {
            await dictTypeApi.create({
                name: typeForm.name,
                type: typeForm.type,
                status: typeForm.status,
                remark: typeForm.remark || null,
            });
            ElMessage.success("字典类型已创建");
        }
        typeDialogVisible.value = false;
        await loadTypes();
    } finally {
        typeSubmitting.value = false;
    }
}

async function removeType(row: DictType) {
    const confirmed = await confirmDanger(
        `确定删除字典类型「${row.name}」吗？类型下仍有字典数据时将被拒绝。`
    );
    if (!confirmed) return;
    await dictTypeApi.remove(row.id);
    ElMessage.success("字典类型已删除");
    if (selectedType.value?.id === row.id) selectedType.value = null;
    await loadTypes();
}

// ---------- 字典数据（右侧，按选中类型联动） ----------

const dataLoading = ref(false);
const dataList = ref<DictData[]>([]);
const dataKeyword = ref("");
const dataPage = ref(1);
const dataSize = ref(20);
const dataTotal = ref(0);

async function loadDataList() {
    if (!selectedType.value) {
        dataList.value = [];
        dataTotal.value = 0;
        return;
    }
    dataLoading.value = true;
    try {
        const res = await dictDataApi.list({
            page: dataPage.value,
            size: dataSize.value,
            dict_type: selectedType.value.type,
            keyword: dataKeyword.value.trim() || undefined,
        });
        dataList.value = res.data?.items ?? [];
        dataTotal.value = res.data?.total ?? 0;
    } finally {
        dataLoading.value = false;
    }
}

let dataKeywordTimer: ReturnType<typeof setTimeout> | undefined;
watch(dataKeyword, () => {
    if (dataKeywordTimer) clearTimeout(dataKeywordTimer);
    dataKeywordTimer = setTimeout(() => {
        dataPage.value = 1;
        loadDataList();
    }, 300);
});

// 数据新建 / 编辑弹窗
const dataDialogVisible = ref(false);
const dataSubmitting = ref(false);
const editingData = ref<DictData | null>(null);
const dataFormRef = ref<FormInstance>();
const dataForm = reactive({
    label: "",
    value: "",
    sort_order: 0,
    is_default: false,
    status: "active",
    remark: "",
});
const dataRules: FormRules = {
    label: [{ required: true, message: "请输入标签", trigger: "blur" }],
    value: [{ required: true, message: "请输入键值", trigger: "blur" }],
};

function openDataCreate() {
    if (!selectedType.value) return;
    editingData.value = null;
    Object.assign(dataForm, {
        label: "",
        value: "",
        sort_order: 0,
        is_default: false,
        status: "active",
        remark: "",
    });
    dataDialogVisible.value = true;
    dataFormRef.value?.clearValidate();
}

function openDataEdit(row: DictData) {
    editingData.value = row;
    Object.assign(dataForm, {
        label: row.label,
        value: row.value,
        sort_order: row.sort_order,
        is_default: row.is_default,
        status: row.status,
        remark: row.remark ?? "",
    });
    dataDialogVisible.value = true;
    dataFormRef.value?.clearValidate();
}

async function submitData() {
    const valid = await dataFormRef.value?.validate().catch(() => false);
    if (!valid) return;
    dataSubmitting.value = true;
    try {
        if (editingData.value) {
            await dictDataApi.update(editingData.value.id, {
                label: dataForm.label,
                value: dataForm.value,
                sort_order: dataForm.sort_order,
                is_default: dataForm.is_default,
                status: dataForm.status,
                remark: dataForm.remark || null,
            });
            ElMessage.success("字典数据已更新");
        } else {
            await dictDataApi.create({
                dict_type: selectedType.value!.type,
                label: dataForm.label,
                value: dataForm.value,
                sort_order: dataForm.sort_order,
                is_default: dataForm.is_default,
                status: dataForm.status,
                remark: dataForm.remark || null,
            });
            ElMessage.success("字典数据已创建");
        }
        dataDialogVisible.value = false;
        await loadDataList();
    } finally {
        dataSubmitting.value = false;
    }
}

async function removeData(row: DictData) {
    const confirmed = await confirmDanger(`确定删除字典数据「${row.label}」吗？`);
    if (!confirmed) return;
    await dictDataApi.remove(row.id);
    ElMessage.success("字典数据已删除");
    await loadDataList();
}

onMounted(loadTypes);
</script>

<template>
    <section class="system-page dict-layout">
        <!-- 左侧：字典类型 -->
        <section class="content-card list-panel" v-loading="typeLoading" element-loading-text="加载中…">
            <div class="toolbar">
                <div>
                    <h2>字典类型</h2>
                    <span>共 {{ typeTotal }} 个类型</span>
                </div>
                <div class="toolbar-actions">
                    <SearchInput v-model="typeKeyword" placeholder="搜索名称 / 类型键" />
                    <button class="primary-button" type="button" @click="openTypeCreate">＋ 新建类型</button>
                </div>
            </div>
            <el-table class="list-scroll" :data="typeList" highlight-current-row :row-key="(r: DictType) => r.id"
                :current-row-key="selectedType?.id" @row-click="handleTypeRowClick">
                <el-table-column prop="name" label="字典名称" min-width="120" show-overflow-tooltip />
                <el-table-column prop="type" label="类型键" min-width="140" show-overflow-tooltip />
                <el-table-column label="状态" width="80">
                    <template #default="{ row }">
                        <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                            {{ row.status === "active" ? "启用" : "停用" }}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column label="操作" width="120" fixed="right">
                    <template #default="{ row }">
                        <el-button link type="primary" size="small" @click.stop="openTypeEdit(row)">编辑</el-button>
                        <el-button link type="danger" size="small" @click.stop="removeType(row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div class="pagination-bar list-footer">
                <Pagination v-model:page="typePage" v-model:size="typeSize" :total="typeTotal" @change="loadTypes" />
            </div>
        </section>

        <!-- 右侧：选中类型的字典数据 -->
        <section class="content-card list-panel" v-loading="dataLoading" element-loading-text="加载中…">
            <div class="toolbar">
                <div>
                    <h2>字典数据</h2>
                    <span>{{ selectedType ? `类型键：${selectedType.type}` : "请先在左侧选择字典类型" }}</span>
                </div>
                <div class="toolbar-actions">
                    <SearchInput v-model="dataKeyword" placeholder="搜索标签" />
                    <button class="primary-button" type="button" :disabled="!selectedType" @click="openDataCreate">
                        ＋ 新建数据
                    </button>
                </div>
            </div>
            <el-table class="list-scroll" :data="dataList">
                <el-table-column prop="label" label="标签" min-width="110" show-overflow-tooltip />
                <el-table-column prop="value" label="键值" min-width="100" show-overflow-tooltip />
                <el-table-column prop="sort_order" label="排序" width="70" />
                <el-table-column label="默认" width="70">
                    <template #default="{ row }">
                        <el-tag v-if="row.is_default" type="warning" size="small">默认</el-tag>
                        <span v-else>—</span>
                    </template>
                </el-table-column>
                <el-table-column label="状态" width="80">
                    <template #default="{ row }">
                        <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                            {{ row.status === "active" ? "启用" : "停用" }}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.remark || "—" }}</template>
                </el-table-column>
                <el-table-column label="操作" width="120" fixed="right">
                    <template #default="{ row }">
                        <el-button link type="primary" size="small" @click="openDataEdit(row)">编辑</el-button>
                        <el-button link type="danger" size="small" @click="removeData(row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div class="pagination-bar list-footer">
                <Pagination v-model:page="dataPage" v-model:size="dataSize" :total="dataTotal" @change="loadDataList" />
            </div>
        </section>

        <!-- 字典类型 新建/编辑 弹窗 -->
        <el-dialog v-model="typeDialogVisible" :title="editingType ? '编辑字典类型' : '新建字典类型'" width="520px">
            <el-form ref="typeFormRef" :model="typeForm" :rules="typeRules" label-width="90px">
                <el-form-item label="字典名称" prop="name">
                    <el-input v-model="typeForm.name" placeholder="如：用户性别" maxlength="100" />
                </el-form-item>
                <el-form-item label="类型键" prop="type">
                    <el-input v-model="typeForm.type" placeholder="如：sys_sex（全局唯一）" maxlength="100" />
                </el-form-item>
                <el-form-item label="状态">
                    <el-select v-model="typeForm.status" style="width: 100%">
                        <el-option label="启用" value="active" />
                        <el-option label="停用" value="disabled" />
                    </el-select>
                </el-form-item>
                <el-form-item label="备注">
                    <el-input v-model="typeForm.remark" type="textarea" :rows="3" placeholder="选填" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="typeDialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="typeSubmitting" @click="submitType">保存</el-button>
            </template>
        </el-dialog>

        <!-- 字典数据 新建/编辑 弹窗 -->
        <el-dialog v-model="dataDialogVisible" :title="editingData ? '编辑字典数据' : '新建字典数据'" width="520px">
            <el-form ref="dataFormRef" :model="dataForm" :rules="dataRules" label-width="90px">
                <el-form-item label="所属类型">
                    <el-input :model-value="editingData?.dict_type ?? selectedType?.type ?? ''" disabled />
                </el-form-item>
                <el-form-item label="标签" prop="label">
                    <el-input v-model="dataForm.label" placeholder="如：男" maxlength="100" />
                </el-form-item>
                <el-form-item label="键值" prop="value">
                    <el-input v-model="dataForm.value" placeholder="如：1" maxlength="100" />
                </el-form-item>
                <el-form-item label="排序">
                    <el-input-number v-model="dataForm.sort_order" :min="0" />
                </el-form-item>
                <el-form-item label="默认选项">
                    <el-switch v-model="dataForm.is_default" />
                </el-form-item>
                <el-form-item label="状态">
                    <el-select v-model="dataForm.status" style="width: 100%">
                        <el-option label="启用" value="active" />
                        <el-option label="停用" value="disabled" />
                    </el-select>
                </el-form-item>
                <el-form-item label="备注">
                    <el-input v-model="dataForm.remark" type="textarea" :rows="3" placeholder="选填" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="dataDialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="dataSubmitting" @click="submitData">保存</el-button>
            </template>
        </el-dialog>
    </section>
</template>

<style scoped>
/* 左右双栏：左类型 / 右数据，窄屏退化为上下堆叠 */
.dict-layout {
    display: grid;
    grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
    /* 行高钉在容器高度，让两个 list-panel 各自内滚、分页固定底部 */
    grid-template-rows: minmax(0, 1fr);
    gap: 20px;
    height: 100%;
    min-height: 0;
    color: #273249;
}

.toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 19px 20px;
    border-bottom: 1px solid #edf0f5;
}

.toolbar-actions {
    display: flex;
    align-items: center;
    gap: 12px;
}

.toolbar span {
    color: #7d879a;
    font-size: 12px;
}

h2 {
    margin: 0 0 4px;
    font-size: 16px;
}

.content-card {
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.primary-button {
    min-height: 40px;
    padding: 0 16px;
    border: 0;
    border-radius: 9px;
    color: #fff;
    background: #526ae2;
    box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
    font-size: 13px;
    font-weight: 600;
}

.primary-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 16px 20px;
    border-top: 1px solid #edf0f5;
}

@media (max-width: 960px) {
    .dict-layout {
        grid-template-columns: 1fr;
        grid-template-rows: none;
        /* 单列堆叠时回退自然流，避免固定高度下的双滚动条 */
        height: auto;
    }
}
</style>
