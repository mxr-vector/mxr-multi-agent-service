<script setup lang="ts">
// Element Plus 全局默认本地化为中文（影响分页、日期选择器、MessageBox 等内置文案）
import zhCn from "element-plus/es/locale/lang/zh-cn";
import AiChat from "./components/AiChatPanel/AiChat.vue";
import { computed, onMounted } from "vue";
import { useRoute } from "vue-router";

const locale = zhCn;
const router = useRoute();

const aiChatHiddenPaths = ["/login", "/register"];
const showAiChat = computed(
  () => !router.meta?.hideAiChat && !aiChatHiddenPaths.includes(router.path)
);

onMounted(() => {});
</script>

<template>
  <!-- ai聊天组件 -->
  <AiChat v-if="showAiChat" />
  <!-- 路由组件 -->
  <el-config-provider :locale="locale">
    <RouterView />
  </el-config-provider>
</template>

<style>
:root {
  color: #182230;
  background: #f7f8fc;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}
* {
  box-sizing: border-box;
}
body {
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
}
button,
input {
  font: inherit;
}
button {
  cursor: pointer;
}
</style>
