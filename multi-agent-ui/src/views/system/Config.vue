<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { configApi, type Config } from "@/api/system/config";
import { confirmDanger } from "@/utils/confirm";
import { useDebouncedKeyword } from "@/composables/useDebouncedKeyword";
import SearchInput from "@/components/SearchInput.vue";
import Pagination from "@/components/Pagination.vue";
import ListPageCard from "@/components/system/ListPageCard.vue";
import PrimaryButton from "@/components/system/PrimaryButton.vue";
import FormDialog from "@/components/system/FormDialog.vue";

const loading = ref(false);
const list = ref<Config[]>([]);
const page = ref(1);
const size = ref(20);
const total = ref(0);

async function loadConfigs() {
  loading.value = true;
  try {
    const res = await configApi.list({
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
const keyword = useDebouncedKeyword(() => {
  page.value = 1;
  loadConfigs();
});

// 新建 / 编辑弹窗
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<Config | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
  name: "",
  key: "",
  value: "",
  is_builtin: false,
  remark: "",
});
const rules: FormRules = {
  name: [{ required: true, message: "请输入参数名称", trigger: "blur" }],
  key: [{ required: true, message: "请输入参数键", trigger: "blur" }],
};

function openCreate() {
  editing.value = null;
  Object.assign(form, { name: "", key: "", value: "", is_builtin: false, remark: "" });
  dialogVisible.value = true;
  formRef.value?.clearValidate();
}

function openEdit(row: Config) {
  editing.value = row;
  Object.assign(form, {
    name: row.name,
    key: row.key,
    value: row.value ?? "",
    is_builtin: row.is_builtin,
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
      // is_builtin 创建后不可变，更新时不提交
      await configApi.update(editing.value.id, {
        name: form.name,
        key: form.key,
        value: form.value || null,
        remark: form.remark || null,
      });
      ElMessage.success("参数已更新");
    } else {
      await configApi.create({
        name: form.name,
        key: form.key,
        value: form.value || null,
        is_builtin: form.is_builtin,
        remark: form.remark || null,
      });
      ElMessage.success("参数已创建");
    }
    dialogVisible.value = false;
    await loadConfigs();
  } finally {
    submitting.value = false;
  }
}

async function removeConfig(row: Config) {
  const confirmed = await confirmDanger(`确定删除参数「${row.name}」吗？`);
  if (!confirmed) return;
  await configApi.remove(row.id);
  ElMessage.success("参数已删除");
  await loadConfigs();
}

onMounted(loadConfigs);
</script>

<template>
  <section class="system-page list-page">
    <ListPageCard title="参数管理" :subtitle="`共 ${total} 个参数`" :loading="loading">
      <template #actions>
        <SearchInput v-model="keyword" placeholder="搜索名称 / 参数键" />
        <PrimaryButton @click="openCreate">＋ 新建参数</PrimaryButton>
      </template>
      <el-table class="list-scroll" :data="list">
        <el-table-column prop="name" label="参数名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="key" label="参数键" min-width="200" show-overflow-tooltip />
        <el-table-column prop="value" label="参数值" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.value ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="内置" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_builtin" type="warning" size="small">内置</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || "—" }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="170" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <!-- 内置参数受后端删除保护，前端同步呈现禁用态 -->
            <el-tooltip v-if="row.is_builtin" content="内置参数不可删除" placement="top">
              <span>
                <el-button link type="danger" size="small" disabled>删除</el-button>
              </span>
            </el-tooltip>
            <el-button v-else link type="danger" size="small" @click="removeConfig(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <Pagination v-model:page="page" v-model:size="size" :total="total" @change="loadConfigs" />
      </template>
    </ListPageCard>

    <!-- 新建/编辑 弹窗 -->
    <FormDialog
      v-model="dialogVisible"
      :title="editing ? '编辑参数' : '新建参数'"
      :submitting="submitting"
      @submit="submit"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="参数名称" prop="name">
          <el-input v-model="form.name" placeholder="如：用户初始密码" maxlength="100" />
        </el-form-item>
        <el-form-item label="参数键" prop="key">
          <el-input
            v-model="form.key"
            placeholder="如：sys.user.init_password（全局唯一）"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item label="参数值">
          <el-input v-model="form.value" placeholder="选填" maxlength="500" />
        </el-form-item>
        <el-form-item label="内置参数">
          <!-- is_builtin 创建后不可变，编辑态禁用 -->
          <el-switch v-model="form.is_builtin" :disabled="Boolean(editing)" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="选填" />
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
