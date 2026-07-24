import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";

// 模板内使用的 Element Plus 组件（el-dialog / el-select 等）由 unplugin 按需自动注入样式；
// 但 ElMessage / ElMessageBox / ElLoading 属于脚本内命令式调用的组件，不会触发按需样式注入，
// 若不显式引入其样式，删除等二次确认弹窗会出现“无样式/错位”的问题，故在此统一补齐。
import "element-plus/theme-chalk/el-overlay.css";
import "element-plus/theme-chalk/el-message-box.css";
import "element-plus/theme-chalk/el-message.css";
import "element-plus/theme-chalk/el-loading.css";

// 列表页通用布局工具类（.list-page / .list-panel / .list-scroll / .list-footer）
import "@/assets/styles/layout.css";

createApp(App).use(router).mount("#app");
