<template>
  <button v-if="runId" type="button" class="runtime-panel" @click="emit('open-run', runId)">
    <span class="runtime-label">Run</span>
    <span class="runtime-id">{{ displayRunId }}</span>
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  runId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['open-run'])

const displayRunId = computed(() => {
  const normalized = String(props.runId || '').trim()
  if (!normalized) return ''
  if (normalized.length <= 16) return normalized
  return `${normalized.slice(0, 12)}...`
})
</script>

<style scoped lang="less">
.runtime-panel {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--main-200);
  background: var(--main-10);
  cursor: pointer;
  transition: all 0.2s ease;
}

.runtime-panel:hover {
  background: var(--main-50);
  border-color: var(--main-300);
}

.runtime-label {
  font-size: 12px;
  color: var(--main-600);
  font-weight: 600;
}

.runtime-id {
  font-size: 12px;
  color: var(--gray-700);
  font-family:
    ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
    monospace;
}
</style>
