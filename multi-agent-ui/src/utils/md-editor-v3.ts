import { MdEditor, MdPreview, NormalToolbar } from "md-editor-v3";
import "md-editor-v3/lib/style.css";

export { MdEditor, MdPreview, NormalToolbar };

/** 兼容别名（适配用户/历史命名惯例） */
export const VMdEditor = MdEditor;

/** MdEditor / MdPreview 默认配置 */
export const MD_PREVIEW_DEFAULTS = {
  /** 预览主题 */
  previewTheme: "default" as const,
  /** 代码主题 */
  codeTheme: "atom" as const,
  /** 是否显示代码行号 */
  showCodeRowNumber: true,
};
