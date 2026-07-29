<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import {
  menuApi,
  buildMenuTree,
  collectMenuSubtreeIds,
  type Menu,
  type MenuTreeNode,
} from "@/api/system/menu";
import { confirmDanger } from "@/utils/confirm";
import { useDebouncedKeyword } from "@/composables/useDebouncedKeyword";
import SearchInput from "@/components/SearchInput.vue";
import IconSelect from "@/components/IconSelect.vue";
import ListPageCard from "@/components/system/ListPageCard.vue";
import PrimaryButton from "@/components/system/PrimaryButton.vue";
import FormDialog from "@/components/system/FormDialog.vue";
import StatusTag from "@/components/system/StatusTag.vue";
import StatusSelect from "@/components/system/StatusSelect.vue";

// menu_type 展示配置：dir 目录 / menu 菜单 / button 按钮
const MENU_TYPE_META: Record<string, { label: string; tag: "primary" | "success" | "info" }> = {
  dir: { label: "目录", tag: "primary" },
  menu: { label: "菜单", tag: "success" },
  button: { label: "按钮", tag: "info" },
};

const loading = ref(false);
// 后端返回扁平列表，树由前端组装
const flatList = ref<Menu[]>([]);

const treeData = computed<MenuTreeNode[]>(() => buildMenuTree(flatList.value));

async function loadMenus() {
  loading.value = true;
  try {
    const res = await menuApi.list({
      keyword: keyword.value.trim() || undefined,
    });
    flatList.value = res.data ?? [];
  } finally {
    loading.value = false;
  }
}

// 关键词防抖：服务端模糊过滤后重新组树
const keyword = useDebouncedKeyword(loadMenus);

// 新建 / 编辑弹窗
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<Menu | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
  menu_type: "menu",
  label: "",
  parent_id: null as string | null,
  name: "",
  path: "",
  component: "",
  icon: "",
  perms: "",
  visible: true,
  sort_order: 0,
  status: "active",
});
const rules: FormRules = {
  label: [{ required: true, message: "请输入显示名称", trigger: "blur" }],
};

// 三种 menu_type 的表单字段联动：dir 有 path；menu 有 name/path/component；button 有 perms
const isDir = computed(() => form.menu_type === "dir");
const isMenu = computed(() => form.menu_type === "menu");
const isButton = computed(() => form.menu_type === "button");

// 父菜单下拉候选：按钮不能作为父节点；编辑时排除自身及后代，防止成环
const parentOptions = computed<MenuTreeNode[]>(() => {
  const excluded = editing.value
    ? collectMenuSubtreeIds(flatList.value, editing.value.id)
    : new Set<string>();
  const filter = (nodes: MenuTreeNode[]): MenuTreeNode[] =>
    nodes
      .filter((n) => n.menu_type !== "button" && !excluded.has(n.id))
      .map((n) => ({ ...n, children: filter(n.children) }));
  return filter(treeData.value);
});

function openCreate(parent?: Menu) {
  editing.value = null;
  Object.assign(form, {
    menu_type: parent?.menu_type === "menu" ? "button" : "menu",
    label: "",
    parent_id: parent?.id ?? null,
    name: "",
    path: "",
    component: "",
    icon: "",
    perms: "",
    visible: true,
    sort_order: 0,
    status: "active",
  });
  dialogVisible.value = true;
  formRef.value?.clearValidate();
}

function openEdit(row: Menu) {
  editing.value = row;
  Object.assign(form, {
    menu_type: row.menu_type,
    label: row.label,
    parent_id: row.parent_id,
    name: row.name ?? "",
    path: row.path ?? "",
    component: row.component ?? "",
    icon: row.icon ?? "",
    perms: row.perms ?? "",
    visible: row.visible,
    sort_order: row.sort_order,
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
    // 与类型无关的字段仅在对应类型下提交，其余置空
    const payload = {
      label: form.label,
      parent_id: form.parent_id,
      name: isMenu.value ? form.name || null : null,
      path: isDir.value || isMenu.value ? form.path || null : null,
      component: isMenu.value ? form.component || null : null,
      icon: isButton.value ? null : form.icon || null,
      perms: isButton.value ? form.perms || null : null,
      visible: form.visible,
      sort_order: form.sort_order,
      status: form.status,
    };
    if (editing.value) {
      // menu_type 创建后不可变，更新时不提交
      await menuApi.update(editing.value.id, payload);
      ElMessage.success("菜单已更新");
    } else {
      await menuApi.create({ menu_type: form.menu_type, ...payload });
      ElMessage.success("菜单已创建");
    }
    dialogVisible.value = false;
    await loadMenus();
  } finally {
    submitting.value = false;
  }
}

async function removeMenu(row: Menu) {
  const confirmed = await confirmDanger(
    `确定删除菜单「${row.label}」吗？存在子菜单或仍被角色绑定时将被拒绝。`
  );
  if (!confirmed) return;
  await menuApi.remove(row.id);
  ElMessage.success("菜单已删除");
  await loadMenus();
}

onMounted(loadMenus);
</script>

<template>
  <section class="system-page list-page">
    <ListPageCard title="菜单管理" :subtitle="`共 ${flatList.length} 个节点`" :loading="loading">
      <template #actions>
        <SearchInput v-model="keyword" placeholder="搜索菜单名称" />
        <PrimaryButton @click="openCreate()">＋ 新建菜单</PrimaryButton>
      </template>
      <!-- 默认收起，仅展示顶级节点，子级按需展开 -->
      <el-table
        class="list-scroll"
        :data="treeData"
        row-key="id"
        :tree-props="{ children: 'children' }"
      >
        <el-table-column prop="label" label="显示名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="MENU_TYPE_META[row.menu_type]?.tag ?? 'info'" size="small">
              {{ MENU_TYPE_META[row.menu_type]?.label ?? row.menu_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="path" label="路由路径" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.path || "—" }}</template>
        </el-table-column>
        <el-table-column prop="component" label="组件" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.component || "—" }}</template>
        </el-table-column>
        <el-table-column prop="perms" label="权限标识" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.perms || "—" }}</template>
        </el-table-column>
        <el-table-column prop="sort_order" label="排序" width="70" />
        <el-table-column label="可见" width="70">
          <template #default="{ row }">{{ row.visible ? "显示" : "隐藏" }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <StatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.menu_type !== 'button'"
              link
              type="primary"
              size="small"
              @click="openCreate(row)"
            >
              新增下级
            </el-button>
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="removeMenu(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </ListPageCard>

    <!-- 新建/编辑 弹窗：字段随 menu_type 三态联动 -->
    <FormDialog
      v-model="dialogVisible"
      :title="editing ? '编辑菜单' : '新建菜单'"
      width="560px"
      :submitting="submitting"
      @submit="submit"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="菜单类型">
          <!-- menu_type 创建后不可变，编辑态禁用 -->
          <el-radio-group v-model="form.menu_type" :disabled="Boolean(editing)">
            <el-radio-button value="dir">目录</el-radio-button>
            <el-radio-button value="menu">菜单</el-radio-button>
            <el-radio-button value="button">按钮</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="上级菜单">
          <el-tree-select
            v-model="form.parent_id"
            :data="parentOptions"
            :props="{ label: 'label', children: 'children' }"
            node-key="id"
            check-strictly
            placeholder="不选表示顶级节点"
            clearable
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="显示名称" prop="label">
          <el-input v-model="form.label" placeholder="如：用户管理" maxlength="100" />
        </el-form-item>
        <el-form-item v-if="isMenu" label="路由名称">
          <el-input
            v-model="form.name"
            placeholder="如：SystemUser（前端路由 name）"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item v-if="isDir || isMenu" label="路由路径">
          <el-input v-model="form.path" placeholder="如：/system/users" maxlength="200" />
        </el-form-item>
        <el-form-item v-if="isMenu" label="组件标识">
          <el-input v-model="form.component" placeholder="如：system/User" maxlength="200" />
        </el-form-item>
        <el-form-item v-if="!isButton" label="图标">
          <!-- 图标选择器：本地 assets/icon 图标 + Element Plus 全量图标 -->
          <IconSelect v-model="form.icon" />
        </el-form-item>
        <el-form-item v-if="isButton" label="权限标识">
          <el-input v-model="form.perms" placeholder="如：system:user:add" maxlength="100" />
        </el-form-item>
        <el-form-item v-if="!isButton" label="是否可见">
          <el-switch v-model="form.visible" />
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
