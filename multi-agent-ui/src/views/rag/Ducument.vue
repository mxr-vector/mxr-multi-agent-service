<script setup lang="ts">
// 电子资料维护页：完整逻辑（部门/文件夹树、筛选、卡片网格、分页、上传、文件夹管理）
// 均内聚在 DocumentTable 组件中，本视图仅作为路由薄壳。
import DocumentTable from "@/components/rag/DocumentTable.vue";
</script>

<template>
  <DocumentTable />
</template>
