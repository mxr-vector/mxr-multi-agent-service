import { MdPreview } from "md-editor-v3";
import "md-editor-v3/lib/preview.css";

export { MdPreview };

/** MdPreview 默认配置 */
export const MD_PREVIEW_DEFAULTS = {
  /** 预览主题 */
  previewTheme: "default" as const,
  /** 代码主题 */
  codeTheme: "atom" as const,
  /** 是否显示代码行号 */
  showCodeRowNumber: true,
};
