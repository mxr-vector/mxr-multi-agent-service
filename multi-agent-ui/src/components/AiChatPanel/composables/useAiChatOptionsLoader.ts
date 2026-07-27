import { computed, ref } from "vue";
import type { KnowledgeLoadStatus } from "../types";

interface UseAiChatOptionsLoaderDeps {
  loadKnowledgeList: () => Promise<void>;
  loadTagList: () => Promise<void>;
}

export function useAiChatOptionsLoader(deps: UseAiChatOptionsLoaderDeps) {
  const knowledgeLoadStatus = ref<KnowledgeLoadStatus>("idle");
  const knowledgeLoadError = ref<string | null>(null);
  const tagLoadStatus = ref<KnowledgeLoadStatus>("idle");
  const tagLoadError = ref<string | null>(null);

  const knowledgeLoading = computed(() => knowledgeLoadStatus.value === "loading");
  const tagLoading = computed(() => tagLoadStatus.value === "loading");

  let knowledgeLoadPromise: Promise<void> | null = null;
  let tagLoadPromise: Promise<void> | null = null;

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

  async function ensureTagListLoaded(): Promise<void> {
    if (tagLoadStatus.value === "loaded") return;
    // Reuse the in-flight request so repeated dropdown openings do not fan out API calls.
    if (tagLoadPromise) return tagLoadPromise;

    tagLoadStatus.value = "loading";
    tagLoadError.value = null;
    tagLoadPromise = deps
      .loadTagList()
      .then(() => {
        tagLoadStatus.value = "loaded";
      })
      .catch((error: unknown) => {
        tagLoadStatus.value = "error";
        tagLoadError.value = error instanceof Error ? error.message : "标签加载失败";
      })
      .finally(() => {
        tagLoadPromise = null;
      });

    return tagLoadPromise;
  }

  function handleKnowledgeDropdownOpen(): void {
    void ensureKnowledgeListLoaded();
  }

  function handleTagDropdownOpen(): void {
    void ensureTagListLoaded();
  }

  return {
    knowledgeLoading,
    knowledgeLoadStatus,
    knowledgeLoadError,
    tagLoading,
    tagLoadStatus,
    tagLoadError,
    handleKnowledgeDropdownOpen,
    handleTagDropdownOpen,
  };
}
