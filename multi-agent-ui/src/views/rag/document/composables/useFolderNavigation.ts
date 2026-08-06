import { computed, nextTick, ref, type Ref } from "vue";
import type { Folder } from "@/api/rag/folders";
import type { KnowledgeBase } from "@/api/rag/knowledgeBase";

type KnowledgeTreeHandle = {
  setCurrentKey(key: string | null): void;
};

export function useFolderNavigation(
  activeKnowledgeBase: Ref<KnowledgeBase | null>,
  folders: Ref<Folder[]>,
  knowledgeTree: Ref<KnowledgeTreeHandle | undefined>,
  page: Ref<number>
) {
  const selectedFolderId = ref<string | null>(null);
  const history = ref<(string | null)[]>([null]);
  const historyIndex = ref(0);

  const canBack = computed(() => historyIndex.value > 0);
  const canForward = computed(() => historyIndex.value < history.value.length - 1);

  function selectFolder(id: string | null, pushHistory = true) {
    selectedFolderId.value = id;
    page.value = 1;
    if (pushHistory) {
      history.value = history.value.slice(0, historyIndex.value + 1);
      history.value.push(id);
      historyIndex.value = history.value.length - 1;
    }
    nextTick(() => knowledgeTree.value?.setCurrentKey(id ?? activeKnowledgeBase.value?.id ?? null));
  }

  function goBack() {
    if (!canBack.value) return;
    historyIndex.value -= 1;
    selectFolder(history.value[historyIndex.value], false);
  }

  function goForward() {
    if (!canForward.value) return;
    historyIndex.value += 1;
    selectFolder(history.value[historyIndex.value], false);
  }

  function goUp() {
    const current = folders.value.find((folder) => folder.id === selectedFolderId.value);
    selectFolder(current?.parent_id ?? null);
  }

  function reset() {
    selectedFolderId.value = null;
    history.value = [null];
    historyIndex.value = 0;
  }

  const breadcrumb = computed(() => {
    const path: { id: string | null; name: string }[] = [
      { id: null, name: activeKnowledgeBase.value?.name ?? "根目录" },
    ];
    if (!selectedFolderId.value) return path;

    const foldersById = new Map(folders.value.map((folder) => [folder.id, folder]));
    const chain: Folder[] = [];
    let current = foldersById.get(selectedFolderId.value);
    while (current) {
      chain.unshift(current);
      current = current.parent_id ? foldersById.get(current.parent_id) : undefined;
    }
    chain.forEach((folder) => path.push({ id: folder.id, name: folder.name }));
    return path;
  });

  return {
    selectedFolderId,
    canBack,
    canForward,
    breadcrumb,
    selectFolder,
    goBack,
    goForward,
    goUp,
    reset,
  };
}
