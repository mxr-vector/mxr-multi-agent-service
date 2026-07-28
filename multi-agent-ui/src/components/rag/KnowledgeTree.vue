<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import type { ElTree } from "element-plus";
import type Node from "element-plus/es/components/tree/src/model/node";
import { knowledgeBaseApi, type KnowledgeBase } from "@/api/rag/knowledgeBase";
import { folderApi, type Folder } from "@/api/rag/folders";
import SearchInput from "@/components/SearchInput.vue";
import SvgIcon from "@/components/SvgIcon.vue";

/**
 * 知识库导航树：根节点为知识库列表，展开/点击某个知识库时
 * 才懒加载其内部文件夹（按知识库整树拉取一次并缓存）。
 * 对外只暴露「选中了哪个知识库/文件夹」与「某知识库的文件夹已加载」。
 */
const props = withDefaults(
    defineProps<{
        /** 知识库列表加载完成后自动选中第一个（避免首屏空白） */
        autoSelectFirst?: boolean;
        /** 部门过滤子树 id 集合（null 表示不过滤），变化时重载知识库列表 */
        deptIds?: string[] | null;
    }>(),
    { autoSelectFirst: true, deptIds: null }
);

const emit = defineEmits<{
    (e: "select", payload: { kb: KnowledgeBase; folder: Folder | null }): void;
    (e: "folders-loaded", kbId: string, folders: Folder[]): void;
    (e: "cleared"): void;
}>();

/** 树节点数据：知识库与文件夹共用一棵树，用 type 区分 */
interface TreeNodeData {
    id: string;
    name: string;
    type: "kb" | "folder";
    isLeaf: boolean;
    kb?: KnowledgeBase;
    folder?: Folder;
}

const treeRef = ref<InstanceType<typeof ElTree>>();
const keyword = ref("");
const kbCount = ref(-1); // -1 表示尚未加载完成
let knowledgeBases: KnowledgeBase[] = [];
// 文件夹缓存：每个知识库仅拉取一次，刷新时主动失效
const folderCache = new Map<string, Folder[]>();
let bootstrapped = false;

watch(keyword, (v) => treeRef.value?.filter(v));
function filterNode(value: string, data: TreeNodeData) {
    return value ? data.name.includes(value) : true;
}

async function fetchFolders(kbId: string): Promise<Folder[]> {
    const cached = folderCache.get(kbId);
    if (cached) return cached;
    const res = await folderApi.list({ knowledge_base_id: kbId, page: 1, size: 200 });
    const list = res.data?.items ?? [];
    folderCache.set(kbId, list);
    emit("folders-loaded", kbId, list);
    return list;
}

function folderChildren(list: Folder[], parentId: string | null): TreeNodeData[] {
    return list
        .filter((f) => (f.parent_id ?? null) === parentId)
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((f) => ({
            id: f.id,
            name: f.name,
            type: "folder" as const,
            isLeaf: !list.some((c) => c.parent_id === f.id),
            folder: f,
        }));
}

/** 懒加载回调：level 0 → 知识库；kb 节点 → 根文件夹；folder 节点 → 子文件夹（走缓存） */
async function loadNode(node: Node, resolve: (data: TreeNodeData[]) => void) {
    if (node.level === 0) {
        const res = await knowledgeBaseApi.list({
            page: 1,
            size: 200,
            dept_ids: props.deptIds ?? undefined,
        });
        knowledgeBases = res.data?.items ?? [];
        kbCount.value = knowledgeBases.length;
        resolve(
            knowledgeBases.map((kb) => ({
                id: kb.id,
                name: kb.name,
                type: "kb" as const,
                isLeaf: false,
                kb,
            }))
        );
        if (props.autoSelectFirst && !bootstrapped && knowledgeBases.length) {
            bootstrapped = true;
            const first = knowledgeBases[0];
            nextTick(() => {
                treeRef.value?.setCurrentKey(first.id);
                emit("select", { kb: first, folder: null });
                nodeById(first.id)?.expand();
            });
        }
        // 部门过滤后无知识库：通知父组件清空当前选中态
        if (!knowledgeBases.length) emit("cleared");
        return;
    }
    const data = node.data as unknown as TreeNodeData;
    if (data.type === "kb") {
        const list = await fetchFolders(data.id);
        resolve(folderChildren(list, null));
    } else {
        const kbId = data.folder!.knowledge_base_id;
        resolve(folderChildren(folderCache.get(kbId) ?? [], data.id));
    }
}

function onNodeClick(data: TreeNodeData, node: Node) {
    if (data.type === "kb") {
        emit("select", { kb: data.kb!, folder: null });
        emitCachedFolders(data.id);
        if (!node.expanded) node.expand();
    } else {
        const kbId = data.folder!.knowledge_base_id;
        const kb = knowledgeBases.find((b) => b.id === kbId);
        if (!kb) return;
        emit("select", { kb, folder: data.folder! });
        emitCachedFolders(kbId);
    }
}

/** 点选时若该知识库文件夹已缓存，补发一次回流，
 *  避免父组件在「切库 + 直接点文件夹」时拿不到列表 */
function emitCachedFolders(kbId: string) {
    const cached = folderCache.get(kbId);
    if (cached) emit("folders-loaded", kbId, cached);
}

/** 通过内部 store 定位节点（element-plus 未公开的稳定内部结构） */
function nodeById(id: string): Node | undefined {
    return (treeRef.value as unknown as { store?: { nodesMap?: Record<string, Node> } })?.store
        ?.nodesMap?.[id];
}

/** 文件夹增删改后由父组件调用：失效缓存、重拉并重载该知识库子树 */
async function refreshFolders(kbId: string) {
    folderCache.delete(kbId);
    await fetchFolders(kbId);
    const node = nodeById(kbId);
    if (node) {
        node.loaded = false;
        node.childNodes = [];
        if (node.expanded) node.expand();
    }
}

/** 同步高亮（面包屑/前进后退驱动树选中态），key 为文件夹或知识库 id */
function setCurrentKey(key: string | null) {
    treeRef.value?.setCurrentKey(key ?? undefined);
}

// 部门筛选变化：失效文件夹缓存并重载根节点（知识库列表随部门边界变动），
// 重置 bootstrapped 让新列表重新自动选中第一个知识库
watch(
    () => props.deptIds,
    () => {
        folderCache.clear();
        bootstrapped = false;
        const root = (treeRef.value as unknown as { store?: { root?: Node } })?.store?.root;
        if (!root) return;
        root.loaded = false;
        root.childNodes = [];
        root.expand();
    }
);

defineExpose({ refreshFolders, setCurrentKey });
</script>

<template>
    <div class="knowledge-tree">
        <SearchInput v-model="keyword" placeholder="搜索知识库 / 文件夹" />
        <el-tree ref="treeRef" class="kt-tree" lazy :load="loadNode" node-key="id"
            :props="{ label: 'name', isLeaf: 'isLeaf' }" :filter-node-method="filterNode" highlight-current
            :expand-on-click-node="false" @node-click="onNodeClick">
            <template #default="{ data }">
                <span class="kt-node" :class="data.type">
                    <SvgIcon :name="data.type === 'kb' ? 'zhishihudong' : 'danganhe'" :size="14" />
                    <span class="kt-label">{{ data.name }}</span>
                    <span v-if="data.type === 'kb'" class="kt-count">{{ data.kb.document_count }}</span>
                </span>
            </template>
        </el-tree>
        <el-empty v-if="kbCount === 0" description="暂无知识库" :image-size="48">
            <template #image>
                <SvgIcon class="kt-empty-icon" name="zhishihudong" :size="44" />
            </template>
        </el-empty>
    </div>
</template>

<style scoped>
.knowledge-tree {
    display: grid;
    gap: 10px;
}

.knowledge-tree :deep(.search-input) {
    width: 100%;
}

.kt-tree {
    max-height: 360px;
    overflow: auto;
    font-size: 13px;
    background: transparent;
}

.kt-node {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
    padding-right: 6px;
}

/* 知识库节点加重，作为一级导航锚点；文件夹保持常规字重 */
.kt-node.kb .kt-label {
    font-weight: 600;
    color: #38445e;
}

.kt-node .svg-icon {
    color: #98a2b8;
}

.kt-node.kb .svg-icon {
    color: #526ae2;
}

.kt-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* 文档数量胶囊：轻量提示该知识库体量 */
.kt-count {
    margin-left: auto;
    padding: 0 6px;
    border-radius: 999px;
    color: #6a7ce6;
    background: #eef1fd;
    font-size: 11px;
    line-height: 16px;
}

.kt-empty-icon {
    color: #cfd6e4;
}
</style>
