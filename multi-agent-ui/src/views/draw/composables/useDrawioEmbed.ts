/**
 * drawio embed 模式 postMessage 协议封装（JSON protocol）。
 *
 * 生命周期：iframe 加载自托管 drawio（地址来自后端运行参数 DRAWIO_EMBED_URL，
 * 在模型配置页「运行参数」中设置）→ 编辑器就绪发
 * {event:'init'} → 宿主发送 load action（drawio XML / xmlpng dataURI / mermaid
 * descriptor）→ 用户编辑 → 宿主按需发 export action 取回 XML 与 xmlpng。
 *
 * 安全：所有入站消息严格校验 event.origin 与 embed 实例源一致 + 消息源为本
 * iframe 的 contentWindow，来源不符一律丢弃（防伪造 save/export 注入）。
 */
import { onBeforeUnmount, ref, type Ref } from "vue";
import { DRAWIO_EMBED_URL_KEY, useConfigStore } from "@/stores/configStore";

/** embed 编辑器 iframe 固定查询串：JSON 协议 + 隐藏全部内置按钮（保存由宿主弹窗驱动） */
const EMBED_QUERY = "?embed=1&proto=json&spin=1&saveAndExit=0&noSaveBtn=1&noExitBtn=1";

/** export 响应（data 为对应格式的 dataURI；xml 为当前图 XML） */
export interface DrawioExportResult {
  format: string;
  data?: string;
  xml?: string;
}

interface UseDrawioEmbedOptions {
  /** 编辑器就绪（收到 init）后的回调：在此发送 load */
  onInit?: () => void;
  /** 图加载完成（load 响应）回调 */
  onLoad?: () => void;
}

/**
 * drawio embed 协议控制器：绑定 iframe ref，提供 load / export 能力。
 * 单编辑器实例、单在途 export 请求的最小实现（够用即简）。
 */
export function useDrawioEmbed(
  iframeRef: Ref<HTMLIFrameElement | null>,
  options: UseDrawioEmbedOptions = {}
) {
  // drawio 实例地址来自全局运行参数 store（模型配置页保存后 store 同步刷新，
  // 这里响应式读取即免刷新生效），首次使用前 ensureLoaded 预热
  const configStore = useConfigStore();
  void configStore.ensureLoaded();

  /** drawio 实例基址（去尾斜杠；同时是 postMessage origin 校验基准） */
  function drawioBase(): string {
    return configStore.getValue(DRAWIO_EMBED_URL_KEY).replace(/\/+$/, "");
  }

  /** embed 编辑器 iframe 地址（基址 + 固定查询串；参数未就绪时为空，加载完成后响应式更新） */
  function embedSrc(): string {
    const base = drawioBase();
    return base ? `${base}/${EMBED_QUERY}` : "";
  }

  /** drawio embed 实例的 origin（如 http://localhost:8080） */
  function drawioOrigin(): string {
    const base = drawioBase();
    return base ? new URL(base).origin : "";
  }

  const ready = ref(false);
  // 在途 export 请求：按 format 关联响应（同一时刻只发起一个）
  const pendingExports = new Map<string, (result: DrawioExportResult) => void>();

  function post(action: Record<string, unknown>) {
    iframeRef.value?.contentWindow?.postMessage(JSON.stringify(action), drawioOrigin());
  }

  /** 加载 drawio XML 或内嵌 XML 的 PNG dataURI */
  function loadXml(xml: string) {
    post({ action: "load", xml, autosave: 0 });
  }

  /** 以 mermaid descriptor 加载（wrap=true 保留 Mermaid 源可再编辑） */
  function loadMermaid(source: string) {
    post({
      action: "load",
      descriptor: { format: "mermaid", data: source, wrap: true },
      sourceMetadata: { key: "mermaidSource", value: source },
    });
  }

  /** 请求导出：format 取 xml / xmlpng / png / svg 等，返回对应响应 */
  function exportDiagram(format: string, timeoutMs = 15000): Promise<DrawioExportResult> {
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        pendingExports.delete(format);
        reject(new Error("drawio 导出超时"));
      }, timeoutMs);
      pendingExports.set(format, (result) => {
        window.clearTimeout(timer);
        resolve(result);
      });
      post({ action: "export", format });
    });
  }

  function handleMessage(event: MessageEvent) {
    // 来源双校验：origin 匹配 embed 实例 + 消息来自本 iframe 窗口
    if (event.origin !== drawioOrigin()) return;
    if (event.source !== iframeRef.value?.contentWindow) return;
    if (typeof event.data !== "string" || !event.data.length) return;

    let msg: any;
    try {
      msg = JSON.parse(event.data);
    } catch {
      return;
    }

    switch (msg.event) {
      case "init":
        ready.value = true;
        options.onInit?.();
        break;
      case "load":
        options.onLoad?.();
        break;
      case "export": {
        const resolver = pendingExports.get(msg.format);
        if (resolver) {
          pendingExports.delete(msg.format);
          resolver({ format: msg.format, data: msg.data, xml: msg.xml });
        }
        break;
      }
      default:
        break;
    }
  }

  window.addEventListener("message", handleMessage);
  onBeforeUnmount(() => {
    window.removeEventListener("message", handleMessage);
    pendingExports.clear();
  });

  /** 编辑器关闭/重开前复位就绪态（iframe 重挂载后等待新 init） */
  function reset() {
    ready.value = false;
    pendingExports.clear();
  }

  return { ready, embedSrc, loadXml, loadMermaid, exportDiagram, reset };
}

/** 把 dataURI（如 xmlpng 导出结果）转为 Blob，供 FormData 上传 */
export function dataUriToBlob(dataUri: string): Blob {
  const [head, body] = dataUri.split(",");
  const mime = head.match(/data:(.*?);/)?.[1] ?? "application/octet-stream";
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mime });
}
