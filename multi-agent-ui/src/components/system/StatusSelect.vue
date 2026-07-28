<script setup lang="ts">
// 启用/停用下拉：各表单弹窗「状态」字段共用，选项来自全局词典（status 类型）
import { computed } from "vue";
import { useDictStore } from "@/stores/dictStore";

const model = defineModel<string>({ default: "active" });

const dictStore = useDictStore();
dictStore.ensureLoaded();

const options = computed(() => dictStore.getOptions("status"));
</script>

<template>
    <el-select v-model="model" style="width: 100%">
        <el-option v-for="opt in options" :key="opt.value" :label="opt.label" :value="opt.value" />
    </el-select>
</template>
