<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { userApi, type User } from "@/api/system/user";
import { buildDeptTree, type Dept, type DeptTreeNode } from "@/api/system/dept";
import { roleApi, type Role } from "@/api/system/role";
import { confirmDanger } from "@/utils/confirm";
import { useDebouncedKeyword } from "@/composables/useDebouncedKeyword";
import SearchInput from "@/components/SearchInput.vue";
import Pagination from "@/components/Pagination.vue";
import DeptTreePanel from "@/components/DeptTreePanel.vue";
import ListPageCard from "@/components/system/ListPageCard.vue";
import PrimaryButton from "@/components/system/PrimaryButton.vue";
import FormDialog from "@/components/system/FormDialog.vue";
import StatusTag from "@/components/system/StatusTag.vue";
import StatusSelect from "@/components/system/StatusSelect.vue";

const loading = ref(false);
const list = ref<User[]>([]);
// 左侧部门树选中的子树 id 集合（null 表示不过滤）
const deptFilterIds = ref<string[] | null>(null);
const page = ref(1);
const size = ref(20);
const total = ref(0);

// 部门扁平列表由 DeptTreePanel 加载后通过 loaded 事件共享，表单树选择复用
const deptList = ref<Dept[]>([]);
const deptTree = computed<DeptTreeNode[]>(() => buildDeptTree(deptList.value));

async function loadUsers() {
  loading.value = true;
  try {
    const res = await userApi.list({
      page: page.value,
      size: size.value,
      keyword: keyword.value.trim() || undefined,
      dept_ids: deptFilterIds.value ?? undefined,
    });
    list.value = res.data?.items ?? [];
    total.value = res.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

// 关键词防抖：变更后回到第 1 页并触发服务端重载
const keyword = useDebouncedKeyword(() => {
  page.value = 1;
  loadUsers();
});

// 部门树选中/清除：以子树 id 集合过滤并回第 1 页
function onDeptSelect(ids: string[] | null) {
  deptFilterIds.value = ids;
  page.value = 1;
  loadUsers();
}

function onDeptsLoaded(depts: Dept[]) {
  deptList.value = depts;
}

// 新建 / 编辑弹窗
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<User | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
  username: "",
  password: "",
  nickname: "",
  dept_id: null as string | null,
  email: "",
  phone: "",
  status: "active",
  remark: "",
});
const rules = computed<FormRules>(() => ({
  username: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  // 创建时必填密码；编辑走重置密码入口
  password: editing.value ? [] : [{ required: true, message: "请输入初始密码", trigger: "blur" }],
}));

function openCreate() {
  editing.value = null;
  Object.assign(form, {
    username: "",
    password: "",
    nickname: "",
    dept_id: null,
    email: "",
    phone: "",
    status: "active",
    remark: "",
  });
  dialogVisible.value = true;
  formRef.value?.clearValidate();
}

function openEdit(row: User) {
  editing.value = row;
  Object.assign(form, {
    username: row.username,
    password: "",
    nickname: row.nickname ?? "",
    dept_id: row.dept_id,
    email: row.email ?? "",
    phone: row.phone ?? "",
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
      await userApi.update(editing.value.id, {
        username: form.username,
        nickname: form.nickname || null,
        dept_id: form.dept_id,
        email: form.email || null,
        phone: form.phone || null,
        status: form.status,
        remark: form.remark || null,
      });
      ElMessage.success("用户已更新");
    } else {
      await userApi.create({
        username: form.username,
        password: form.password,
        nickname: form.nickname || null,
        dept_id: form.dept_id,
        email: form.email || null,
        phone: form.phone || null,
        status: form.status,
        remark: form.remark || null,
      });
      ElMessage.success("用户已创建");
    }
    dialogVisible.value = false;
    await loadUsers();
  } finally {
    submitting.value = false;
  }
}

async function removeUser(row: User) {
  const confirmed = await confirmDanger(
    `确定删除用户「${row.username}」吗？其角色关联将一并清理。`
  );
  if (!confirmed) return;
  await userApi.remove(row.id);
  ElMessage.success("用户已删除");
  await loadUsers();
}

// 重置密码弹窗
const pwdDialogVisible = ref(false);
const pwdSubmitting = ref(false);
const pwdTarget = ref<User | null>(null);
const pwdFormRef = ref<FormInstance>();
const pwdForm = reactive({ password: "" });
const pwdRules: FormRules = {
  password: [
    { required: true, message: "请输入新密码", trigger: "blur" },
    { min: 6, message: "密码至少 6 位", trigger: "blur" },
  ],
};

function openResetPassword(row: User) {
  pwdTarget.value = row;
  pwdForm.password = "";
  pwdDialogVisible.value = true;
  pwdFormRef.value?.clearValidate();
}

async function submitResetPassword() {
  const valid = await pwdFormRef.value?.validate().catch(() => false);
  if (!valid || !pwdTarget.value) return;
  pwdSubmitting.value = true;
  try {
    await userApi.resetPassword(pwdTarget.value.id, pwdForm.password);
    ElMessage.success("密码已重置");
    pwdDialogVisible.value = false;
  } finally {
    pwdSubmitting.value = false;
  }
}

// 分配角色弹窗（全量覆盖语义：保存时以勾选结果整体覆盖）
const roleDialogVisible = ref(false);
const roleSubmitting = ref(false);
const roleLoading = ref(false);
const roleTarget = ref<User | null>(null);
const roleOptions = ref<Role[]>([]);
const checkedRoleIds = ref<string[]>([]);

async function openAssignRoles(row: User) {
  roleTarget.value = row;
  roleDialogVisible.value = true;
  roleLoading.value = true;
  try {
    const [rolesRes, idsRes] = await Promise.all([
      roleApi.list({ page: 1, size: 200 }),
      userApi.listRoleIds(row.id),
    ]);
    roleOptions.value = rolesRes.data?.items ?? [];
    checkedRoleIds.value = idsRes.data ?? [];
  } finally {
    roleLoading.value = false;
  }
}

async function submitAssignRoles() {
  if (!roleTarget.value) return;
  roleSubmitting.value = true;
  try {
    await userApi.assignRoles(roleTarget.value.id, checkedRoleIds.value);
    ElMessage.success("角色已分配");
    roleDialogVisible.value = false;
    // 角色列为服务端聚合数据，保存后重载列表保证 tag 回显实时准确
    await loadUsers();
  } finally {
    roleSubmitting.value = false;
  }
}

onMounted(() => {
  loadUsers();
});
</script>

<template>
  <section class="system-page list-page">
    <div class="user-layout">
      <!-- 左栏：通用部门树，选中子树驱动右侧列表过滤 -->
      <DeptTreePanel @select="onDeptSelect" @loaded="onDeptsLoaded" />
      <ListPageCard
        class="user-list-card"
        title="用户管理"
        :subtitle="`共 ${total} 个用户`"
        :loading="loading"
      >
        <template #actions>
          <SearchInput v-model="keyword" placeholder="搜索用户名 / 昵称" />
          <PrimaryButton @click="openCreate">＋ 新建用户</PrimaryButton>
        </template>
        <el-table class="list-scroll" :data="list">
          <el-table-column prop="username" label="用户名" min-width="120" show-overflow-tooltip />
          <el-table-column prop="nickname" label="昵称" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.nickname || "—" }}</template>
          </el-table-column>
          <el-table-column label="部门" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">{{ row.dept_name || "—" }}</template>
          </el-table-column>
          <el-table-column label="角色" min-width="150">
            <template #default="{ row }">
              <template v-if="row.roles?.length">
                <el-tag v-for="role in row.roles" :key="role.id" class="role-tag" size="small">
                  {{ role.name }}
                </el-tag>
              </template>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.email || "—" }}</template>
          </el-table-column>
          <el-table-column prop="phone" label="手机号" width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.phone || "—" }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <StatusTag :status="row.status" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="primary" size="small" @click="openAssignRoles(row)">
                分配角色
              </el-button>
              <el-button link type="warning" size="small" @click="openResetPassword(row)">
                重置密码
              </el-button>
              <el-button link type="danger" size="small" @click="removeUser(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <template #footer>
          <Pagination v-model:page="page" v-model:size="size" :total="total" @change="loadUsers" />
        </template>
      </ListPageCard>
    </div>

    <!-- 新建/编辑 弹窗 -->
    <FormDialog
      v-model="dialogVisible"
      :title="editing ? '编辑用户' : '新建用户'"
      width="560px"
      :submitting="submitting"
      @submit="submit"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="登录用户名（全局唯一）" maxlength="50" />
        </el-form-item>
        <el-form-item v-if="!editing" label="初始密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="服务端加密存储"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="form.nickname" placeholder="选填" maxlength="50" />
        </el-form-item>
        <el-form-item label="所属部门">
          <el-tree-select
            v-model="form.dept_id"
            :data="deptTree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            check-strictly
            clearable
            placeholder="不选表示未分配"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="选填" maxlength="100" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="选填" maxlength="20" />
        </el-form-item>
        <el-form-item label="状态">
          <StatusSelect v-model="form.status" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="选填" />
        </el-form-item>
      </el-form>
    </FormDialog>

    <!-- 重置密码 弹窗 -->
    <FormDialog
      v-model="pwdDialogVisible"
      :title="`重置密码：${pwdTarget?.username ?? ''}`"
      width="440px"
      :submitting="pwdSubmitting"
      confirm-text="确定"
      @submit="submitResetPassword"
    >
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="80px">
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="pwdForm.password"
            type="password"
            show-password
            placeholder="至少 6 位"
            maxlength="100"
          />
        </el-form-item>
      </el-form>
    </FormDialog>

    <!-- 分配角色 弹窗 -->
    <FormDialog
      v-model="roleDialogVisible"
      :title="`分配角色：${roleTarget?.username ?? ''}`"
      width="440px"
      :submitting="roleSubmitting"
      @submit="submitAssignRoles"
    >
      <div v-loading="roleLoading">
        <el-checkbox-group v-model="checkedRoleIds" class="role-checks">
          <el-checkbox v-for="role in roleOptions" :key="role.id" :value="role.id">
            {{ role.name }}（{{ role.role_key }}）
          </el-checkbox>
        </el-checkbox-group>
        <p v-if="!roleLoading && !roleOptions.length" class="empty-tip">
          暂无可分配角色，请先创建角色
        </p>
      </div>
    </FormDialog>
  </section>
</template>

<style scoped>
.system-page {
  color: #273249;
}

/* 左右双栏：左部门树固定宽、右列表卡片吃满剩余；两栏各自 list-panel 内滚 */
.user-layout {
  display: flex;
  flex: 1;
  gap: 20px;
  min-height: 0;
}

/* 仅右侧列表卡片吃满剩余宽度，避免命中同样带 content-card 类的部门树面板 */
.user-layout > .user-list-card {
  flex: 1;
  min-width: 0;
}

.role-tag {
  margin: 2px 6px 2px 0;
}

.role-checks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-tip {
  margin: 8px 0 0;
  color: #7d879a;
  font-size: 13px;
}

/* 窄屏回退：双栏改纵向堆叠，随页面自然流滚动 */
@media (max-width: 720px) {
  .user-layout {
    flex-direction: column;
  }
}
</style>
