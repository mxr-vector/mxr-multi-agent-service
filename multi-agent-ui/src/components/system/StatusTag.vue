<script setup lang="ts">
// 启用/停用状态标签：系统管理各列表页状态列共用，文案来自全局词典（status 类型）
import { computed } from "vue";
import { useDictStore } from "@/stores/dictStore";

const props = defineProps<{ status: string }>();

const dictStore = useDictStore();
dictStore.ensureLoaded();

const label = computed(() => dictStore.getLabel("status", props.status));
</script>

<template>
    <el-tag :type="status === 'active' ? 'success' : 'info'" size="small">
        {{ label }}
    </el-tag>
</template>
