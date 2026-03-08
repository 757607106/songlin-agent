<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useRuntimeStore } from '@/stores/runtime'
import { formatFullDateTime, formatRelative } from '@/utils/time'
import HeaderComponent from '@/components/HeaderComponent.vue'

const runtimeStore = useRuntimeStore()
const route = useRoute()
const router = useRouter()
const {
  sortedRuns,
  selectedRun,
  runEvents,
  loadingRuns,
  loadingEvents,
  filters,
  eventFilters,
  eventTypeCatalog
} = storeToRefs(runtimeStore)
const routeRunId = computed(() => {
  const fromParams = String(route.params.runId || '').trim()
  if (fromParams) return fromParams
  return String(route.query.run_id || '').trim()
})

const selectedRunId = computed(() => selectedRun.value?.run_id || '')
const runKeyword = ref('')
const expandedEvents = ref(new Set())
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
    { label: 'Run ID', value: run.run_id || '-', mono: true },
    { label: 'Thread ID', value: run.thread_id || '-', mono: true },
    { label: '请求 ID', value: run.request_id || '-', mono: true },
    { label: '当前状态', value: run.status || '-', isStatus: true },
    { label: '执行模式', value: run.mode || '-' },
    { label: '尝试次数', value: `${run.attempt ?? 0} / ${run.max_attempts ?? 1}` },
    { label: '创建时间', value: formatFullDateTime(run.created_at) },
    { label: '更新时间', value: formatFullDateTime(run.updated_at) }
  ]
})

const filteredRuns = computed(() => {
  const keyword = String(runKeyword.value || '')
    .trim()
    .toLowerCase()
  if (!keyword) return sortedRuns.value
  return sortedRuns.value.filter((run) => {
    const runId = String(run.run_id || '').toLowerCase()
    const agentId = String(run.agent_id || '').toLowerCase()
    const mode = String(run.mode || '').toLowerCase()
    return runId.includes(keyword) || agentId.includes(keyword) || mode.includes(keyword)
  })
})

const eventTypeOptions = computed(() => {
  const values = Array.from(
    new Set([
      ...(eventTypeCatalog.value || []),
      ...(runEvents.value || []).map((event) => event.event_type).filter(Boolean)
    ])
  ).sort()
  return [
    { label: '全部事件', value: undefined },
    ...values.map((item) => ({ label: item, value: item }))
  ]
})

const filteredRunEvents = computed(() => {
  return (runEvents.value || []).filter((event) => {
    if (eventFilters.value.eventType && event.event_type !== eventFilters.value.eventType) {
      return false
    }
    if (eventFilters.value.actorType && event.actor_type !== eventFilters.value.actorType) {
      return false
    }
    const actorNameKeyword = String(eventFilters.value.actorName || '')
      .trim()
      .toLowerCase()
    if (
      actorNameKeyword &&
      !String(event.actor_name || '')
        .toLowerCase()
        .includes(actorNameKeyword)
    ) {
      return false
    }
    return true
  })
})

const rowClassName = (record) => (record.run_id === selectedRunId.value ? 'row-selected' : '')

const hasPayload = (event) => {
  const payload = event.event_payload
  return payload && typeof payload === 'object' && Object.keys(payload).length > 0
}

const togglePayload = (eventKey) => {
  const next = new Set(expandedEvents.value)
  if (next.has(eventKey)) {
    next.delete(eventKey)
  } else {
    next.add(eventKey)
  }
  expandedEvents.value = next
}

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

watch(routeRunId, async (runId) => {
  const normalized = String(runId || '').trim()
  if (!normalized || normalized === selectedRunId.value) return
  await runtimeStore.selectRun(normalized)
})

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
    <HeaderComponent
      title="Runtime 运行中心"
      description="实时查看 Run 状态与事件时间线"
      :loading="loadingRuns"
    >
      <template #actions>
        <a-input
          v-model:value="runKeyword"
          style="width: 220px"
          allow-clear
          placeholder="筛选 Run ID / Agent / 模式"
        />
        <a-select
          :value="filters.status"
          style="width: 140px"
          :options="statusOptions"
          allow-clear
          placeholder="按状态筛选"
          @change="handleStatusFilterChange"
        />
        <a-button type="primary" :loading="loadingRuns" @click="refreshAll">刷新</a-button>
      </template>
    </HeaderComponent>

    <div class="runtime-grid">
      <!-- 左侧：运行列表 -->
      <div class="glass-panel run-list-panel">
        <div class="panel-header">
          <span class="panel-title">运行列表</span>
        </div>
        <div class="panel-body">
          <a-table
            size="small"
            class="custom-table"
            :loading="loadingRuns"
            :columns="tableColumns"
            :data-source="filteredRuns"
            :pagination="{ pageSize: 12, showSizeChanger: false }"
            row-key="run_id"
            :row-class-name="rowClassName"
            :custom-row="
              (record) => ({
                onClick: () => handleSelectRun(record.run_id)
              })
            "
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'run_id'">
                <a-typography-text :strong="record.run_id === selectedRunId">{{
                  record.run_id
                }}</a-typography-text>
              </template>
              <template v-else-if="column.key === 'status'">
                <a-tag :color="statusColorMap[record.status] || 'default'">{{
                  record.status
                }}</a-tag>
              </template>
              <template v-else-if="column.key === 'created_at'">
                <span>{{ formatFullDateTime(record.created_at) }}</span>
              </template>
            </template>
          </a-table>
        </div>
      </div>

      <!-- 右侧：详情 + 事件 -->
      <div class="runtime-detail-stack">
        <!-- 运行详情 -->
        <div class="glass-panel run-detail-panel">
          <div class="panel-header">
            <span class="panel-title">运行详情</span>
            <a-space>
              <a-button size="small" :disabled="!selectedRunId" @click="handleResume"
                >恢复</a-button
              >
              <a-button size="small" :disabled="!selectedRunId" @click="handleRetry">重试</a-button>
              <a-button size="small" danger :disabled="!selectedRunId" @click="handleCancel"
                >取消</a-button
              >
            </a-space>
          </div>
          <div class="panel-body">
            <a-empty v-if="!selectedRun" description="请选择一个运行记录" />
            <div v-else class="detail-grid">
              <div v-for="item in runMeta" :key="item.label" class="info-item">
                <div class="info-label">{{ item.label }}</div>
                <div class="info-value" :class="{ mono: item.mono }">
                  <a-tag
                    v-if="item.isStatus"
                    :color="statusColorMap[item.value] || 'default'"
                    size="small"
                  >
                    {{ item.value }}
                  </a-tag>
                  <template v-else>{{ item.value }}</template>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 事件时间线 -->
        <div class="glass-panel run-events-panel">
          <div class="panel-header">
            <span class="panel-title">事件时间线</span>
            <span class="events-count"
              >{{ filteredRunEvents.length }} / {{ runEvents.length }}</span
            >
          </div>
          <div class="panel-body events-body">
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
                  style="width: 150px"
                  :options="actorTypeOptions"
                  allow-clear
                  placeholder="筛选角色"
                  @change="(value) => updateEventFilters({ actorType: value })"
                />
                <a-input
                  :value="eventFilters.actorName"
                  style="width: 170px"
                  allow-clear
                  placeholder="筛选执行者"
                  @change="(e) => updateEventFilters({ actorName: e.target.value || '' })"
                />
                <a-button size="small" @click="resetEventFilters">重置</a-button>
              </div>
              <a-timeline class="runtime-timeline">
                <a-timeline-item
                  v-for="event in filteredRunEvents"
                  :key="`${event.run_id}:${event.seq}`"
                >
                  <div class="event-card">
                    <div class="event-line">
                      <a-space :size="6" wrap>
                        <a-tag :color="eventTypeColor(event.event_type)" size="small">{{
                          event.event_type
                        }}</a-tag>
                        <a-tag size="small">{{ event.actor_type }}</a-tag>
                        <span class="event-seq">#{{ event.seq }}</span>
                        <span v-if="event.actor_name" class="event-actor">{{
                          event.actor_name
                        }}</span>
                      </a-space>
                      <span class="event-time">
                        {{ formatFullDateTime(event.event_ts) }}
                        <span class="event-relative">({{ formatRelative(event.event_ts) }})</span>
                      </span>
                    </div>
                    <div v-if="hasPayload(event)" class="event-payload-section">
                      <a
                        class="payload-toggle"
                        @click.prevent="togglePayload(`${event.run_id}:${event.seq}`)"
                      >
                        {{
                          expandedEvents.has(`${event.run_id}:${event.seq}`)
                            ? '收起 Payload'
                            : '查看 Payload'
                        }}
                      </a>
                      <pre
                        v-if="expandedEvents.has(`${event.run_id}:${event.seq}`)"
                        class="event-payload"
                        >{{ JSON.stringify(event.event_payload, null, 2) }}</pre
                      >
                    </div>
                  </div>
                </a-timeline-item>
              </a-timeline>
            </a-spin>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style lang="less" scoped>
.runtime-view {
  padding: 24px 30px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.runtime-grid {
  display: grid;
  grid-template-columns: minmax(460px, 46%) 1fr;
  gap: 16px;
  min-height: 0;
  flex: 1 1 auto;
}

// --- Panel 通用样式 ---
.glass-panel {
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 14px 20px;
  border-bottom: 1px solid var(--gray-100);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-900);
}

.panel-body {
  padding: 16px 20px;
  flex: 1;
  overflow: auto;
  min-height: 0;
}

// --- 运行列表 ---
.run-list-panel {
  min-height: 0;
}

:deep(.custom-table) {
  .ant-table-thead > tr > th {
    background: var(--gray-50);
    color: var(--gray-700);
    font-weight: 600;
  }

  .ant-table-tbody > tr {
    cursor: pointer;
  }

  .ant-table-tbody > tr.row-selected > td {
    background: var(--main-0) !important;
  }

  .ant-table-tbody > tr.row-selected:hover > td {
    background: var(--main-100) !important;
  }
}

// --- 右侧堆叠 ---
.runtime-detail-stack {
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 16px;
  min-height: 0;
}

// --- 详情面板 ---
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 24px;
}

.info-item {
  .info-label {
    font-size: 12px;
    color: var(--gray-500);
    margin-bottom: 2px;
  }

  .info-value {
    font-size: 13px;
    color: var(--gray-800);
    word-break: break-all;

    &.mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;
    }
  }
}

// --- 事件面板 ---
.run-events-panel {
  min-height: 0;
}

.events-body {
  display: flex;
  flex-direction: column;
}

.events-count {
  color: var(--gray-500);
  font-size: 12px;
}

.events-filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--gray-100);
  margin-bottom: 14px;
  flex-shrink: 0;
}

.runtime-timeline {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
  min-height: 0;
}

.event-card {
  padding: 10px 14px;
  background: var(--gray-0);
  border: 1px solid var(--gray-100);
  border-radius: 8px;
}

.event-line {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.event-time {
  font-size: 12px;
  color: var(--gray-500);
  white-space: nowrap;
  flex-shrink: 0;
}

.event-relative {
  color: var(--gray-400);
}

.event-seq {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;
  font-size: 12px;
  color: var(--gray-600);
}

.event-actor {
  font-size: 12px;
  color: var(--gray-600);
}

.event-payload-section {
  margin-top: 8px;
}

.payload-toggle {
  font-size: 12px;
  color: var(--main-500);
  cursor: pointer;

  &:hover {
    color: var(--main-600);
  }
}

.event-payload {
  margin: 6px 0 0;
  padding: 10px;
  border-radius: 6px;
  border: 1px solid var(--gray-100);
  background: var(--gray-50);
  font-size: 12px;
  line-height: 1.45;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
