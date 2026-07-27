import { ref, watch, onBeforeUnmount, type Ref } from "vue";

/**
 * 各管理页共用的搜索关键词防抖：
 * 返回关键词 ref，输入停顿 delay 毫秒后触发回调（回调内自行处理回页 1 与重载）。
 */
export function useDebouncedKeyword(onSearch: () => void, delay = 300): Ref<string> {
  const keyword = ref("");
  let timer: ReturnType<typeof setTimeout> | undefined;

  watch(keyword, () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(onSearch, delay);
  });

  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer);
  });

  return keyword;
}
