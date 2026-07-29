import { computed, ref } from "vue";
import type { KnowledgeLoadStatus } from "../types";

interface UseAiChatOptionsLoaderDeps {
  loadKnowledgeList: () => Promise<void>;
}

export function useAiChatOptionsLoader(deps: UseAiChatOptionsLoaderDeps) {
  const knowledgeLoadStatus = ref<KnowledgeLoadStatus>("idle");
  const knowledgeLoadError = ref<string | null>(null);

  const knowledgeLoading = computed(() => knowledgeLoadStatus.value === "loading");

  let knowledgeLoadPromise: Promise<void> | null = null;

  async function ensureKnowledgeListLoaded(): Promise<void> {
    if (knowledgeLoadStatus.value === "loaded") return;
    // Reuse the in-flight request so repeated dropdown openings do not fan out API calls.
    if (knowledgeLoadPromise) return knowledgeLoadPromise;

    knowledgeLoadStatus.value = "loading";
    knowledgeLoadError.value = null;
    knowledgeLoadPromise = deps
      .loadKnowledgeList()
      .then(() => {
        knowledgeLoadStatus.value = "loaded";
      })
      .catch((error: unknown) => {
        knowledgeLoadStatus.value = "error";
        knowledgeLoadError.value = error instanceof Error ? error.message : "知识库加载失败";
      })
      .finally(() => {
        knowledgeLoadPromise = null;
      });

    return knowledgeLoadPromise;
  }

  function handleKnowledgeDropdownOpen(): void {
    void ensureKnowledgeListLoaded();
  }

  return {
    knowledgeLoading,
    knowledgeLoadStatus,
    knowledgeLoadError,
    handleKnowledgeDropdownOpen,
  };
}
