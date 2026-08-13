<script setup lang="ts">
// RAG / AI 问答运行参数区域：展示全部内置参数（is_builtin=true，含 RAG_* / CHAT_* / DRAWIO_EMBED_URL
// 及后续新增的内置参数），点值即改，保存后后端触发配置快照刷新（免重启生效），
// refreshed 透出是否热更新成功；展示与刷新均经全局 configStore（其他消费方同源）。
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { configApi, type Config } from "@/api/system/config";
import { useConfigStore } from "@/stores/configStore";

const configStore = useConfigStore();
const loading = ref(false);
const list = computed(() => configStore.list());

async function loadScalars() {
  loading.value = true;
  try {
    await configStore.loadAll();
  } finally {
    loading.value = false;
  }
}

// 编辑弹窗（仅可改 value / remark：key 为内置参数契约键，不可变；无新建/删除入口）
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<Config | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
  value: "",
  remark: "",
});
// 校验按后端返回的 value_type 数据驱动：url 为 http(s) 地址，int 为正整数，
// text（无格式约束的内置参数）仅校必填——后端快照校验是契约键的最终闸门
const rules: FormRules = {
  value: [
    { required: true, message: "请输入参数值", trigger: "blur" },
    {
      validator: (_rule, val, cb) => {
        const type = editing.value?.value_type;
        if (type === "url") {
          try {
            const u = new URL(String(val));
            if (u.protocol !== "http:" && u.protocol !== "https:") {
              cb(new Error("必须为 http/https 地址"));
            } else cb();
          } catch {
            cb(new Error("请输入合法的 URL"));
          }
          return;
        }
        if (type === "int") {
          const n = Number(val);
          if (!Number.isInteger(n) || n <= 0) cb(new Error("必须为正整数"));
          else cb();
          return;
        }
        // text 型：不预设格式，仅靠 required 校必填
        cb();
      },
      trigger: "blur",
    },
  ],
};

function openEdit(row: Config) {
  editing.value = row;
  Object.assign(form, { value: row.value ?? "", remark: row.remark ?? "" });
  dialogVisible.value = true;
  formRef.value?.clearValidate();
}

// 参数值输入框占位提示（按 value_type：URL / 正整数 / 普通文本）
const valuePlaceholder = computed(() => {
  const type = editing.value?.value_type;
  if (type === "url") return "http(s):// 地址";
  if (type === "int") return "正整数";
  return "参数值";
});

async function submit() {
  if (!editing.value) return;
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    // key/name 为白名单契约值，运行参数仅允许改 value / remark
    const res = await configApi.update(editing.value.id, {
      value: form.value.trim(),
      remark: form.remark || null,
    });
    if (res.data?.refreshed === false) {
      ElMessage.warning("已保存，但配置热更新校验未通过，仍沿用旧配置");
    } else {
      ElMessage.success("已保存，配置已热更新");
    }
    dialogVisible.value = false;
    await loadScalars();
  } finally {
    submitting.value = false;
  }
}

defineExpose({ reload: loadScalars });
onMounted(loadScalars);
</script>

<template>
  <section class="scalar-params" v-loading="loading">
    <header class="scalar-params__head">
      <h3 class="scalar-params__title">运行参数</h3>
      <p class="scalar-params__subtitle">
        RAG 检索与 AI 问答的运行参数，保存后免重启、自下一请求生效。
      </p>
    </header>

    <el-table :data="list" class="scalar-params__table">
      <el-table-column prop="name" label="参数名称" min-width="140" show-overflow-tooltip />
      <el-table-column prop="key" label="参数键" min-width="200" show-overflow-tooltip />
      <el-table-column prop="value" label="参数值" min-width="120">
        <template #default="{ row }">{{ row.value ?? "—" }}</template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || "—" }}</template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="170" show-overflow-tooltip />
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="`编辑 · ${editing?.name ?? ''}`" width="460px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="72px">
        <el-form-item label="参数键">
          <el-input :model-value="editing?.key" disabled />
        </el-form-item>
        <el-form-item label="参数值" prop="value">
          <el-input v-model="form.value" :placeholder="valuePlaceholder" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.scalar-params {
  margin-top: 28px;
}

.scalar-params__head {
  margin-bottom: 16px;
}

.scalar-params__title {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
  color: #273249;
}

.scalar-params__subtitle {
  margin: 0;
  font-size: 13px;
  color: #8a94a6;
}

.scalar-params__table {
  width: 100%;
}
</style>
