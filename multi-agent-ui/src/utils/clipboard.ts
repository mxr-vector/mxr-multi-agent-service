/**
 * 剪贴板文本复制工具（兼容非安全上下文 HTTP / IP 访问 / 旧版浏览器）
 */

/**
 * 复制文本到剪贴板。
 * 优先使用现代 Clipboard API；非安全上下文（如内网 HTTP / IP 直连）时自动回落到 textarea + execCommand 兼容方案。
 *
 * @param text 要复制的文本
 * @returns 是否复制成功
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (text == null) return false;

  // 1. 现代安全上下文 (HTTPS 或 localhost) 的 Clipboard API
  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 权限被拒绝或执行异常时，尝试继续走下面的降级方案
    }
  }

  // 2. 传统降级方案：创建不可见 textarea 选中后执行 document.execCommand('copy')
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    // 移出可视区域，避免影响页面滚动与布局
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "-9999px";
    textarea.style.opacity = "0";
    textarea.setAttribute("readonly", "");
    document.body.appendChild(textarea);

    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const successful = document.execCommand("copy");
    document.body.removeChild(textarea);
    return successful;
  } catch {
    return false;
  }
}
