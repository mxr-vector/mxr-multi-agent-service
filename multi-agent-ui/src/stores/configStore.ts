/**
 * 全局运行参数 store：白名单标量参数（RAG_* / CHAT_* / DRAWIO_EMBED_URL）的
 * 前端唯一状态源（与 dictStore 同构）。
 *
 * ensureLoaded 由消费方（如 drawio 编辑器）按需预热，单飞去重；模型配置页
 * 「运行参数」区域展示与保存均经本 store，保存后 loadAll 刷新使各消费方
 * 免刷新拿到新值；登出时由 userStore 调用 reset 清空，下次登录重新拉取。
 */

import { defineStore } from "pinia";
import { ref } from "vue";
import { configApi, type Config } from "@/api/system/config";

/**
 * drawio embed 实例地址参数键：前端 useDrawioEmbed 直接消费该值（读 iframe 地址 +
 * postMessage origin 基准），故前端需知道此键名——这是前端自身的消费契约，
 * 与后端 SCALAR_KEYS 无关。其余运行参数：展示由 is_builtin 驱动、校验由 /scalars
 * 返回的 value_type 数据驱动，前端不再镜像后端白名单键。
 */
export const DRAWIO_EMBED_URL_KEY = "DRAWIO_EMBED_URL";

export const useConfigStore = defineStore("config", () => {
  /** 参数键 -> 参数行（接口序，后端按 is_builtin + created_at 升序返回） */
  const configMap = ref<Record<string, Config>>({});
  /** 是否已完成一次加载（含失败降级），避免重复拉取 */
  const loaded = ref(false);

  /** 拉取全部白名单标量运行参数；失败保持空表但标记已加载 */
  async function loadAll() {
    try {
      const res = await configApi.listScalars();
      const map: Record<string, Config> = {};
      (res.data ?? []).forEach((c) => {
        map[c.key] = c;
      });
      configMap.value = map;
    } catch {
      configMap.value = {};
    } finally {
      loaded.value = true;
    }
  }

  /** ensureLoaded 的在途请求：并发调用共享同一次加载（单飞去重） */
  let loadPromise: Promise<void> | null = null;

  /** 确保参数已加载：已加载直接返回，在途则共享，否则触发 loadAll */
  async function ensureLoaded() {
    if (loaded.value) return;
    if (!loadPromise) {
      loadPromise = loadAll().finally(() => {
        loadPromise = null;
      });
    }
    return loadPromise;
  }

  /** 白名单参数列表（接口序），供运行参数表格渲染 */
  function list(): Config[] {
    return Object.values(configMap.value);
  }

  /** 按参数键取值（供业务侧运行时读取，如 drawio embed），未加载/未知键返回空串 */
  function getValue(key: string): string {
    return configMap.value[key]?.value ?? "";
  }

  /** 清空参数（登出时调用），下次登录重新拉取 */
  function reset() {
    configMap.value = {};
    loaded.value = false;
  }

  return { configMap, loaded, loadAll, ensureLoaded, list, getValue, reset };
});
