<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { authApi } from "@/api/system";
import { useUserStore } from "@/stores/userStore";
import StatusTag from "@/components/system/StatusTag.vue";

const userStore = useUserStore();

// 当前用户信息（刷新后内存态可能为空，挂载时懒拉 /auth/me 补齐）
const currentUser = computed(() => userStore.userInfo);
const displayName = computed(
    () => currentUser.value?.nickname || currentUser.value?.username || "—"
);
const avatarInitial = computed(() => displayName.value.charAt(0).toUpperCase());

// 基本资料表单（仅本人可维护字段：昵称/邮箱/手机/头像）
const profileFormRef = ref<FormInstance>();
const profileSubmitting = ref(false);
const profileForm = reactive({
    nickname: "",
    email: "",
    phone: "",
    avatar: "",
});
const profileRules: FormRules = {
    email: [{ type: "email", message: "邮箱格式不正确", trigger: "blur" }],
    phone: [{ pattern: /^1\d{10}$/, message: "手机号格式不正确", trigger: "blur" }],
};

/** 用 store 中的当前用户信息回填表单（保存后/挂载时调用） */
function fillProfileForm() {
    const user = currentUser.value;
    if (!user) return;
    Object.assign(profileForm, {
        nickname: user.nickname ?? "",
        email: user.email ?? "",
        phone: user.phone ?? "",
        avatar: user.avatar ?? "",
    });
}

async function submitProfile() {
    const valid = await profileFormRef.value?.validate().catch(() => false);
    if (!valid) return;
    profileSubmitting.value = true;
    try {
        const res = await authApi.updateProfile({
            nickname: profileForm.nickname || null,
            email: profileForm.email || null,
            phone: profileForm.phone || null,
            avatar: profileForm.avatar || null,
        });
        // 合并回 store：/auth/me 更新响应不含 data_scope 等聚合字段，展开保留原值
        userStore.userInfo = { ...userStore.userInfo, ...res.data };
        ElMessage.success("个人资料已保存");
    } finally {
        profileSubmitting.value = false;
    }
}

// 修改密码表单（需原密码校验，区别于用户管理的管理员重置密码）
const pwdFormRef = ref<FormInstance>();
const pwdSubmitting = ref(false);
const pwdForm = reactive({
    oldPassword: "",
    newPassword: "",
    confirmPassword: "",
});
const pwdRules: FormRules = {
    oldPassword: [{ required: true, message: "请输入原密码", trigger: "blur" }],
    newPassword: [
        { required: true, message: "请输入新密码", trigger: "blur" },
        { min: 6, message: "密码至少 6 位", trigger: "blur" },
    ],
    confirmPassword: [
        { required: true, message: "请再次输入新密码", trigger: "blur" },
        {
            validator: (_rule, value: string, callback) => {
                if (value && value !== pwdForm.newPassword) {
                    callback(new Error("两次输入的新密码不一致"));
                } else {
                    callback();
                }
            },
            trigger: "blur",
        },
    ],
};

async function submitPassword() {
    const valid = await pwdFormRef.value?.validate().catch(() => false);
    if (!valid) return;
    pwdSubmitting.value = true;
    try {
        await authApi.changePassword(pwdForm.oldPassword, pwdForm.newPassword);
        ElMessage.success("密码修改成功");
        Object.assign(pwdForm, { oldPassword: "", newPassword: "", confirmPassword: "" });
        pwdFormRef.value?.clearValidate();
    } finally {
        pwdSubmitting.value = false;
    }
}

onMounted(async () => {
    // 刷新页面后 userInfo 为空时先补齐，再回填表单
    if (!userStore.userInfo) {
        await userStore.fetchUserInfo().catch(() => { });
    }
    fillProfileForm();
});
</script>

<template>
    <section class="system-page profile-page">
        <div class="profile-layout">
            <!-- 左栏：账号概览卡片（只读展示） -->
            <section class="content-card summary-card">
                <span class="summary-avatar" aria-hidden="true">
                    <img v-if="currentUser?.avatar" :src="currentUser.avatar" alt="" />
                    <template v-else>{{ avatarInitial }}</template>
                </span>
                <h2 class="summary-name">{{ displayName }}</h2>
                <p class="summary-username">@{{ currentUser?.username ?? "—" }}</p>
                <ul class="summary-meta">
                    <li>
                        <span class="meta-label">状态</span>
                        <StatusTag v-if="currentUser" :status="currentUser.status" />
                        <span v-else>—</span>
                    </li>
                    <li>
                        <span class="meta-label">邮箱</span>
                        <span class="meta-value">{{ currentUser?.email || "—" }}</span>
                    </li>
                    <li>
                        <span class="meta-label">手机号</span>
                        <span class="meta-value">{{ currentUser?.phone || "—" }}</span>
                    </li>
                    <li>
                        <span class="meta-label">创建时间</span>
                        <span class="meta-value">{{ currentUser?.created_at || "—" }}</span>
                    </li>
                </ul>
            </section>

            <div class="profile-main">
                <!-- 基本资料维护 -->
                <section class="content-card form-card">
                    <div class="card-header">
                        <h3>基本资料</h3>
                        <span class="card-subtitle">昵称、联系方式与头像，保存后即时生效</span>
                    </div>
                    <el-form ref="profileFormRef" class="card-form" :model="profileForm" :rules="profileRules"
                        label-width="90px">
                        <el-form-item label="用户名">
                            <el-input :model-value="currentUser?.username ?? ''" disabled />
                        </el-form-item>
                        <el-form-item label="昵称" prop="nickname">
                            <el-input v-model="profileForm.nickname" placeholder="选填" maxlength="50" />
                        </el-form-item>
                        <el-form-item label="邮箱" prop="email">
                            <el-input v-model="profileForm.email" placeholder="选填" maxlength="100" />
                        </el-form-item>
                        <el-form-item label="手机号" prop="phone">
                            <el-input v-model="profileForm.phone" placeholder="选填" maxlength="20" />
                        </el-form-item>
                        <el-form-item label="头像地址" prop="avatar">
                            <el-input v-model="profileForm.avatar" placeholder="图片 URL，选填" maxlength="255" />
                        </el-form-item>
                        <el-form-item>
                            <el-button type="primary" :loading="profileSubmitting" @click="submitProfile">
                                保存资料
                            </el-button>
                        </el-form-item>
                    </el-form>
                </section>

                <!-- 修改密码 -->
                <section class="content-card form-card">
                    <div class="card-header">
                        <h3>修改密码</h3>
                        <span class="card-subtitle">需先验证原密码，新密码至少 6 位</span>
                    </div>
                    <el-form ref="pwdFormRef" class="card-form" :model="pwdForm" :rules="pwdRules" label-width="90px">
                        <el-form-item label="原密码" prop="oldPassword">
                            <el-input v-model="pwdForm.oldPassword" type="password" show-password placeholder="当前登录密码"
                                maxlength="100" />
                        </el-form-item>
                        <el-form-item label="新密码" prop="newPassword">
                            <el-input v-model="pwdForm.newPassword" type="password" show-password placeholder="至少 6 位"
                                maxlength="100" />
                        </el-form-item>
                        <el-form-item label="确认新密码" prop="confirmPassword">
                            <el-input v-model="pwdForm.confirmPassword" type="password" show-password
                                placeholder="再次输入新密码" maxlength="100" />
                        </el-form-item>
                        <el-form-item>
                            <el-button type="primary" :loading="pwdSubmitting" @click="submitPassword">
                                修改密码
                            </el-button>
                        </el-form-item>
                    </el-form>
                </section>
            </div>
        </div>
    </section>
</template>

<style scoped>
.system-page {
    color: #273249;
}

/* 左右双栏：左账号概览固定宽，右侧表单卡片吃满剩余 */
.profile-layout {
    display: flex;
    align-items: flex-start;
    gap: 20px;
}

.content-card {
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.summary-card {
    display: flex;
    width: 280px;
    flex: 0 0 auto;
    flex-direction: column;
    align-items: center;
    padding: 32px 24px;
}

.summary-avatar {
    display: grid;
    overflow: hidden;
    width: 72px;
    height: 72px;
    place-items: center;
    border-radius: 20px;
    color: #fff;
    background: linear-gradient(145deg, #5b8bff, #6c63ff);
    font-size: 30px;
    font-weight: 700;
}

.summary-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.summary-name {
    margin: 14px 0 2px;
    font-size: 17px;
}

.summary-username {
    margin: 0 0 18px;
    color: #9aa4bd;
    font-size: 13px;
}

.summary-meta {
    width: 100%;
    margin: 0;
    padding: 14px 0 0;
    border-top: 1px solid #edf0f5;
    list-style: none;
}

.summary-meta li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 7px 0;
    font-size: 13px;
}

.meta-label {
    flex: 0 0 auto;
    color: #7d879a;
}

.meta-value {
    overflow: hidden;
    text-align: right;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.profile-main {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 20px;
    min-width: 0;
}

.card-header {
    padding: 19px 20px;
    border-bottom: 1px solid #edf0f5;
}

.card-header h3 {
    margin: 0 0 4px;
    font-size: 16px;
}

.card-subtitle {
    color: #7d879a;
    font-size: 12px;
}

.card-form {
    max-width: 520px;
    padding: 20px 20px 8px;
}

@media (max-width: 900px) {
    .profile-layout {
        flex-direction: column;
    }

    .summary-card {
        width: 100%;
    }
}
</style>
