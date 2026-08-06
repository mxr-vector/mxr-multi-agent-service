<script setup lang="ts">
import { computed } from "vue";
import type { RagDocument } from "@/api/rag/document";
import { resolveFileIcon } from "@/utils/fileIcon";
import SvgIcon from "@/components/SvgIcon.vue";
import expiredSoonBadge from "@/assets/images/expiredSoon.svg";
import expiredBadge from "@/assets/images/expired.svg";

const props = defineProps<{
  document: RagDocument;
  /** 该卡片是否正在向量化（禁用重复触发） */
  vectorizing: boolean;
}>();

const emit = defineEmits<{
  (e: "open", doc: RagDocument): void;
  (e: "vectorize", doc: RagDocument): void;
  (e: "view-chunks", doc: RagDocument): void;
  (e: "detail", doc: RagDocument): void;
  (e: "delete", doc: RagDocument): void;
}>();

// 文档 status -> 同步状态圆点（与顶部图例保持一致）
const SYNC_MAP: Record<string, { label: string; cls: string }> = {
  pending: { label: "未同步", cls: "pending" },
  reindexing: { label: "同步中", cls: "syncing" },
  active: { label: "已同步", cls: "synced" },
  failed: { label: "同步失败", cls: "failed" },
};
const sync = computed(() => SYNC_MAP[props.document.status] ?? SYNC_MAP.pending);

const fileIcon = computed(() => resolveFileIcon(props.document));

const title = computed(
  () => props.document.title || props.document.source_uri || props.document.id
);

// 有效期展示：仅取日期部分（YYYY-MM-DD）
const validDate = computed(() => {
  const v = props.document.valid_until;
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? "" : v.slice(0, 10);
});

// 过期状态（依据 valid_until，NULL 表示长期有效）：
// 已过期→右上角「已过期」印章；剩余不足一个月→右上角「即将过期」角标
const expireMs = computed(() => {
  const v = props.document.valid_until;
  if (!v) return null;
  const until = new Date(v).getTime();
  return Number.isNaN(until) ? null : until - Date.now();
});
const isExpired = computed(() => expireMs.value !== null && expireMs.value <= 0);
const expiringSoon = computed(
  () => expireMs.value !== null && expireMs.value > 0 && expireMs.value <= 30 * 24 * 3600 * 1000
);

function handleCommand(command: string) {
  if (command === "vectorize") emit("vectorize", props.document);
  else if (command === "chunks") emit("view-chunks", props.document);
  else if (command === "detail") emit("detail", props.document);
  else if (command === "delete") emit("delete", props.document);
}
</script>

<template>
  <article
    class="doc-card"
    :class="{ expiring: expiringSoon, expired: isExpired }"
    @click="emit('open', document)"
  >
    <!-- 过期徽标：已过期优先于即将过期 -->
    <img v-if="isExpired" class="expired-stamp" :src="expiredBadge" alt="已过期" />
    <img v-else-if="expiringSoon" class="expiring-corner" :src="expiredSoonBadge" alt="即将过期" />

    <!-- 同步状态圆点：左上角 -->
    <span class="sync-dot" :class="sync.cls" :title="sync.label"></span>

    <div class="icon-wrap">
      <SvgIcon :name="fileIcon.name" :colored="fileIcon.colored" :size="46" />
    </div>

    <h3 class="doc-title" :title="title">{{ title }}</h3>

    <div class="doc-foot" @click.stop>
      <span class="doc-date">{{ validDate }}</span>
      <el-dropdown trigger="click" @command="handleCommand">
        <button type="button" class="more-btn" aria-label="更多操作">···</button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="vectorize" :disabled="vectorizing">
              {{ vectorizing ? "处理中…" : "向量化" }}
            </el-dropdown-item>
            <el-dropdown-item command="chunks">查看分块</el-dropdown-item>
            <el-dropdown-item command="detail">详情</el-dropdown-item>
            <!-- 同步中禁删：后台向量化作业未结束，后端也会拒绝 -->
            <el-dropdown-item
              command="delete"
              divided
              :disabled="vectorizing || document.status === 'reindexing'"
            >
              <span class="danger-item">删除</span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </article>
</template>

<style scoped>
.doc-card {
  position: relative;
  display: flex;
  width: 150px;
  height: 168px;
  flex-direction: column;
  align-items: center;
  padding: 16px 12px 8px;
  overflow: hidden;
  border: 1px solid #e8ebf2;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 4px 12px rgb(43 56 86 / 3%);
  cursor: pointer;
  transition:
    border-color 150ms ease,
    box-shadow 150ms ease,
    transform 150ms ease;
}

.doc-card:hover {
  border-color: #d3dbf5;
  box-shadow: 0 10px 22px rgb(43 56 86 / 8%);
  transform: translateY(-2px);
}

/* 同步状态圆点 */
.sync-dot {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c2c9d6;
}

.sync-dot.pending {
  background: #c2c9d6;
}

.sync-dot.syncing {
  background: #e6a23c;
}

.sync-dot.synced {
  background: #3fa77b;
}

.sync-dot.failed {
  background: #e0637a;
}

/* 即将过期角标：右上角斜向色带图（图内自带文案与配色） */
.expiring-corner {
  position: absolute;
  top: 0;
  right: 0;
  width: 44px;
  height: 44px;
  pointer-events: none;
}

/* 已过期印章：右上角斜置，半透明不遮挡文档图标 */
.expired-stamp {
  position: absolute;
  top: 14px;
  right: 4px;
  width: 72px;
  opacity: 0.85;
  transform: rotate(8deg);
  pointer-events: none;
}

/* 已过期整卡置灰，与印章叠加强化失效感 */
.doc-card.expired .icon-wrap,
.doc-card.expired .doc-title {
  opacity: 0.55;
}

.icon-wrap {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 56px;
  height: 56px;
  margin-top: 8px;
  color: #8993a5;
}

.doc-title {
  display: -webkit-box;
  width: 100%;
  margin: 12px 0 0;
  overflow: hidden;
  color: #3a465c;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
  text-align: center;
  text-overflow: ellipsis;
  line-clamp: 2;
  -webkit-box-orient: vertical;
}

.doc-foot {
  display: flex;
  width: 100%;
  height: 22px;
  margin-top: auto;
  align-items: center;
  justify-content: space-between;
}

.doc-date {
  color: #9aa3b5;
  font-size: 11px;
}

.more-btn {
  padding: 0 4px;
  border: 0;
  color: #9aa3b5;
  background: transparent;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  line-height: 1;
  cursor: pointer;
  transition: color 150ms ease;
}

.more-btn:hover {
  color: #526ae2;
}

.danger-item {
  color: #e0637a;
}
</style>
