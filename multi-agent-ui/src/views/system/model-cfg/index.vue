<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { modelConfigApi, type ModelConfig } from "@/api/system/modelConfig";
import { useDictStore } from "@/stores/dictStore";
import FormDialog from "@/components/ui/FormDialog.vue";
import ModelCard from "./ModelCard.vue";
import ScalarParams from "./ScalarParams.vue";

const dictStore = useDictStore();
dictStore.ensureLoaded();
// 上下文窗口预设档位（字典 context_window，值为 token 数字符串）
const contextWindowOptions = computed(() => dictStore.getOptions("context_window"));
// 嵌入模型协议档位（字典 embedding_provider，重排序模型 provider 复用该协议集）
const providerOptions = computed(() => dictStore.getOptions("embedding_provider"));

const loading = ref(false);
const list = ref<ModelConfig[]>([]);

async function loadConfigs() {
    loading.value = true;
    try {
        const res = await modelConfigApi.list();
        list.value = res.data ?? [];
    } finally {
        loading.value = false;
    }
}

// 编辑弹窗（无新建/删除入口：角色集合由后端固定，内置行禁删）
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<ModelConfig | null>(null);
const formRef = ref<FormInstance>();
const form = reactive({
    name: "",
    model_name: "",
    api_url: "",
    api_key: "",
    provider: "",
    timeout: null as number | null,
    max_retries: null as number | null,
    // 字典下拉存储值为字符串（token 数），提交前转数字
    context_window: "" as string,
    remark: "",
});
const rules: FormRules = {
    name: [{ required: true, message: "请输入卡片名称", trigger: "blur" }],
    model_name: [{ required: true, message: "请输入模型名", trigger: "blur" }],
    api_url: [{ required: true, message: "请输入接口地址", trigger: "blur" }],
};

// chat/visual 显示超时/重试；仅 rerank 显示 provider；仅 chat 显示上下文窗口
const showTimeout = computed(() => ["chat", "visual"].includes(editing.value?.role ?? ""));
const showProvider = computed(() => editing.value?.role === "rerank");
const showContextWindow = computed(() => editing.value?.role === "chat");

function openEdit(config: ModelConfig) {
    editing.value = config;
    Object.assign(form, {
        name: config.name,
        model_name: config.model_name,
        api_url: config.api_url,
        // 密钥默认留空，留空则不修改（避免把掩码值写回覆盖真实密钥）
        api_key: "",
        provider: config.provider ?? "",
        timeout: config.timeout,
        max_retries: config.max_retries,
        context_window: config.context_window != null ? String(config.context_window) : "",
        remark: config.remark ?? "",
    });
    dialogVisible.value = true;
    formRef.value?.clearValidate();
}

async function submit() {
    if (!editing.value) return;
    const valid = await formRef.value?.validate().catch(() => false);
    if (!valid) return;
    submitting.value = true;
    try {
        const res = await modelConfigApi.update(editing.value.id, {
            name: form.name,
            model_name: form.model_name,
            api_url: form.api_url,
            // 仅在填写了新密钥时提交；留空则后端保持原值
            api_key: form.api_key.trim() || undefined,
            provider: showProvider.value ? form.provider || null : undefined,
            timeout: showTimeout.value ? form.timeout : undefined,
            max_retries: showTimeout.value ? form.max_retries : undefined,
            // 上下文窗口字典存字符串，提交转数字；非 chat 角色不提交
            context_window: showContextWindow.value
                ? (form.context_window ? Number(form.context_window) : null)
                : undefined,
            remark: form.remark || null,
        });
        // 后端在保存成功后触发配置快照刷新，refreshed 透出是否热更新生效
        if (res.data?.refreshed === false) {
            ElMessage.warning("已保存，但配置热更新校验未通过，仍沿用旧配置");
        } else {
            ElMessage.success("已保存，配置已热更新");
        }
        dialogVisible.value = false;
        await loadConfigs();
    } finally {
        submitting.value = false;
    }
}

onMounted(loadConfigs);
</script>

<template>
    <section class="model-cfg-page" v-loading="loading">
        <header class="model-cfg-page__head">
            <h2 class="model-cfg-page__title">模型配置</h2>
            <p class="model-cfg-page__subtitle">
                对话 / 改写 / 多模态 / 重排序模型的运行参数，保存后免重启、自下一请求生效。
            </p>
        </header>

        <div class="model-cfg-page__grid">
            <ModelCard v-for="config in list" :key="config.id" :config="config" @edit="openEdit" />
        </div>

        <!-- RAG / AI 问答运行参数区域（白名单标量参数，同样支持免重启热更新） -->
        <ScalarParams />

        <!-- 编辑弹窗 -->
        <FormDialog v-model="dialogVisible" :title="`编辑 · ${editing?.name ?? ''}`" :submitting="submitting"
            @submit="submit">
            <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
                <el-form-item label="卡片名称" prop="name">
                    <el-input v-model="form.name" maxlength="100" />
                </el-form-item>
                <el-form-item label="模型名" prop="model_name">
                    <el-input v-model="form.model_name" maxlength="200" />
                </el-form-item>
                <el-form-item label="接口地址" prop="api_url">
                    <el-input v-model="form.api_url" placeholder="OpenAI 兼容 base_url" />
                </el-form-item>
                <el-form-item label="API 密钥">
                    <el-input v-model="form.api_key" type="password" show-password placeholder="留空则不修改" />
                </el-form-item>
                <el-form-item v-if="showProvider" label="Provider">
                    <el-select v-model="form.provider" placeholder="选择 Provider" clearable>
                        <el-option v-for="item in providerOptions" :key="item.value" :label="item.label"
                            :value="item.value" />
                    </el-select>
                </el-form-item>
                <template v-if="showTimeout">
                    <el-form-item label="超时(秒)">
                        <el-input-number v-model="form.timeout" :min="1" :max="600" controls-position="right" />
                    </el-form-item>
                    <el-form-item label="重试次数">
                        <el-input-number v-model="form.max_retries" :min="0" :max="10" controls-position="right" />
                    </el-form-item>
                </template>
                <el-form-item v-if="showContextWindow" label="上下文窗口">
                    <el-select v-model="form.context_window" placeholder="选择上下文窗口" clearable>
                        <el-option v-for="item in contextWindowOptions" :key="item.value" :label="item.label"
                            :value="item.value" />
                    </el-select>
                </el-form-item>
                <el-form-item label="备注">
                    <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="选填" />
                </el-form-item>
            </el-form>
        </FormDialog>
    </section>
</template>

<style scoped>
.model-cfg-page {
    padding: 4px;
    color: #273249;
}

.model-cfg-page__head {
    margin-bottom: 16px;
}

.model-cfg-page__title {
    margin: 0 0 4px;
    font-size: 18px;
    font-weight: 600;
}

.model-cfg-page__subtitle {
    margin: 0;
    font-size: 13px;
    color: #8a94a6;
}

.model-cfg-page__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
}
</style>
