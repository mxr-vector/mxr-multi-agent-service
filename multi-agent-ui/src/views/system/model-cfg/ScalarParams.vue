<script setup lang="ts">
// RAG / AI 问答运行参数区域：白名单内置标量参数（RAG_* / CHAT_*）以卡片展示、点值即改，
// 保存后后端触发配置快照刷新（免重启生效），refreshed 透出是否热更新成功。
// 另混入纯前端本地参数（如 drawio 服务地址），仅存 localStorage、不走后端接口。
import { onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { configApi, type Config } from "@/api/system/config";
import { useSysParamStore } from "@/stores/sysParamStore";

// 统一行结构：后端标量参数携 id，本地参数 source='local' 且无 id
type ScalarRow = (Config & { source: "backend" }) | (LocalRow & { source: "local" });
interface LocalRow {
    key: string;
    name: string;
    value: string | null;
    remark: string | null;
    updated_at: string | null;
}

const sysParamStore = useSysParamStore();
const loading = ref(false);
const list = ref<ScalarRow[]>([]);

async function loadScalars() {
    loading.value = true;
    try {
        const res = await configApi.listScalars();
        const backend: ScalarRow[] = (res.data ?? []).map((c) => ({ ...c, source: "backend" }));
        const local: ScalarRow[] = sysParamStore.list().map((p) => ({ ...p, source: "local" }));
        // 本地参数置底（与后端参数同表展示，便于集中管理）
        list.value = [...backend, ...local];
    } finally {
        loading.value = false;
    }
}

// 编辑弹窗（仅可改 value / remark：key 为白名单契约键，不可变；无新建/删除入口）
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<ScalarRow | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
    value: "",
    remark: "",
});
// 后端标量参数为正整数；本地 drawio 地址为 http(s) URL，校验按行来源区分
const rules: FormRules = {
    value: [
        { required: true, message: "请输入参数值", trigger: "blur" },
        {
            validator: (_rule, val, cb) => {
                if (editing.value?.source === "local") {
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
                const n = Number(val);
                if (!Number.isInteger(n) || n <= 0) cb(new Error("必须为正整数"));
                else cb();
            },
            trigger: "blur",
        },
    ],
};

function openEdit(row: ScalarRow) {
    editing.value = row;
    Object.assign(form, { value: row.value ?? "", remark: row.remark ?? "" });
    dialogVisible.value = true;
    formRef.value?.clearValidate();
}

async function submit() {
    if (!editing.value) return;
    const valid = await formRef.value?.validate().catch(() => false);
    if (!valid) return;
    submitting.value = true;
    try {
        if (editing.value.source === "local") {
            // 纯前端参数：仅写 localStorage，不调后端，下次打开编辑器即生效
            sysParamStore.update(editing.value.key, {
                value: form.value.trim(),
                remark: form.remark || null,
            });
            ElMessage.success("已保存（仅本浏览器生效）");
        } else {
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
                    <el-input v-model="form.value"
                        :placeholder="editing?.source === 'local' ? 'http(s):// 地址' : '正整数'" />
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
