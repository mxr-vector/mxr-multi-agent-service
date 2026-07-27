<script setup lang="ts">
// 启用/停用下拉：各表单弹窗「状态」字段共用
const model = defineModel<string>({ default: "active" });
</script>

<template>
    <el-select v-model="model" style="width: 100%">
        <el-option label="启用" value="active" />
        <el-option label="停用" value="disabled" />
    </el-select>
</template>
