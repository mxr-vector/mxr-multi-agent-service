<script setup lang="ts">
// 通用部门树面板：自取部门扁平列表组树，内置搜索过滤与"全部"清除入口。
// 选中节点时向外发射该节点及其全部后代的部门 id 集合（子树过滤用），
// 并把加载到的扁平列表通过 loaded 暴露给消费方复用，避免页面重复请求。
import { onMounted, ref, watch } from "vue";
// 仅作类型使用须用 import type：值导入会让 unplugin-vue-components 跳过
// 模板中 <el-tree> 的自动解析，导致其按需样式不注入（刷新直达本页时树样式丢失）
import type { ElTree } from "element-plus";
import {
    deptApi,
    buildDeptTree,
    collectDeptSubtreeIds,
    type Dept,
    type DeptTreeNode,
} from "@/api/system/dept";
import SearchInput from "@/components/SearchInput.vue";

withDefaults(
    defineProps<{
        /** 懒加载预留位：本期不实现按需加载，仅保留类型扩展点 */
        lazy?: boolean;
    }>(),
    { lazy: false },
);

const emit = defineEmits<{
    /** 选中节点：发射子树 id 集合与节点自身；清除选中时两者均为 null */
    select: [deptIds: string[] | null, dept: Dept | null];
    /** 部门扁平列表加载完成，供消费方（如表单树选择）复用 */
    loaded: [list: Dept[]];
}>();

const loading = ref(false);
const deptList = ref<Dept[]>([]);
const treeData = ref<DeptTreeNode[]>([]);
const keyword = ref("");
const currentId = ref<string | null>(null);
const treeRef = ref<InstanceType<typeof ElTree>>();

async function loadDepts() {
    loading.value = true;
    try {
        const res = await deptApi.list();
        deptList.value = res.data ?? [];
        treeData.value = buildDeptTree(deptList.value);
        emit("loaded", deptList.value);
    } finally {
        loading.value = false;
    }
}

// 搜索防抖：交给 el-tree 的 filter-node-method 前端过滤
let filterTimer: ReturnType<typeof setTimeout> | undefined;
watch(keyword, (val) => {
    if (filterTimer) clearTimeout(filterTimer);
    filterTimer = setTimeout(() => treeRef.value?.filter(val.trim()), 300);
});

function filterNode(value: string, data: Record<string, unknown>) {
    if (!value) return true;
    return String(data.name ?? "").toLowerCase().includes(value.toLowerCase());
}

function handleNodeClick(node: DeptTreeNode) {
    currentId.value = node.id;
    const ids = [...collectDeptSubtreeIds(deptList.value, node.id)];
    emit("select", ids, node);
}

/** "全部"入口：清除选中，通知消费方取消部门过滤 */
function clearSelection() {
    currentId.value = null;
    treeRef.value?.setCurrentKey();
    emit("select", null, null);
}

onMounted(loadDepts);
</script>

<template>
    <aside class="dept-tree-panel content-card list-panel" v-loading="loading">
        <div class="dept-tree-panel__head">
            <button class="dept-tree-panel__all" :class="{ active: currentId === null }" type="button"
                @click="clearSelection">
                全部
            </button>
            <SearchInput v-model="keyword" class="dept-tree-panel__search" placeholder="搜索部门" />
        </div>
        <el-tree ref="treeRef" class="dept-tree-panel__tree list-scroll" :data="treeData"
            :props="{ label: 'name', children: 'children' }" node-key="id" highlight-current
            :expand-on-click-node="false" default-expand-all :filter-node-method="filterNode"
            @node-click="handleNodeClick" />
    </aside>
</template>

<style scoped>
.dept-tree-panel {
    /* 参照设计稿比例：树面板约占内容区宽度 1/6，随视口伸缩并限定上下限 */
    flex: 0 0 clamp(240px, 16.5%, 340px);
    min-width: 0;
    border: 1px solid #e8ebf2;
    border-radius: 13px;
    background: #fff;
    box-shadow: 0 8px 24px rgb(43 56 86 / 3%);
}

.dept-tree-panel__head {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 14px 12px;
    border-bottom: 1px solid #edf0f5;
}

.dept-tree-panel__all {
    height: 34px;
    padding: 0 12px;
    border: 0;
    border-radius: 8px;
    color: #4c5670;
    background: #f3f5fa;
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition:
        background-color 150ms ease,
        color 150ms ease;
}

.dept-tree-panel__all:hover {
    background: #e8ecf7;
}

.dept-tree-panel__all.active {
    color: #526ae2;
    background: #edf0fd;
    font-weight: 600;
}

.dept-tree-panel__search {
    width: 100%;
}

.dept-tree-panel__tree {
    padding: 10px 8px;
}

@media (max-width: 720px) {
    .dept-tree-panel {
        width: 100%;
        flex: none;
    }
}
</style>
