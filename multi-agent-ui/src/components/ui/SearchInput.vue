<script setup lang="ts">
// 各管理页共用的搜索框：统一图标、清空按钮与聚焦样式。
withDefaults(defineProps<{ placeholder?: string }>(), { placeholder: "搜索" });
const model = defineModel<string>({ default: "" });
</script>

<template>
  <div class="search-input">
    <svg
      class="search-input__icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
    <input
      v-model="model"
      class="search-input__field"
      type="search"
      :placeholder="placeholder"
      :aria-label="placeholder"
    />
    <button
      v-if="model"
      class="search-input__clear"
      type="button"
      aria-label="清空搜索"
      @click="model = ''"
    >
      ×
    </button>
  </div>
</template>

<style scoped>
.search-input {
  position: relative;
  display: flex;
  width: 240px;
  max-width: 100%;
  align-items: center;
}

.search-input__icon {
  position: absolute;
  left: 11px;
  width: 16px;
  height: 16px;
  color: #9aa4bd;
  pointer-events: none;
}

.search-input__field {
  width: 100%;
  height: 38px;
  padding: 0 32px 0 34px;
  border: 1px solid #dfe4ef;
  border-radius: 9px;
  outline: 0;
  color: #34405a;
  font-size: 13px;
  background: #fff;
  transition:
    border-color 150ms ease,
    box-shadow 150ms ease;
}

.search-input__field::placeholder {
  color: #aab2c6;
}

.search-input__field:focus {
  border-color: #8091e8;
  box-shadow: 0 0 0 3px rgb(128 145 232 / 12%);
}

/* 隐藏浏览器原生的 search 清除按钮，使用自定义的 */
.search-input__field::-webkit-search-cancel-button {
  display: none;
}

.search-input__clear {
  position: absolute;
  right: 8px;
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border: 0;
  border-radius: 50%;
  color: #8b95b1;
  background: #eef1f8;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 150ms ease,
    color 150ms ease;
}

.search-input__clear:hover {
  color: #4c5670;
  background: #e2e7f2;
}

@media (max-width: 720px) {
  .search-input {
    width: 100%;
  }
}
</style>
