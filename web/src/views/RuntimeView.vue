<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useRuntimeStore } from '@/stores/runtime'
import { formatFullDateTime, formatRelative } from '@/utils/time'

const runtimeStore = useRuntimeStore()
const route = useRoute()
const router = useRouter()
const { sortedRuns, selectedRun, runEvents, loadingRuns, loadingEvents, filters, eventFilters, eventTypeCatalog } =
  storeToRefs(runtimeStore)
const routeRunId = computed(() => {
  const fromParams = String(route.params.runId || '').trim()
  if (fromParams) return fromParams
  return String(route.query.run_id || '').trim()
})

const selectedRunId = computed(() => selectedRun.value?.run_id || '')
const runKeyword = ref('')
const statusOptions = [
  { label: '全部状态', value: undefined },
  { label: '排队', value: 'queued' },
  { label: '运行中', value: 'running' },
  { label: '暂停中', value: 'paused' },
  { label: '恢复中', value: 'resuming' },
  { label: '已完成', value: 'completed' },
  { label: '已失败', value: 'failed' },
  { label: '已取消', value: 'cancelled' }
]

const tableColumns = [
  { title: 'Run ID', dataIndex: 'run_id', key: 'run_id', width: 230, ellipsis: true },
  { title: 'Agent', dataIndex: 'agent_id', key: 'agent_id', width: 120, ellipsis: true },
  { title: '模式', dataIndex: 'mode', key: 'mode', width: 90 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170 }
]

const statusColorMap = reactive({
  queued: 'default',
  dispatching: 'processing',
  running: 'processing',
  pausing: 'warning',
  paused: 'warning',
  resuming: 'processing',
  completed: 'success',
  failed: 'error',
  cancelled: 'error'
})

const actorTypeOptions = [
  { label: '全部角色', value: undefined },
  { label: 'system', value: 'system' },
  { label: 'user', value: 'user' },
  { label: 'supervisor', value: 'supervisor' },
  { label: 'subagent', value: 'subagent' },
  { label: 'tool', value: 'tool' }
]

const eventTypeColor = (eventType) => {
  if (eventType.startsWith('run.')) return 'blue'
  if (eventType.startsWith('team.execution.')) return 'green'
  if (eventType.startsWith('tool.')) return 'purple'
  if (eventType.startsWith('agent.')) return 'cyan'
  if (eventType.startsWith('supervisor.')) return 'geekblue'
  if (eventType.startsWith('subagent.')) return 'gold'
  return 'default'
}

const runMeta = computed(() => {
  if (!selectedRun.value) return []
  const run = selectedRun.value
  return [
    { label: 'Run ID', value: run.run_id || '-' },
    { label: 'Thread ID', value: run.thread_id || '-' },
    { label: '请求 ID', value: run.request_id || '-' },
    { label: '当前状态', value: run.status || '-' },
    { label: '执行模式', value: run.mode || '-' },
    { label: '尝试次数', value: `${run.attempt ?? 0} / ${run.max_attempts ?? 1}` },
    { label: '创建时间', value: formatFullDateTime(run.created_at) },
    { label: '更新时间', value: formatFullDateTime(run.updated_at) }
  ]
})

const filteredRuns = computed(() => {
  const keyword = String(runKeyword.value || '').trim().toLowerCase()
  if (!keyword) return sortedRuns.value
  return sortedRuns.value.filter((run) => {
    const runId = String(run.run_id || '').toLowerCase()
    const agentId = String(run.agent_id || '').toLowerCase()
    const mode = String(run.mode || '').toLowerCase()
    return runId.includes(keyword) || agentId.includes(keyword) || mode.includes(keyword)
  })
})

const eventTypeOptions = computed(() => {
  const values = Array.from(new Set([...(eventTypeCatalog.value || []), ...(runEvents.value || []).map((event) => event.event_type).filter(Boolean)])).sort()
  return [{ label: '全部事件', value: undefined }, ...values.map((item) => ({ label: item, value: item }))]
})

const filteredRunEvents = computed(() => {
  return (runEvents.value || []).filter((event) => {
    if (eventFilters.value.eventType && event.event_type !== eventFilters.value.eventType) {
      return false
    }
    if (eventFilters.value.actorType && event.actor_type !== eventFilters.value.actorType) {
      return false
    }
    const actorNameKeyword = String(eventFilters.value.actorName || '').trim().toLowerCase()
    if (actorNameKeyword && !String(event.actor_name || '').toLowerCase().includes(actorNameKeyword)) {
      return false
    }
    return true
  })
})

const refreshAll = async () => {
  await runtimeStore.loadRuns()
  if (routeRunId.value) {
    await runtimeStore.selectRun(routeRunId.value)
    return
  }
  if (!selectedRunId.value && sortedRuns.value.length > 0) {
    await runtimeStore.selectRun(sortedRuns.value[0].run_id)
    return
  }
  if (selectedRunId.value) {
    await runtimeStore.selectRun(selectedRunId.value)
  }
}

const handleSelectRun = async (runId) => {
  await router.replace({ name: 'RuntimeComp', params: { runId } })
  await runtimeStore.selectRun(runId)
}

const handleStatusFilterChange = async (status) => {
  filters.value = { ...filters.value, status }
  await refreshAll()
}

const updateEventFilters = async (patch) => {
  await runtimeStore.setEventFilters(selectedRunId.value, patch)
}

const resetEventFilters = async () => {
  await runtimeStore.resetEventFilters(selectedRunId.value)
}

const handleCancel = async () => {
  if (!selectedRunId.value) return
  await runtimeStore.cancelRun(selectedRunId.value)
}

const handleResume = async () => {
  if (!selectedRunId.value) return
  await runtimeStore.resumeRun(selectedRunId.value)
}

const handleRetry = async () => {
  if (!selectedRunId.value) return
  await runtimeStore.retryRun(selectedRunId.value)
}

watch(
  () => filteredRuns.value.length,
  async (length) => {
    if (length > 0 && !selectedRunId.value) {
      await runtimeStore.selectRun(filteredRuns.value[0].run_id)
    }
  }
)

watch(
  routeRunId,
  async (runId) => {
    const normalized = String(runId || '').trim()
    if (!normalized || normalized === selectedRunId.value) return
    await runtimeStore.selectRun(normalized)
  }
)

onMounted(async () => {
  await refreshAll()
  runtimeStore.startPolling(5000)
})

onUnmounted(() => {
  runtimeStore.stopPolling()
})
</script>

<template>
  <div class="runtime-view layout-container">
    <div class="runtime-header">
      <div class="header-left">
        <h2>Runtime 运行中心</h2>
        <span>实时查看 Run 状态与事件时间线</span>
      </div>
      <div class="header-actions">
        <a-input
          v-model:value="runKeyword"
          style="width: 230px"
          allow-clear
          placeholder="筛选 Run ID / Agent / 模式"
        />
        <a-select
          :value="filters.status"
          style="width: 150px"
          :options="statusOptions"
          allow-clear
          placeholder="按状态筛选"
          @change="handleStatusFilterChange"
        />
        <a-button type="primary" :loading="loadingRuns" @click="refreshAll">刷新</a-button>
      </div>
    </div>

    <div class="runtime-grid">
      <a-card class="runtime-list-card" :bordered="false">
        <template #title>运行列表</template>
        <a-table
          size="small"
          :loading="loadingRuns"
          :columns="tableColumns"
          :data-source="filteredRuns"
          :pagination="{ pageSize: 12, showSizeChanger: false }"
          row-key="run_id"
          :custom-row="
            (record) => ({
              onClick: () => handleSelectRun(record.run_id)
            })
          "
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'run_id'">
              <a-typography-text :strong="record.run_id === selectedRunId">{{ record.run_id }}</a-typography-text>
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag :color="statusColorMap[record.status] || 'default'">{{ record.status }}</a-tag>
            </template>
            <template v-else-if="column.key === 'created_at'">
              <span>{{ formatFullDateTime(record.created_at) }}</span>
            </template>
          </template>
        </a-table>
      </a-card>

      <div class="runtime-detail-stack">
        <a-card class="runtime-detail-card" :bordered="false">
          <template #title>运行详情</template>
          <template #extra>
            <a-space>
              <a-button size="small" :disabled="!selectedRunId" @click="handleResume">恢复</a-button>
              <a-button size="small" :disabled="!selectedRunId" @click="handleRetry">重试</a-button>
              <a-button size="small" danger :disabled="!selectedRunId" @click="handleCancel">取消</a-button>
            </a-space>
          </template>
          <a-empty v-if="!selectedRun" description="请选择一个运行记录" />
          <a-descriptions v-else size="small" :column="2" bordered>
            <a-descriptions-item v-for="item in runMeta" :key="item.label" :label="item.label">
              {{ item.value }}
            </a-descriptions-item>
          </a-descriptions>
        </a-card>

        <a-card class="runtime-events-card" :bordered="false">
          <template #title>事件时间线</template>
          <template #extra>
            <span class="events-count">筛选后 {{ filteredRunEvents.length }} / 总计 {{ runEvents.length }}</span>
          </template>
          <a-empty v-if="!selectedRunId" description="请选择运行记录后查看事件" />
          <a-spin v-else :spinning="loadingEvents">
            <div class="events-filter-bar">
              <a-select
                :value="eventFilters.eventType"
                style="width: 220px"
                :options="eventTypeOptions"
                allow-clear
                placeholder="筛选事件类型"
                @change="(value) => updateEventFilters({ eventType: value })"
              />
              <a-select
                :value="eventFilters.actorType"
                style="width: 160px"
                :options="actorTypeOptions"
                allow-clear
                placeholder="筛选角色"
                @change="(value) => updateEventFilters({ actorType: value })"
              />
              <a-input
                :value="eventFilters.actorName"
                style="width: 180px"
                allow-clear
                placeholder="筛选执行者"
                @change="(e) => updateEventFilters({ actorName: e.target.value || '' })"
              />
              <a-button size="small" @click="resetEventFilters">重置筛选</a-button>
            </div>
            <a-timeline class="runtime-timeline">
              <a-timeline-item v-for="event in filteredRunEvents" :key="`${event.run_id}:${event.seq}`">
                <div class="event-line">
                  <a-space :size="8">
                    <a-tag :color="eventTypeColor(event.event_type)">{{ event.event_type }}</a-tag>
                    <a-tag>{{ event.actor_type }}</a-tag>
                    <span class="event-seq">#{{ event.seq }}</span>
                  </a-space>
                  <span class="event-time">
                    {{ formatFullDateTime(event.event_ts) }}
                    <span class="event-relative">({{ formatRelative(event.event_ts) }})</span>
                  </span>
                </div>
                <div class="event-actor">{{ event.actor_name || '-' }}</div>
                <pre class="event-payload">{{ JSON.stringify(event.event_payload || {}, null, 2) }}</pre>
              </a-timeline-item>
            </a-timeline>
          </a-spin>
        </a-card>
      </div>
    </div>
  </div>
</template>

<style lang="less" scoped>
.runtime-view {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.runtime-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--gray-100);
  border-radius: 14px;
  background: linear-gradient(120deg, var(--main-0) 0%, rgba(24, 144, 255, 0.06) 100%);
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.header-left h2 {
  margin: 0;
  font-size: 20px;
  color: var(--gray-1000);
}

.header-left span {
  color: var(--gray-600);
  font-size: 13px;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.runtime-grid {
  display: grid;
  grid-template-columns: minmax(480px, 48%) 1fr;
  gap: 14px;
  min-height: 0;
  flex: 1 1 auto;
}

.runtime-list-card,
.runtime-detail-card,
.runtime-events-card {
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(9, 30, 66, 0.06);
}

.runtime-detail-stack {
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 14px;
  min-height: 0;
}

.runtime-events-card {
  min-height: 380px;
}

.runtime-timeline {
  max-height: 540px;
  overflow-y: auto;
  padding-right: 6px;
}

.events-filter-bar {
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.event-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.event-time {
  font-size: 12px;
  color: var(--gray-500);
}

.event-relative {
  color: var(--gray-400);
}

.event-seq {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  color: var(--gray-600);
}

.event-actor {
  margin-top: 4px;
  margin-bottom: 6px;
  color: var(--gray-700);
  font-size: 12px;
}

.event-payload {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--gray-100);
  background: var(--gray-50);
  font-size: 12px;
  line-height: 1.45;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.events-count {
  color: var(--gray-500);
  font-size: 12px;
}
</style>
