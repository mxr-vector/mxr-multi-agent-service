/**
 * 全局词典 store：登录后一次性拉取全部字典类型及其字典项的唯一状态源。
 *
 * ensureLoaded 由路由守卫在首次导航时并行预热（失败不阻断导航），组件侧
 * 消费 getOptions/getLabel 并保留原文案回退，词典缺失时不出现空白；
 * 登出时由 userStore 调用 reset 清空，下次登录重新拉取。
 */

import { defineStore } from "pinia";
import { ref } from "vue";
import { dictTypeApi, dictDataApi, type DictData } from "@/api/system/dict";

export const useDictStore = defineStore("dict", () => {
  /** 类型键 -> 启用态字典项列表（sort_order 升序，接口序） */
  const dictMap = ref<Record<string, DictData[]>>({});
  /** 是否已完成一次加载（含失败降级），避免重复拉取 */
  const loaded = ref(false);

  /** 拉取全部启用的字典类型及各自的字典项；失败保持空词典但标记已加载 */
  async function loadAll() {
    try {
      const typeRes = await dictTypeApi.list({ size: 200, status: "active" });
      const types = typeRes.data?.items ?? [];
      const dataLists = await Promise.all(types.map((t) => dictDataApi.listByType(t.type)));
      const map: Record<string, DictData[]> = {};
      types.forEach((t, i) => {
        map[t.type] = (dataLists[i].data ?? []).filter((d) => d.status === "active");
      });
      dictMap.value = map;
    } catch {
      dictMap.value = {};
    } finally {
      loaded.value = true;
    }
  }

  /** ensureLoaded 的在途请求：并发调用共享同一次加载（单飞去重） */
  let loadPromise: Promise<void> | null = null;

  /** 确保词典已加载：已加载直接返回，在途则共享，否则触发 loadAll */
  async function ensureLoaded() {
    if (loaded.value) return;
    if (!loadPromise) {
      loadPromise = loadAll().finally(() => {
        loadPromise = null;
      });
    }
    return loadPromise;
  }

  /** 按类型键取字典项列表（下拉框数据源），未加载/未知类型返回空数组 */
  function getOptions(dictType: string): DictData[] {
    return dictMap.value[dictType] ?? [];
  }

  /** 按类型键 + 存储值取展示文案，未命中回退原始 value */
  function getLabel(dictType: string, value: string): string {
    const hit = dictMap.value[dictType]?.find((d) => d.value === value);
    return hit?.label ?? value;
  }

  /** 清空词典（登出时调用），下次登录重新拉取 */
  function reset() {
    dictMap.value = {};
    loaded.value = false;
  }

  return { dictMap, loaded, loadAll, ensureLoaded, getOptions, getLabel, reset };
});
