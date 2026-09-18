<script setup lang="ts">
/**
 * 生成表单：风格/画幅/集数/基调 + 需求输入 + 发送/停止（纯展示，状态由父级持有）。
 */
import { computed } from "vue";
import type { StoryGeneratePayload, StoryStyleVO } from "@/api/story";
import { useDictStore } from "@/stores/dictStore";

const form = defineModel<StoryGeneratePayload>({ required: true });

const props = defineProps<{
  styles: StoryStyleVO[];
  generating: boolean;
}>();

const emit = defineEmits<{
  (e: "send"): void;
  (e: "stop"): void;
}>();

const dictStore = useDictStore();
dictStore.ensureLoaded();

/** 风格专属推荐基调映射表（结合各技能包权威定义，用于下拉高频置顶） */
const STYLE_TONES_MAP: Record<string, string[]> = {
  shangmeiying: ["仙气", "禅意", "史诗", "悲壮", "苍凉", "神性", "诡秘", "诙谐"],
  generic: ["史诗", "空灵", "治愈", "悬疑", "热血", "庄严", "幽默", "科幻"],
  handdrawn: ["温馨", "治愈", "童趣", "幽默", "怀旧", "轻松"],
};

/** 通用基调备选列表（字典离线时的兜底数据） */
const DEFAULT_TONES = [
  "史诗",
  "空灵",
  "治愈",
  "仙气",
  "禅意",
  "悬疑",
  "热血",
  "悲壮",
  "苍凉",
  "庄严",
  "温馨",
  "幽默",
  "神性",
  "诡秘",
  "科幻",
  "童趣",
  "怀旧",
];

/** 当前风格可用画幅（注册表预设；未选风格时为空） */
const aspectOptions = computed(
  () => props.styles.find((s) => s.key === form.value.style_key)?.aspect_ratios ?? []
);

interface ToneOptionItem {
  label: string;
  value: string;
  remark?: string | null;
}

/** 从字典 story_tone 获取基调，按当前选择的风格智能高频置顶 */
const toneOptions = computed<ToneOptionItem[]>(() => {
  const dictItems = dictStore.getOptions("story_tone");
  let items: ToneOptionItem[] = [];

  if (dictItems && dictItems.length > 0) {
    items = dictItems.map((d) => ({
      label: d.label,
      value: d.value,
      remark: d.remark,
    }));
  } else {
    items = DEFAULT_TONES.map((t) => ({ label: t, value: t }));
  }

  // 若当前已选定风格，将该风格推荐的基调优先排在前面
  const preferred = form.value.style_key ? STYLE_TONES_MAP[form.value.style_key] : null;
  if (preferred && preferred.length > 0) {
    const high = items.filter((item) => preferred.includes(item.value));
    const rest = items.filter((item) => !preferred.includes(item.value));
    items = [...high, ...rest];
  }

  // 若用户已填写了不在预设列表中的自定义基调，追加保留展示
  if (form.value.tone && !items.some((item) => item.value === form.value.tone)) {
    items = [{ label: form.value.tone, value: form.value.tone, remark: "自定义" }, ...items];
  }

  return items;
});

/** 切换风格时画幅回落到该风格首选 */
function onStyleChange() {
  if (!aspectOptions.value.includes(form.value.aspect_ratio ?? "")) {
    form.value.aspect_ratio = aspectOptions.value[0] ?? null;
  }
}
</script>

<template>
  <div class="gen-form">
    <div class="form-row">
      <el-select v-model="form.style_key" placeholder="视频风格" size="small" @change="onStyleChange">
        <el-option
          v-for="style in styles"
          :key="style.key"
          :value="style.key"
          :label="style.name"
        />
      </el-select>
      <el-select v-model="form.aspect_ratio" placeholder="画幅" size="small" class="aspect-select">
        <el-option v-for="ratio in aspectOptions" :key="ratio" :value="ratio" :label="ratio" />
      </el-select>
      <el-input-number
        v-model="form.episodes"
        :min="1"
        :max="50"
        size="small"
        controls-position="right"
        placeholder="集数"
        class="episodes-input"
      />
      <el-select
        v-model="form.tone"
        placeholder="基调"
        size="small"
        clearable
        filterable
        allow-create
        default-first-option
        class="tone-select"
      >
        <el-option
          v-for="t in toneOptions"
          :key="t.value"
          :value="t.value"
          :label="t.label"
        >
          <div class="tone-option-item">
            <span>{{ t.label }}</span>
            <span v-if="t.remark" class="tone-option-desc">{{ t.remark }}</span>
          </div>
        </el-option>
      </el-select>
    </div>
    <div class="input-row">
      <el-input
        v-model="form.idea"
        type="textarea"
        :rows="3"
        :disabled="generating"
        placeholder="描述你的故事设定/需求，如题材、主人公、核心冲突…"
      />
    </div>
    <div class="action-row">
      <el-button v-if="!generating" type="primary" size="small" @click="emit('send')">
        生成剧本
      </el-button>
      <el-button v-else type="warning" size="small" @click="emit('stop')">停止生成</el-button>
    </div>
  </div>
</template>

<style scoped>
.gen-form {
  border-top: 1px solid #e5e9f2;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.form-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.form-row > .el-select {
  flex: 1;
  min-width: 96px;
}
.aspect-select {
  min-width: 80px;
  max-width: 88px;
}
.episodes-input {
  width: 92px;
}
.tone-select {
  flex: 1;
  min-width: 88px;
  max-width: 110px;
}
.tone-option-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.tone-option-desc {
  font-size: 11px;
  color: #8c939d;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action-row {
  display: flex;
  justify-content: flex-end;
}
</style>
