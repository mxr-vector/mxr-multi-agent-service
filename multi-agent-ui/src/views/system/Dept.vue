<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import {
    deptApi,
    buildDeptTree,
    collectDeptSubtreeIds,
    type Dept,
    type DeptTreeNode,
} from "@/api/system/dept";
import { confirmDanger } from "@/utils/confirm";
import { useDebouncedKeyword } from "@/composables/useDebouncedKeyword";
import SearchInput from "@/components/SearchInput.vue";
import ListPageCard from "@/components/system/ListPageCard.vue";
import PrimaryButton from "@/components/system/PrimaryButton.vue";
import FormDialog from "@/components/system/FormDialog.vue";
import StatusTag from "@/components/system/StatusTag.vue";
import StatusSelect from "@/components/system/StatusSelect.vue";

const loading = ref(false);
// 后端返回扁平列表，树由前端组装
const flatList = ref<Dept[]>([]);

const treeData = computed<DeptTreeNode[]>(() => buildDeptTree(flatList.value));

async function loadDepts() {
    loading.value = true;
    try {
        const res = await deptApi.list({
            keyword: keyword.value.trim() || undefined,
        });
        flatList.value = res.data ?? [];
    } finally {
        loading.value = false;
    }
}

// 关键词防抖：服务端模糊过滤后重新组树
const keyword = useDebouncedKeyword(loadDepts);

// 新建 / 编辑弹窗
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<Dept | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
    name: "",
    parent_id: null as string | null,
    sort_order: 0,
    leader: "",
    status: "active",
});
const rules: FormRules = {
    name: [{ required: true, message: "请输入部门名称", trigger: "blur" }],
};

// 父部门下拉候选：编辑时排除自身及后代，防止成环
const parentOptions = computed<DeptTreeNode[]>(() => {
    if (!editing.value) return treeData.value;
    const excluded = collectDeptSubtreeIds(flatList.value, editing.value.id);
    const filter = (nodes: DeptTreeNode[]): DeptTreeNode[] =>
        nodes
            .filter((n) => !excluded.has(n.id))
            .map((n) => ({ ...n, children: filter(n.children) }));
    return filter(treeData.value);
});

function openCreate(parent?: Dept) {
    editing.value = null;
    Object.assign(form, {
        name: "",
        parent_id: parent?.id ?? null,
        sort_order: 0,
        leader: "",
        status: "active",
    });
    dialogVisible.value = true;
    formRef.value?.clearValidate();
}

function openEdit(row: Dept) {
    editing.value = row;
    Object.assign(form, {
        name: row.name,
        parent_id: row.parent_id,
        sort_order: row.sort_order,
        leader: row.leader ?? "",
        status: row.status,
    });
    dialogVisible.value = true;
    formRef.value?.clearValidate();
}

async function submit() {
    const valid = await formRef.value?.validate().catch(() => false);
    if (!valid) return;
    submitting.value = true;
    try {
        if (editing.value) {
            await deptApi.update(editing.value.id, {
                name: form.name,
                parent_id: form.parent_id,
                sort_order: form.sort_order,
                leader: form.leader || null,
                status: form.status,
            });
            ElMessage.success("部门已更新");
        } else {
            await deptApi.create({
                name: form.name,
                parent_id: form.parent_id,
                sort_order: form.sort_order,
                leader: form.leader || null,
                status: form.status,
            });
            ElMessage.success("部门已创建");
        }
        dialogVisible.value = false;
        await loadDepts();
    } finally {
        submitting.value = false;
    }
}

async function removeDept(row: Dept) {
    const confirmed = await confirmDanger(
        `确定删除部门「${row.name}」吗？存在子部门或关联用户时将被拒绝。`
    );
    if (!confirmed) return;
    await deptApi.remove(row.id);
    ElMessage.success("部门已删除");
    await loadDepts();
}

onMounted(loadDepts);
</script>

<template>
    <section class="system-page list-page">
        <ListPageCard title="部门管理" :subtitle="`共 ${flatList.length} 个部门`" :loading="loading">
            <template #actions>
                <SearchInput v-model="keyword" placeholder="搜索部门名称" />
                <PrimaryButton @click="openCreate()">＋ 新建部门</PrimaryButton>
            </template>
            <el-table class="list-scroll" :data="treeData" row-key="id" default-expand-all
                :tree-props="{ children: 'children' }">
                <el-table-column prop="name" label="部门名称" min-width="220" show-overflow-tooltip />
                <el-table-column prop="leader" label="负责人" min-width="110" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.leader || "—" }}</template>
                </el-table-column>
                <el-table-column prop="sort_order" label="排序" width="70" />
                <el-table-column label="状态" width="80">
                    <template #default="{ row }">
                        <StatusTag :status="row.status" />
                    </template>
                </el-table-column>
                <el-table-column prop="updated_at" label="更新时间" width="170" show-overflow-tooltip />
                <el-table-column label="操作" width="170" fixed="right">
                    <template #default="{ row }">
                        <el-button link type="primary" size="small" @click="openCreate(row)">新增下级</el-button>
                        <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
                        <el-button link type="danger" size="small" @click="removeDept(row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
        </ListPageCard>

        <!-- 新建/编辑 弹窗 -->
        <FormDialog v-model="dialogVisible" :title="editing ? '编辑部门' : '新建部门'" :submitting="submitting"
            @submit="submit">
            <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
                <el-form-item label="上级部门">
                    <el-tree-select v-model="form.parent_id" :data="parentOptions"
                        :props="{ label: 'name', children: 'children' }" node-key="id" check-strictly
                        placeholder="不选表示顶级部门" clearable style="width: 100%" />
                </el-form-item>
                <el-form-item label="部门名称" prop="name">
                    <el-input v-model="form.name" placeholder="如：研发部" maxlength="100" />
                </el-form-item>
                <el-form-item label="负责人">
                    <el-input v-model="form.leader" placeholder="选填" maxlength="50" />
                </el-form-item>
                <el-form-item label="排序">
                    <el-input-number v-model="form.sort_order" :min="0" />
                </el-form-item>
                <el-form-item label="状态">
                    <StatusSelect v-model="form.status" />
                </el-form-item>
            </el-form>
        </FormDialog>
    </section>
</template>

<style scoped>
.system-page {
    color: #273249;
}
</style>
