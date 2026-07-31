/**
 * 纯前端本地运行参数 store：仅持久化到 localStorage，不经任何后端接口。
 *
 * 与后端白名单标量参数（RAG_* / CHAT_*）一起在模型配置页「运行参数」区域展示，
 * 但保存只写本浏览器；不维护默认值/元信息，未设置时值为空字符串。
 * 新增纯前端参数：定义一个字符串键常量并加入 LOCAL_PARAM_KEYS 即可。
 */

import { defineStore } from "pinia";
import { ref } from "vue";

/** drawio embed 实例地址参数键 */
export const DRAWIO_EMBED_URL_KEY = "DRAWIO_EMBED_URL";

/** 本地参数白名单键列表：新增纯前端参数在此登记字符串常量即可入表 */
const LOCAL_PARAM_KEYS: string[] = [DRAWIO_EMBED_URL_KEY];

/** 本地参数展示结构（与后端 Config 表格列对齐） */
export interface LocalParam {
  key: string;
  name: string;
  value: string;
  remark: string | null;
  updated_at: string | null;
}

const STORAGE_PREFIX = "sys-param:";

interface StoredParam {
  value: string;
  remark: string | null;
  updated_at: string;
}

/** 与后端 updated_at 展示格式对齐：YYYY-MM-DD HH:mm:ss */
function nowText(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 从 localStorage 恢复全部已存参数（解析失败的键忽略） */
function restore(): Record<string, StoredParam> {
  const map: Record<string, StoredParam> = {};
  for (const key of LOCAL_PARAM_KEYS) {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + key);
      if (raw) map[key] = JSON.parse(raw) as StoredParam;
    } catch {
      // 忽略损坏项
    }
  }
  return map;
}

export const useSysParamStore = defineStore("sysParam", () => {
  // 初始化时从 localStorage 恢复本地参数覆盖值
  const stored = ref<Record<string, StoredParam>>(restore());

  /** 列出全部本地参数（本地未存过的项值为空），供运行参数表格渲染 */
  function list(): LocalParam[] {
    return LOCAL_PARAM_KEYS.map((key) => {
      const hit = stored.value[key];
      return {
        key,
        name: key,
        value: hit?.value ?? "",
        remark: hit?.remark ?? null,
        updated_at: hit?.updated_at ?? null,
      };
    });
  }

  /** 按 key 读取本地参数值（供业务侧运行时读取，如 drawio embed） */
  function getValue(key: string): string {
    return stored.value[key]?.value ?? "";
  }

  /** 保存本地参数（写 localStorage + 更新 store，立即生效） */
  function update(key: string, payload: { value: string; remark: string | null }) {
    const next: StoredParam = {
      value: payload.value,
      remark: payload.remark,
      updated_at: nowText(),
    };
    stored.value = { ...stored.value, [key]: next };
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(next));
  }

  return { list, getValue, update };
});
