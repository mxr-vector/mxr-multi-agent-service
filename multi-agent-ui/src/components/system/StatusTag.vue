<script setup lang="ts">
// 启用/停用状态标签：系统管理各列表页状态列共用
defineProps<{ status: string }>();
</script>

<template>
    <el-tag :type="status === 'active' ? 'success' : 'info'" size="small">
        {{ status === "active" ? "启用" : "停用" }}
    </el-tag>
</template>
