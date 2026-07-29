<template>
  <!-- 各管理页共用的主操作按钮（如「＋ 新建xx」），点击等事件经 attrs 透传 -->
  <button class="primary-button" type="button">
    <slot />
  </button>
</template>

<style scoped>
.primary-button {
  min-height: 40px;
  padding: 0 16px;
  border: 0;
  border-radius: 9px;
  color: #fff;
  background: #526ae2;
  box-shadow: 0 8px 16px rgb(82 106 226 / 18%);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.primary-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
