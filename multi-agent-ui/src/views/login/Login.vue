<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { useUserStore } from "@/stores/userStore";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const formRef = ref<FormInstance>();
const loading = ref(false);

// 开发期默认填充种子账号，便于快速进入系统
const form = reactive({
    username: "admin",
    password: "123456",
});

const rules: FormRules = {
    username: [{ required: true, message: "请输入用户名", trigger: "blur" }],
    password: [{ required: true, message: "请输入密码", trigger: "blur" }],
};

/** 登录成功后回跳守卫记录的来源页，缺省进首页 */
async function handleLogin() {
    if (!formRef.value) return;
    const valid = await formRef.value.validate().catch(() => false);
    if (!valid) return;
    loading.value = true;
    try {
        await userStore.login(form.username, form.password);
        ElMessage.success("登录成功");
        const redirect = (route.query.redirect as string) || "/";
        await router.replace(redirect);
    } finally {
        loading.value = false;
    }
}
</script>

<template>
    <div class="login-page">
        <div class="login-card">
            <header class="login-head">
                <h1>Multi-Agent Service</h1>
                <p>请登录后进入管理控制台</p>
            </header>
            <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large"
                @keyup.enter="handleLogin">
                <el-form-item label="用户名" prop="username">
                    <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="'User'" clearable />
                </el-form-item>
                <el-form-item label="密码" prop="password">
                    <el-input v-model="form.password" type="password" placeholder="请输入密码" :prefix-icon="'Lock'"
                        show-password />
                </el-form-item>
                <el-button class="login-submit" type="primary" size="large" :loading="loading" @click="handleLogin">
                    登 录
                </el-button>
            </el-form>
        </div>
    </div>
</template>

<style scoped>
.login-page {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: linear-gradient(160deg, #eef2fb 0%, #f7f9fd 45%, #e9eefa 100%);
}

.login-card {
    width: 380px;
    padding: 36px 34px 30px;
    border: 1px solid #e8ebf2;
    border-radius: 14px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 6%);
}

.login-head {
    margin-bottom: 24px;
    text-align: center;
}

.login-head h1 {
    margin: 0;
    font-size: 22px;
    color: #26324d;
}

.login-head p {
    margin: 8px 0 0;
    font-size: 13px;
    color: #8a94ab;
}

.login-submit {
    width: 100%;
    margin-top: 6px;
}
</style>
