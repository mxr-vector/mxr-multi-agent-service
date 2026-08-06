import { computed, reactive, type Ref } from "vue";
import type { RagDocument } from "@/api/rag/document";

export type FilterState = {
  keyword: string;
  dateRange: [string, string] | null;
  tableType: "" | "yes" | "no";
  remark: string;
};

export const tableTypeOptions = [
  { label: "全部", value: "" },
  { label: "是", value: "yes" },
  { label: "否", value: "no" },
] as const;

const SPREADSHEET_TYPES = new Set(["excel", "xlsx", "xls"]);

function emptyFilter(): FilterState {
  return { keyword: "", dateRange: null, tableType: "", remark: "" };
}

function isSpreadsheet(document: RagDocument): boolean {
  return SPREADSHEET_TYPES.has((document.doc_type ?? "").toLowerCase());
}

export function useDocumentFilters(
  allDocuments: Ref<RagDocument[]>,
  selectedFolderId: Ref<string | null>,
  page: Ref<number>,
  size: Ref<number>
) {
  const draft = reactive<FilterState>(emptyFilter());
  const applied = reactive<FilterState>(emptyFilter());

  const filteredDocuments = computed(() => {
    const keyword = applied.keyword.trim().toLowerCase();
    const remark = applied.remark.trim().toLowerCase();
    const [from, to] = applied.dateRange ?? [null, null];

    return allDocuments.value.filter((document) => {
      if (selectedFolderId.value && document.folder_id !== selectedFolderId.value) return false;
      if (keyword) {
        const name = (document.title || document.source_uri || "").toLowerCase();
        if (!name.includes(keyword)) return false;
      }
      if (applied.tableType === "yes" && !isSpreadsheet(document)) return false;
      if (applied.tableType === "no" && isSpreadsheet(document)) return false;
      if (from && to && document.valid_from) {
        const date = document.valid_from.slice(0, 10);
        if (date < from.slice(0, 10) || date > to.slice(0, 10)) return false;
      }
      if (
        remark &&
        !String(document.metadata?.remark ?? "")
          .toLowerCase()
          .includes(remark)
      ) {
        return false;
      }
      return true;
    });
  });

  const total = computed(() => filteredDocuments.value.length);
  const pagedDocuments = computed(() => {
    const start = (page.value - 1) * size.value;
    return filteredDocuments.value.slice(start, start + size.value);
  });

  function apply() {
    Object.assign(applied, draft);
    page.value = 1;
  }

  function reset() {
    Object.assign(draft, emptyFilter());
    Object.assign(applied, emptyFilter());
    page.value = 1;
  }

  return {
    draft,
    applied,
    tableTypeOptions,
    filteredDocuments,
    total,
    pagedDocuments,
    apply,
    reset,
  };
}
