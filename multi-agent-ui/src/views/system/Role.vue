<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElTree, type FormInstance, type FormRules } from "element-plus";
import { roleApi, type Role } from "@/api/system/role";
import { menuApi, buildMenuTree, type MenuTreeNode } from "@/api/system/menu";
import { confirmDanger } from "@/utils/confirm";
import SearchInput from "@/components/SearchInput.vue";
import Pagination from "@/components/Pagination.vue";

const loading = ref(false);
const list = ref<Role[]>([]);
const keyword = ref("");
const page = ref(1);
const size = ref(20);
const total = ref(0);

async function loadRoles() {
    loading.value = true;
    try {
        const res = await roleApi.list({
            page: page.value,
            size: size.value,
            keyword: keyword.value.trim() || undefined,
        });
        list.value = res.data?.items ?? [];
        total.value = res.data?.total ?? 0;
    } finally {
        loading.value = false;
    }
}

// 关键词防抖：变更后回到第 1 页并触发服务端重载
let keywordTimer: ReturnType<typeof setTimeout> | undefined;
watch(keyword, () => {
    if (keywordTimer) clearTimeout(keywordTimer);
    keywordTimer = setTimeout(() => {
        page.value = 1;
        loadRoles();
    }, 300);
});

// 新建 / 编辑弹窗
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<Role | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
    name: "",
    role_key: "",
    sort_order: 0,
    status: "active",
    remark: "",
});
const rules: FormRules = {
    name: [{ required: true, message: "请输入角色名称", trigger: "blur" }],
    role_key: [{ required: true, message: "请输入角色标识", trigger: "blur" }],
};

function openCreate() {
    editing.value = null;
    Object.assign(form, { name: "", role_key: "", sort_order: 0, status: "active", remark: "" });
    dialogVisible.value = true;
    formRef.value?.clearValidate();
}

function openEdit(row: Role) {
    editing.value = row;
    Object.assign(form, {
        name: row.name,
        role_key: row.role_key,
        sort_order: row.sort_order,
        status: row.status,
        remark: row.remark ?? "",
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
            await roleApi.update(editing.value.id, {
                name: form.name,
                role_key: form.role_key,
                sort_order: form.sort_order,
                status: form.status,
                remark: form.remark || null,
            });
            ElMessage.success("角色已更新");
        } else {
            await roleApi.create({
                name: form.name,
                role_key: form.role_key,
                sort_order: form.sort_order,
                status: form.status,
                remark: form.remark || null,
            });
            ElMessage.success("角色已创建");
        }
        dialogVisible.value = false;
        await loadRoles();
    } finally {
        submitting.value = false;
    }
}

async function removeRole(row: Role) {
    const confirmed = await confirmDanger(
        `确定删除角色「${row.name}」吗？角色已分配给用户时将被拒绝。`
    );
    if (!confirmed) return;
    await roleApi.remove(row.id);
    ElMessage.success("角色已删除");
    await loadRoles();
}

// 分配菜单弹窗（全量覆盖语义：保存时以勾选结果整体覆盖）
const menuDialogVisible = ref(false);
const menuSubmitting = ref(false);
const menuLoading = ref(false);
const menuTarget = ref<Role | null>(null);
const menuTree = ref<MenuTreeNode[]>([]);
const menuTreeRef = ref<InstanceType<typeof ElTree>>();

async function openAssignMenus(row: Role) {
    menuTarget.value = row;
    menuDialogVisible.value = true;
    menuLoading.value = true;
    try {
        const [menusRes, idsRes] = await Promise.all([
            menuApi.list(),
            roleApi.listMenuIds(row.id),
        ]);
        menuTree.value = buildMenuTree(menusRes.data ?? []);
        // 待树渲染后仅回显叶子勾选，父节点由 el-tree 推导半选态
        const bound = new Set(idsRes.data ?? []);
        const leafIds: string[] = [];
        const walk = (nodes: MenuTreeNode[]) => {
            nodes.forEach((n) => {
                if (n.children.length) walk(n.children);
                else if (bound.has(n.id)) leafIds.push(n.id);
            });
        };
        walk(menuTree.value);
        await nextTick();
        menuTreeRef.value?.setCheckedKeys(leafIds);
    } finally {
        menuLoading.value = false;
    }
}

async function submitAssignMenus() {
    if (!menuTarget.value || !menuTreeRef.value) return;
    menuSubmitting.value = true;
    try {
        // 全选节点 + 半选父节点一并提交，保证目录层级完整
        const checked = menuTreeRef.value.getCheckedKeys() as string[];
        const halfChecked = menuTreeRef.value.getHalfCheckedKeys() as string[];
        await roleApi.assignMenus(menuTarget.value.id, [...checked, ...halfChecked]);
        ElMessage.success("菜单已分配");
        menuDialogVisible.value = false;
    } finally {
        menuSubmitting.value = false;
    }
}

onMounted(loadRoles);
</script>

<template>
    <section class="system-page list-page">
        <section class="content-card list-panel" v-loading="loading" element-loading-text="加载中…">
            <div class="toolbar">
                <div>
                    <h2>角色管理</h2>
                    <span>共 {{ total }} 个角色</span>
                </div>
                <div class="toolbar-actions">
                    <SearchInput v-model="keyword" placeholder="搜索名称 / 角色标识" />
                    <button class="primary-button" type="button" @click="openCreate">＋ 新建角色</button>
                </div>
            </div>
            <el-table class="list-scroll" :data="list">
                <el-table-column prop="name" label="角色名称" min-width="130" show-overflow-tooltip />
                <el-table-column prop="role_key" label="角色标识" min-width="130" show-overflow-tooltip />
                <el-table-column prop="sort_order" label="排序" width="70" />
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
                <el-table-column prop="updated_at" label="更新时间" width="170" show-overflow-tooltip />
                <el-table-column label="操作" width="190" fixed="right">
                    <template #default="{ row }">
                        <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
                        <el-button link type="primary" size="small" @click="openAssignMenus(row)">分配菜单</el-button>
                        <el-button link type="danger" size="small" @click="removeRole(row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
            <div class="pagination-bar list-footer">
                <Pagination v-model:page="page" v-model:size="size" :total="total" @change="loadRoles" />
            </div>
        </section>

        <!-- 新建/编辑 弹窗 -->
        <el-dialog v-model="dialogVisible" :title="editing ? '编辑角色' : '新建角色'" width="520px">
            <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
                <el-form-item label="角色名称" prop="name">
                    <el-input v-model="form.name" placeholder="如：管理员" maxlength="100" />
                </el-form-item>
                <el-form-item label="角色标识" prop="role_key">
                    <el-input v-model="form.role_key" placeholder="如：admin（全局唯一）" maxlength="100" />
                </el-form-item>
                <el-form-item label="排序">
                    <el-input-number v-model="form.sort_order" :min="0" />
                </el-form-item>
                <el-form-item label="状态">
                    <el-select v-model="form.status" style="width: 100%">
                        <el-option label="启用" value="active" />
                        <el-option label="停用" value="disabled" />
                    </el-select>
                </el-form-item>
                <el-form-item label="备注">
                    <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="选填" />
                </el-form-item>
            </el-form>
            <template #footer>
                <el-button @click="dialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
            </template>
        </el-dialog>

        <!-- 分配菜单 弹窗 -->
        <el-dialog v-model="menuDialogVisible" :title="`分配菜单：${menuTarget?.name ?? ''}`" width="480px">
            <div v-loading="menuLoading" class="menu-tree-wrap">
                <el-tree ref="menuTreeRef" :data="menuTree" node-key="id" show-checkbox default-expand-all
                    :props="{ label: 'label', children: 'children' }" />
                <p v-if="!menuLoading && !menuTree.length" class="empty-tip">暂无菜单数据</p>
            </div>
            <template #footer>
                <el-button @click="menuDialogVisible = false">取消</el-button>
                <el-button type="primary" :loading="menuSubmitting" @click="submitAssignMenus">保存</el-button>
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

.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 16px 20px;
    border-top: 1px solid #edf0f5;
}

.menu-tree-wrap {
    max-height: 420px;
    overflow: auto;
}

.empty-tip {
    margin: 8px 0 0;
    color: #7d879a;
    font-size: 13px;
}
</style>
