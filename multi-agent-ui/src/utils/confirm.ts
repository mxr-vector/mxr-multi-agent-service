/** 危险操作（删除等）的统一二次确认封装，保证各管理页交互与样式一致。 */
import { ElMessageBox, type ElMessageBoxOptions } from "element-plus";

/**
 * 弹出“危险操作”确认框。
 * - 确认返回 true；取消或关闭返回 false（不抛异常，业务侧无需再包 try/catch）。
 * - 确认按钮统一使用 danger 样式，突出破坏性动作。
 */
export async function confirmDanger(
  message: string,
  title = "删除确认",
  options: ElMessageBoxOptions = {}
): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      confirmButtonClass: "el-button--danger",
      ...options,
    });
    return true;
  } catch {
    return false;
  }
}
