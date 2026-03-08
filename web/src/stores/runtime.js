import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { runtimeApi } from '@/apis/runtime_api'
import { parseToShanghai } from '@/utils/time'

const toRun = (raw = {}) => ({
  run_id: raw.run_id || '',
  thread_id: raw.thread_id || '',
  request_id: raw.request_id || '',
  idempotency_key: raw.idempotency_key || '',
  mode: raw.mode || 'hybrid',
  agent_id: raw.agent_id || '',
  status: raw.status || 'queued',
  attempt: raw.attempt ?? 0,
  max_attempts: raw.max_attempts ?? 1,
  cancel_requested: !!raw.cancel_requested,
  paused_reason: raw.paused_reason || '',
  created_by: raw.created_by,
  created_at: raw.created_at,
  updated_at: raw.updated_at,
  started_at: raw.started_at,
  finished_at: raw.finished_at,
  input_payload: raw.input_payload || {},
  output_payload: raw.output_payload,
  error_payload: raw.error_payload
})

const toEvent = (raw = {}) => ({
  event_id: raw.event_id,
  run_id: raw.run_id,
  seq: raw.seq ?? 0,
  event_type: raw.event_type || '',
  actor_type: raw.actor_type || '',
  actor_name: raw.actor_name || '',
  span_id: raw.span_id || '',
  parent_span_id: raw.parent_span_id || '',
  event_ts: raw.event_ts,
  event_payload: raw.event_payload || {}
})

export const useRuntimeStore = defineStore('runtime', () => {
  const runs = ref([])
  const selectedRun = ref(null)
  const runEvents = ref([])
  const eventTypeCatalog = ref([])
  const eventCatalogRunId = ref('')
  const loadingRuns = ref(false)
  const loadingEvents = ref(false)
  const polling = ref(false)
  const eventsCursor = ref(0)
  const filters = ref({ status: undefined })
  const eventFilters = ref({ eventType: undefined, actorType: undefined, actorName: '' })
  let timer = null

  const sortedRuns = computed(() =>
    [...runs.value].sort((a, b) => {
      const timeA = parseToShanghai(a.created_at)
      const timeB = parseToShanghai(b.created_at)
      if (!timeA && !timeB) return 0
      if (!timeA) return 1
      if (!timeB) return -1
      return timeB.valueOf() - timeA.valueOf()
    })
  )

  async function loadRuns(extraParams = {}) {
    loadingRuns.value = true
    try {
      const response = await runtimeApi.fetchRuns({ ...filters.value, ...extraParams, limit: 200 })
      runs.value = (response?.runs || []).map(toRun)
    } catch (error) {
      console.error('加载运行列表失败', error)
      message.error(error?.message || '加载运行列表失败')
    } finally {
      loadingRuns.value = false
    }
  }

  async function loadRunDetail(runId) {
    if (!runId) return
    try {
      const response = await runtimeApi.fetchRunDetail(runId)
      selectedRun.value = toRun(response || {})
    } catch (error) {
      console.error(`加载运行 ${runId} 详情失败`, error)
      message.error(error?.message || '加载运行详情失败')
    }
  }

  async function loadRunEvents(runId, { reset = false } = {}) {
    if (!runId) return
    loadingEvents.value = true
    try {
      if (reset) {
        eventsCursor.value = 0
      }
      if (eventCatalogRunId.value !== runId) {
        eventCatalogRunId.value = runId
        eventTypeCatalog.value = []
      }
      const actorName = String(eventFilters.value.actorName || '').trim()
      const response = await runtimeApi.fetchRunEvents(runId, {
        cursor: eventsCursor.value,
        limit: 300,
        event_type: eventFilters.value.eventType,
        actor_type: eventFilters.value.actorType,
        actor_name: actorName || undefined
      })
      const incoming = (response?.items || []).map(toEvent)
      const eventTypeSet = new Set(eventTypeCatalog.value)
      for (const item of incoming) {
        if (item.event_type) eventTypeSet.add(item.event_type)
      }
      eventTypeCatalog.value = Array.from(eventTypeSet).sort()
      if (reset) {
        runEvents.value = incoming
      } else {
        const seen = new Set(runEvents.value.map((item) => `${item.run_id}:${item.seq}`))
        for (const item of incoming) {
          const key = `${item.run_id}:${item.seq}`
          if (!seen.has(key)) {
            runEvents.value.push(item)
            seen.add(key)
          }
        }
      }
      eventsCursor.value = response?.next_cursor || eventsCursor.value
    } catch (error) {
      console.error(`加载运行 ${runId} 事件失败`, error)
      message.error(error?.message || '加载运行事件失败')
    } finally {
      loadingEvents.value = false
    }
  }

  async function selectRun(runId) {
    await loadRunDetail(runId)
    await loadRunEvents(runId, { reset: true })
  }

  async function setEventFilters(runId, nextFilters = {}) {
    eventFilters.value = {
      ...eventFilters.value,
      ...nextFilters
    }
    if (runId) {
      await loadRunEvents(runId, { reset: true })
    }
  }

  async function resetEventFilters(runId) {
    eventFilters.value = { eventType: undefined, actorType: undefined, actorName: '' }
    if (runId) {
      await loadRunEvents(runId, { reset: true })
    }
  }

  async function cancelRun(runId) {
    if (!runId) return
    try {
      await runtimeApi.cancelRun(runId)
      message.success('已请求取消运行')
      await Promise.all([loadRunDetail(runId), loadRunEvents(runId, { reset: true }), loadRuns()])
    } catch (error) {
      console.error(`取消运行 ${runId} 失败`, error)
      message.error(error?.message || '取消运行失败')
    }
  }

  async function resumeRun(runId) {
    if (!runId) return
    try {
      await runtimeApi.resumeRun(runId, {})
      message.success('已请求恢复运行')
      await Promise.all([loadRunDetail(runId), loadRunEvents(runId, { reset: true }), loadRuns()])
    } catch (error) {
      console.error(`恢复运行 ${runId} 失败`, error)
      message.error(error?.message || '恢复运行失败')
    }
  }

  async function retryRun(runId) {
    if (!runId) return
    try {
      await runtimeApi.retryRun(runId, {})
      message.success('已请求重试运行')
      await Promise.all([loadRunDetail(runId), loadRunEvents(runId, { reset: true }), loadRuns()])
    } catch (error) {
      console.error(`重试运行 ${runId} 失败`, error)
      message.error(error?.message || '重试运行失败')
    }
  }

  function startPolling(interval = 5000) {
    if (timer) return
    polling.value = true
    timer = setInterval(async () => {
      await loadRuns()
      if (selectedRun.value?.run_id) {
        await Promise.all([loadRunDetail(selectedRun.value.run_id), loadRunEvents(selectedRun.value.run_id)])
      }
    }, interval)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    polling.value = false
  }

  function reset() {
    stopPolling()
    runs.value = []
    selectedRun.value = null
    runEvents.value = []
    eventTypeCatalog.value = []
    eventCatalogRunId.value = ''
    eventFilters.value = { eventType: undefined, actorType: undefined, actorName: '' }
    eventsCursor.value = 0
  }

  return {
    runs,
    sortedRuns,
    selectedRun,
    runEvents,
    eventTypeCatalog,
    loadingRuns,
    loadingEvents,
    polling,
    filters,
    eventFilters,
    loadRuns,
    loadRunDetail,
    loadRunEvents,
    selectRun,
    setEventFilters,
    resetEventFilters,
    cancelRun,
    resumeRun,
    retryRun,
    startPolling,
    stopPolling,
    reset
  }
})
