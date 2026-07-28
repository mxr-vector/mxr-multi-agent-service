<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { knowledgeBaseApi, type KnowledgeBase } from "@/api/rag/knowledgeBase";
import { statsApi, type RagStats } from "@/api/rag/stats";
import type { Dept } from "@/api/system/dept";
import { confirmDanger } from "@/utils/confirm";
import { useUserStore } from "@/stores/userStore";
import KnowledgeBaseTable from "@/components/rag/KnowledgeBaseTable.vue";
import KnowledgeBaseFormDialog from "@/components/rag/KnowledgeBaseFormDialog.vue";
import SearchInput from "@/components/SearchInput.vue";
import Pagination from "@/components/Pagination.vue";
import DeptTreePanel from "@/components/DeptTreePanel.vue";
import type { KnowledgeBaseFormPayload } from "@/components/rag/types";

const loading = ref(false);
const knowledgeBases = ref<KnowledgeBase[]>([]);
const keyword = ref("");

// 分页状态（服务端分页）
const page = ref(1);
const size = ref(20);
const total = ref(0);

// 部门树筛选：仅 data_scope=all 的用户展示树面板（其余档位后端强制边界）。
// 用 computed 而非一次性赋值：store 已缓存 data_scope 时同步渲染，
// 避免每次进入页面都等 /auth/me 返回后才异步插入树（概率性闪现/缺失）
const userStore = useUserStore();
const showDeptTree = computed(() => userStore.dataScope === "all");
// 左侧部门树选中的子树 id 集合（null 表示不过滤）
const deptFilterIds = ref<string[] | null>(null);
// 左侧部门树当前选中的节点（新建知识库时作为默认归属部门）
const selectedDept = ref<Dept | null>(null);
// 部门扁平列表（复用 DeptTreePanel loaded 事件，供新建弹窗部门树选择，免重复请求）
const deptList = ref<Dept[]>([]);

// 全局统计（汇总卡片数据源，与列表共用部门筛选口径）
const stats = ref<RagStats>({
    knowledge_base_count: 0,
    document_count: 0,
    total_chunk_count: 0,
});

async function loadKnowledgeBases() {
    loading.value = true;
    try {
        const res = await knowledgeBaseApi.list({
            page: page.value,
            size: size.value,
            keyword: keyword.value.trim() || undefined,
            dept_ids: deptFilterIds.value ?? undefined,
        });
        knowledgeBases.value = res.data?.items ?? [];
        total.value = res.data?.total ?? 0;
    } finally {
        loading.value = false;
    }
}

async function loadStats() {
    const res = await statsApi.overview({
        dept_ids: deptFilterIds.value ?? undefined,
    });
    if (res.data) stats.value = res.data;
}

/** 部门树选中变化：记录选中节点、重置页码后按新边界重查列表与统计 */
function onDeptSelect(deptIds: string[] | null, dept: Dept | null) {
    deptFilterIds.value = deptIds;
    selectedDept.value = dept;
    page.value = 1;
    loadKnowledgeBases();
    loadStats();
}

// 关键词防抖：变更后回到第 1 页并触发服务端重载
let keywordTimer: ReturnType<typeof setTimeout> | undefined;
watch(keyword, () => {
    if (keywordTimer) clearTimeout(keywordTimer);
    keywordTimer = setTimeout(() => {
        page.value = 1;
        loadKnowledgeBases();
    }, 300);
});

// 新建 / 编辑弹窗
const dialogVisible = ref(false);
const submitting = ref(false);
const editing = ref<KnowledgeBase | null>(null);

function openCreate() {
    editing.value = null;
    dialogVisible.value = true;
}

function openEdit(base: KnowledgeBase) {
    editing.value = base;
    dialogVisible.value = true;
}

async function handleSubmit(payload: KnowledgeBaseFormPayload) {
    submitting.value = true;
    try {
        if (editing.value) {
            await knowledgeBaseApi.update(editing.value.id, {
                name: payload.name,
                description: payload.description || null,
                visibility: payload.visibility,
                status: payload.status,
            });
            ElMessage.success("知识库已更新");
        } else {
            await knowledgeBaseApi.create({
                name: payload.name,
                description: payload.description || null,
                visibility: payload.visibility,
                // 优先用弹窗显式选择的归属部门（仅 data_scope=all 生效），
                // 未选回退左树选中部门，仍未选由服务端按用户上下文注入
                dept_id: payload.dept_id ?? selectedDept.value?.id ?? null,
            });
            ElMessage.success("知识库已创建");
        }
        dialogVisible.value = false;
        await loadKnowledgeBases();
        await loadStats();
    } finally {
        submitting.value = false;
    }
}

async function removeKnowledgeBase(base: KnowledgeBase) {
    // 前置内容检查：非空禁删，避免文档 / 分块数据游离；
    // 后端为权威兜底（含文件夹检查与计数漂移场景），报错由响应拦截器自动 toast
    if (base.document_count > 0 || base.total_chunk_count > 0) {
        ElMessage.warning(
            `该知识库内仍有 ${base.document_count} 份文档，请先清空后再删除`
        );
        return;
    }
    const confirmed = await confirmDanger(
        `确定删除知识库「${base.name}」吗？删除后将不再出现在列表中。`
    );
    if (!confirmed) return;
    await knowledgeBaseApi.remove(base.id);
    ElMessage.success("知识库已删除");
    await loadKnowledgeBases();
    await loadStats();
}

onMounted(() => {
    loadKnowledgeBases();
    loadStats();
    // data_scope 懒加载（登录响应不含），showDeptTree 由 computed 响应式跟随；
    // /auth/me 失败不阻断页面主体，仅部门树入口缺失
    userStore.ensureDataScope().catch(() => { });
});
</script>

<template>
    <section class="rag-page list-page" v-loading="loading" element-loading-text="加载中…">
        <div class="kb-layout">
            <!-- 左栏：通用部门树（仅 data_scope=all 渲染），选中子树驱动右侧列表与统计过滤 -->
            <DeptTreePanel v-if="showDeptTree" @select="onDeptSelect" @loaded="deptList = $event" />
            <div class="kb-main">
                <section class="summary-grid">
                    <article>
                        <span>知识库总数</span>
                        <strong>{{ stats.knowledge_base_count }}</strong>
                        <small>全部知识源</small>
                    </article>
                    <article>
                        <span>已收录文档</span>
                        <strong>{{ stats.document_count }}</strong>
                        <small>所有知识库合计</small>
                    </article>
                    <article>
                        <span>分块总数</span>
                        <strong>{{ stats.total_chunk_count }}</strong>
                        <small>已入库块数</small>
                    </article>
                </section>
                <section class="content-card list-panel">
                    <div class="toolbar">
                        <div>
                            <h2>知识库列表</h2>
                            <span>共 {{ total }} 个知识库</span>
                        </div>
                        <div class="toolbar-actions">
                            <SearchInput v-model="keyword" placeholder="搜索名称 / 描述" />
                            <button class="primary-button" type="button" @click="openCreate">＋ 新建知识库</button>
                        </div>
                    </div>
                    <KnowledgeBaseTable class="list-scroll" :list="knowledgeBases" @edit="openEdit"
                        @remove="removeKnowledgeBase" />
                    <div class="pagination-bar list-footer">
                        <Pagination v-model:page="page" v-model:size="size" :total="total"
                            @change="loadKnowledgeBases" />
                    </div>
                </section>
            </div>
        </div>

        <KnowledgeBaseFormDialog v-model:visible="dialogVisible" :record="editing" :submitting="submitting"
            :show-dept="showDeptTree" :dept-list="deptList" :default-dept-id="selectedDept?.id ?? null"
            @submit="handleSubmit" />
    </section>
</template>

<style scoped>
.rag-page {
    gap: 20px;
    color: #273249;
}

/* 双栏骨架：左部门树面板（组件自带宽度约束）+ 右主列吃满剩余宽度 */
.kb-layout {
    display: flex;
    flex: 1;
    gap: 20px;
    min-height: 0;
}

.kb-main {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 20px;
    min-width: 0;
    min-height: 0;
}

.page-header,
.toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
}

.toolbar-actions {
    display: flex;
    align-items: center;
    gap: 12px;
}

.eyebrow {
    margin: 0 0 8px;
    color: #7b89b9;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.15px;
}

h1,
h2,
p {
    margin-top: 0;
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

.summary-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
    flex: 0 0 auto;
}

.summary-grid article,
.content-card {
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.summary-grid article {
    display: grid;
    gap: 7px;
    padding: 20px;
}

.summary-grid span,
.summary-grid small,
.toolbar span {
    color: #7d879a;
    font-size: 12px;
}

.summary-grid strong {
    font-size: 28px;
    letter-spacing: -1px;
}

.summary-grid small {
    color: #4eab83;
}

.toolbar {
    align-items: center;
    padding: 19px 20px;
    border-bottom: 1px solid #edf0f5;
}

/* 内容卡片撑满剩余高度、分页固定底部的骨架由全局工具类
   list-panel / list-scroll / list-footer 提供，此处只保留底栏视觉样式。 */
.pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 16px 20px;
    border-top: 1px solid #edf0f5;
}

h2 {
    margin-bottom: 4px;
    font-size: 16px;
}

@media (max-width: 720px) {

    /* 窄屏回退：双栏改纵向堆叠，随页面自然流滚动 */
    .kb-layout {
        flex-direction: column;
    }

    .page-header,
    .toolbar {
        align-items: flex-start;
        flex-direction: column;
    }

    .summary-grid {
        grid-template-columns: 1fr;
    }
}
</style>
