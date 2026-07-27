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

// ---------- 字典类型（主视图） ----------

const typeLoading = ref(false);
const typeList = ref<DictType[]>([]);
const typeKeyword = ref("");
const typePage = ref(1);
const typeSize = ref(20);
const typeTotal = ref(0);

// 当前钻取的类型：非空时展示该类型下的字典数据视图
const currentType = ref<DictType | null>(null);

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

// 点击类型键钻取进入字典数据视图
function enterDataView(row: DictType) {
    currentType.value = row;
    dataPage.value = 1;
    if (dataKeyword.value) {
        // 关键词非空时清空即可，由防抖 watcher 触发加载，避免重复请求
        dataKeyword.value = "";
    } else {
        loadDataList();
    }
}

// 返回类型列表视图
function backToTypeList() {
    currentType.value = null;
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
    await loadTypes();
}

// ---------- 字典数据（钻取视图，按当前类型联动） ----------

const dataLoading = ref(false);
const dataList = ref<DictData[]>([]);
const dataKeyword = ref("");
const dataPage = ref(1);
const dataSize = ref(20);
const dataTotal = ref(0);

async function loadDataList() {
    if (!currentType.value) {
        dataList.value = [];
        dataTotal.value = 0;
        return;
    }
    dataLoading.value = true;
    try {
        const res = await dictDataApi.list({
            page: dataPage.value,
            size: dataSize.value,
            dict_type: currentType.value.type,
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
    if (!currentType.value) return;
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
                dict_type: currentType.value!.type,
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
    <section class="system-page list-page">
        <!-- 主视图：字典类型列表 -->
        <section v-if="!currentType" class="content-card list-panel" v-loading="typeLoading"
            element-loading-text="加载中…">
            <div class="toolbar">
                <div>
                    <h2>字典管理</h2>
                    <span>共 {{ typeTotal }} 个类型，点击类型键查看字典数据</span>
                </div>
                <div class="toolbar-actions">
                    <SearchInput v-model="typeKeyword" placeholder="搜索名称 / 类型键" />
                    <button class="primary-button" type="button" @click="openTypeCreate">＋ 新建类型</button>
                </div>
            </div>
            <el-table class="list-scroll" :data="typeList">
                <el-table-column prop="name" label="字典名称" min-width="140" show-overflow-tooltip />
                <el-table-column label="类型键" min-width="180">
                    <template #default="{ row }">
                        <a class="type-key-link" title="点击查看字典数据" @click="enterDataView(row)">
                            {{ row.type }}<span class="type-key-arrow">›</span>
                        </a>
                    </template>
                </el-table-column>
                <el-table-column label="状态" width="80">
                    <template #default="{ row }">
                        <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                            {{ row.status === "active" ? "启用" : "停用" }}
                        </el-tag>
                    </template>
                </el-table-column>
                <el-table-column prop="remark" label="备注" min-width="160" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.remark || "—" }}</template>
                </el-table-column>
                <el-table-column prop="updated_at" label="更新时间" width="170" show-overflow-tooltip />
                <el-table-column label="操作" width="120" fixed="right">
                    <template #default="{ row }">
                        <el-button link type="primary" size="small" @click="openTypeEdit(row)">编辑</el-button>
                        <el-button link type="danger" size="small" @click="removeType(row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div class="pagination-bar list-footer">
                <Pagination v-model:page="typePage" v-model:size="typeSize" :total="typeTotal" @change="loadTypes" />
            </div>
        </section>

        <!-- 钻取视图：当前类型下的字典数据 -->
        <section v-else class="content-card list-panel" v-loading="dataLoading" element-loading-text="加载中…">
            <div class="toolbar">
                <div class="toolbar-title">
                    <button class="back-button" type="button" @click="backToTypeList">← 返回</button>
                    <div>
                        <h2>{{ currentType.name }}</h2>
                        <span>类型键：<code class="type-key-chip">{{ currentType.type }}</code> · 共 {{ dataTotal }}
                            条字典数据</span>
                    </div>
                </div>
                <div class="toolbar-actions">
                    <SearchInput v-model="dataKeyword" placeholder="搜索标签" />
                    <button class="primary-button" type="button" @click="openDataCreate">＋ 新建数据</button>
                </div>
            </div>
            <el-table class="list-scroll" :data="dataList">
                <el-table-column prop="label" label="标签" min-width="120" show-overflow-tooltip />
                <el-table-column prop="value" label="键值" min-width="110" show-overflow-tooltip />
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
                <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip>
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
                    <el-input :model-value="editingData?.dict_type ?? currentType?.type ?? ''" disabled />
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
.system-page {
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

.toolbar-title {
    display: flex;
    align-items: center;
    gap: 12px;
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

/* 返回类型列表按钮 */
.back-button {
    min-height: 32px;
    padding: 0 12px;
    border: 1px solid #dfe4ee;
    border-radius: 8px;
    color: #526ae2;
    background: #fff;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
}

.back-button:hover {
    border-color: #526ae2;
    background: #f4f6ff;
}

/* 类型键高亮：点击钻取进入该类型的字典数据 */
.type-key-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 10px;
    border-radius: 7px;
    color: #526ae2;
    background: rgb(82 106 226 / 9%);
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
}

.type-key-link:hover {
    color: #fff;
    background: #526ae2;
}

.type-key-arrow {
    font-size: 14px;
    line-height: 1;
}

/* 钻取视图副标题中的类型键徽标 */
.type-key-chip {
    padding: 1px 6px;
    border-radius: 5px;
    color: #526ae2;
    background: rgb(82 106 226 / 9%);
    font-family: "JetBrains Mono", Consolas, monospace;
    font-size: 12px;
}

.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 16px 20px;
    border-top: 1px solid #edf0f5;
}
</style>
