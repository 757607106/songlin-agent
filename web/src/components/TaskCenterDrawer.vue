<template>
  <a-drawer
    :open="isOpen"
    :width="620"
    title="任务中心"
    placement="right"
    @close="handleClose"
    class="task-center-drawer"
    :headerStyle="{ borderBottom: '1px solid var(--gray-200)', padding: '20px 24px' }"
    :bodyStyle="{ padding: '0', backgroundColor: 'var(--gray-50)' }"
  >
    <div class="task-center-container">
      <div class="task-header-alert">
        <InfoCircleOutlined class="icon" />
        <p>任务执行成功仅代表流程结束，请查看日志确认业务结果。</p>
      </div>

      <div class="task-toolbar">
        <div class="task-filter-group">
          <a-segmented
            v-model:value="statusFilter"
            :options="taskFilterOptions"
            class="custom-segmented"
          />
        </div>
        <div class="task-toolbar-actions">
          <a-button type="text" @click="handleRefresh" :loading="loadingState" class="refresh-btn">
            <template #icon><ReloadOutlined /></template>
            刷新
          </a-button>
        </div>
      </div>

      <a-alert
        v-if="lastErrorState"
        type="error"
        show-icon
        class="task-error-alert"
        :message="lastErrorState.message || '加载任务信息失败'"
      />

      <div v-if="hasTasks" class="task-list">
        <div
          v-for="task in filteredTasks"
          :key="task.id"
          class="task-card"
          :class="taskCardClasses(task)"
          @click="handleTaskCardClick(task)"
        >
          <div class="task-card-main">
            <div class="task-card-header">
              <div class="header-top">
                <div class="task-type-badge">{{ taskTypeLabel(task.type) }}</div>
                <div class="task-status-badge" :class="task.status">
                  <span class="dot"></span>
                  {{ statusLabel(task.status) }}
                </div>
              </div>
              <div class="task-title" :title="task.name">{{ task.name }}</div>
              <div class="task-meta">
                <span class="id">ID: {{ formatTaskId(task.id) }}</span>
                <span class="separator">•</span>
                <span class="time">{{ formatTime(task.created_at, 'short') }}</span>
                <template v-if="getTaskDuration(task)">
                  <span class="separator">•</span>
                  <span class="duration">耗时 {{ getTaskDuration(task) }}</span>
                </template>
              </div>
            </div>

            <!-- 进度条 -->
            <div v-if="!isTaskCompleted(task)" class="task-progress-wrapper">
              <div class="progress-info">
                <span>执行进度</span>
                <span class="percent">{{ Math.round(task.progress || 0) }}%</span>
              </div>
              <a-progress
                :percent="Math.round(task.progress || 0)"
                :status="progressStatus(task.status)"
                :stroke-width="6"
                :show-info="false"
                strokeColor="var(--primary-500)"
                trailColor="var(--gray-200)"
              />
            </div>

            <!-- 消息/错误提示 -->
            <div v-if="task.message && !isTaskCompleted(task)" class="task-message-box">
              <InfoCircleOutlined class="icon" />
              <span class="text">{{ task.message }}</span>
            </div>
            <div v-if="task.error" class="task-error-box">
              <CloseCircleOutlined class="icon" />
              <span class="text">{{ task.error }}</span>
            </div>
          </div>

          <!-- 底部操作栏 -->
          <div class="task-card-footer">
            <div class="footer-time">
              <template v-if="task.started_at">
                <ClockCircleOutlined class="icon" />
                <span>开始于 {{ formatTime(task.started_at, 'short') }}</span>
              </template>
            </div>
            <div class="footer-actions">
              <a-button type="text" size="small" @click.stop="handleDetail(task.id)">
                详情
              </a-button>
              <a-button
                type="text"
                size="small"
                danger
                v-if="canCancel(task)"
                @click.stop="handleCancel(task.id)"
              >
                取消
              </a-button>
              <a-button
                type="text"
                size="small"
                class="delete-btn"
                v-if="isTaskCompleted(task)"
                @click.stop="handleDelete(task.id, task.name)"
              >
                删除
              </a-button>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="task-empty-state">
        <div class="empty-icon">
          <InboxOutlined />
        </div>
        <div class="empty-title">暂无任务</div>
        <div class="empty-desc">
          当你提交知识库导入或其他后台任务时，会在这里展示实时进度（仅展示最近的 100 个任务）。
        </div>
      </div>
    </div>
  </a-drawer>
</template>

<script setup>
import { computed, h, onBeforeUnmount, watch, ref } from 'vue'
import { Modal } from 'ant-design-vue'
import { useTaskerStore } from '@/stores/tasker'
import { storeToRefs } from 'pinia'
import { formatFullDateTime, formatRelative, parseToShanghai } from '@/utils/time'
import {
  ReloadOutlined,
  InfoCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  InboxOutlined
} from '@ant-design/icons-vue'

const taskerStore = useTaskerStore()
const {
  isDrawerOpen,
  sortedTasks,
  loading,
  lastError,
  activeCount,
  totalCount,
  successCount,
  failedCount
} = storeToRefs(taskerStore)
const isOpen = isDrawerOpen

const tasks = computed(() => sortedTasks.value)
const loadingState = computed(() => Boolean(loading.value))
const lastErrorState = computed(() => lastError.value)
const statusFilter = ref('all')
const inProgressCount = computed(() => activeCount.value || 0)
const completedCount = computed(() => successCount.value || 0)
const failedTaskCount = computed(() => failedCount.value || 0)
const totalTaskCount = computed(() => totalCount.value || 0)
const taskFilterOptions = computed(() => [
  {
    label: () =>
      h('div', { class: 'custom-segment-item' }, [
        h('span', '全部'),
        h('span', { class: 'count-badge' }, totalTaskCount.value)
      ]),
    value: 'all'
  },
  {
    label: () =>
      h('div', { class: 'custom-segment-item' }, [
        h('span', '进行中'),
        h('span', { class: 'count-badge active' }, inProgressCount.value)
      ]),
    value: 'active'
  },
  {
    label: () =>
      h('div', { class: 'custom-segment-item' }, [
        h('span', '已完成'),
        h('span', { class: 'count-badge success' }, completedCount.value)
      ]),
    value: 'success'
  },
  {
    label: () =>
      h('div', { class: 'custom-segment-item' }, [
        h('span', '失败'),
        h('span', { class: 'count-badge error' }, failedTaskCount.value)
      ]),
    value: 'failed'
  }
])

const filteredTasks = computed(() => {
  const list = tasks.value
  switch (statusFilter.value) {
    case 'active':
      return list.filter((task) => ACTIVE_CLASS_STATUSES.has(task.status))
    case 'success':
      return list.filter((task) => task.status === 'success')
    case 'failed':
      return list.filter((task) => FAILED_STATUSES.has(task.status))
    default:
      return list
  }
})

const hasTasks = computed(() => filteredTasks.value.length > 0)

const ACTIVE_CLASS_STATUSES = new Set(['pending', 'queued', 'running'])
const FAILED_STATUSES = new Set(['failed', 'cancelled'])
const TASK_TYPE_LABELS = {
  knowledge_ingest: '知识库导入',
  knowledge_rechunks: '文档重新分块',
  graph_task: '图谱处理',
  agent_job: '智能体任务'
}

function taskCardClasses(task) {
  return {
    'is-active': ACTIVE_CLASS_STATUSES.has(task.status),
    'is-success': task.status === 'success',
    'is-failed': task.status === 'failed'
  }
}

function taskTypeLabel(type) {
  if (!type) return '后台任务'
  return TASK_TYPE_LABELS[type] || type
}

function formatTaskId(id) {
  if (!id) return '--'
  return id.slice(0, 8)
}

watch(
  isOpen,
  (open) => {
    if (open) {
      taskerStore.loadTasks()
      taskerStore.startPolling()
    } else {
      taskerStore.stopPolling()
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  taskerStore.stopPolling()
})

function handleClose() {
  taskerStore.closeDrawer()
}

function handleRefresh() {
  taskerStore.loadTasks()
}

function handleTaskCardClick(task) {
  console.log('Task clicked:', task)
}

function handleDetail(taskId) {
  const task = tasks.value.find((item) => item.id === taskId)
  if (!task) {
    return
  }
  const detail = h('div', { class: 'task-detail-modal-content' }, [
    h('div', { class: 'detail-row' }, [
      h('span', { class: 'label' }, '状态：'),
      h('span', { class: 'value' }, statusLabel(task.status))
    ]),
    h('div', { class: 'detail-row' }, [
      h('span', { class: 'label' }, '进度：'),
      h('span', { class: 'value' }, `${Math.round(task.progress || 0)}%`)
    ]),
    h('div', { class: 'detail-row' }, [
      h('span', { class: 'label' }, '更新时间：'),
      h('span', { class: 'value' }, formatTime(task.updated_at))
    ]),
    h('div', { class: 'detail-row full' }, [
      h('span', { class: 'label' }, '描述：'),
      h('div', { class: 'value description' }, task.message || '-')
    ]),
    task.error
      ? h('div', { class: 'detail-row full error' }, [
          h('span', { class: 'label' }, '错误信息：'),
          h('div', { class: 'value error-text' }, task.error)
        ])
      : null
  ])

  Modal.info({
    title: task.name,
    width: 520,
    icon: null,
    content: detail,
    maskClosable: true,
    class: 'task-detail-modal'
  })
}

function handleCancel(taskId) {
  taskerStore.cancelTask(taskId)
}

function handleDelete(taskId, taskName) {
  Modal.confirm({
    title: '确认删除',
    content: `确定要删除任务"${taskName}"吗？此操作不可恢复。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => {
      taskerStore.deleteTask(taskId)
    }
  })
}

function formatTime(value, mode = 'full') {
  if (!value) return '-'
  if (mode === 'short') {
    return formatRelative(value)
  }
  return formatFullDateTime(value)
}

function getTaskDuration(task) {
  if (!task.started_at || !task.completed_at) return null
  try {
    const start = parseToShanghai(task.started_at)
    const end = parseToShanghai(task.completed_at)
    if (!start || !end) {
      return null
    }

    const diffSeconds = Math.max(0, Math.floor(end.diff(start, 'second')))
    const hours = Math.floor(diffSeconds / 3600)
    const minutes = Math.floor((diffSeconds % 3600) / 60)
    const seconds = diffSeconds % 60

    if (hours > 0) {
      return `${hours}小时${minutes}分钟`
    }
    if (minutes > 0) {
      return `${minutes}分钟${seconds}秒`
    }
    if (seconds > 0) {
      return `${seconds}秒`
    }
    return '< 1秒'
  } catch {
    return null
  }
}

function isTaskCompleted(task) {
  return ['success', 'failed', 'cancelled'].includes(task.status)
}

function statusLabel(status) {
  const map = {
    pending: '等待中',
    queued: '已排队',
    running: '进行中',
    success: '已完成',
    failed: '失败',
    cancelled: '已取消'
  }
  return map[status] || status
}

function progressStatus(status) {
  if (status === 'failed') return 'exception'
  if (status === 'cancelled') return 'normal'
  return 'active'
}

function canCancel(task) {
  return ['pending', 'running', 'queued'].includes(task.status) && !task.cancel_requested
}
</script>

<style scoped lang="less">
.task-center-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 24px;
}

.task-header-alert {
  background: var(--primary-50);
  border: 1px solid var(--primary-100);
  border-radius: 8px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;

  .icon {
    color: var(--primary-500);
    font-size: 16px;
  }

  p {
    margin: 0;
    font-size: 13px;
    color: var(--primary-700);
  }
}

.task-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

:deep(.custom-segmented) {
  background: var(--gray-200);
  padding: 4px;
  border-radius: 8px;

  .ant-segmented-item {
    border-radius: 6px;
  }

  .custom-segment-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px;

    .count-badge {
      font-size: 12px;
      background: var(--gray-300);
      color: var(--gray-600);
      padding: 0 6px;
      border-radius: 10px;
      min-width: 20px;
      text-align: center;

      &.active {
        background: var(--primary-100);
        color: var(--primary-600);
      }
      &.success {
        background: var(--success-100);
        color: var(--success-600);
      }
      &.error {
        background: var(--error-100);
        color: var(--error-600);
      }
    }
  }
}

.task-error-alert {
  margin-bottom: 16px;
  border-radius: 8px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  padding-right: 4px;
  padding-bottom: 24px;
  flex: 1;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-thumb {
    background: var(--gray-300);
    border-radius: 3px;
  }
}

.task-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;

  &:hover {
    border-color: var(--primary-200);
    box-shadow: 0 4px 12px var(--shadow-color);
    transform: translateY(-2px);
  }

  &.is-active {
    border-left: 4px solid var(--primary-500);
  }

  &.is-success {
    border-left: 4px solid var(--success-500);
  }

  &.is-failed {
    border-left: 4px solid var(--error-500);
  }
}

.task-card-main {
  padding: 16px 16px 12px;
}

.task-card-header {
  margin-bottom: 12px;

  .header-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .task-type-badge {
    font-size: 12px;
    color: var(--gray-600);
    background: var(--gray-100);
    padding: 2px 8px;
    border-radius: 4px;
  }

  .task-status-badge {
    font-size: 12px;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 6px;

    .dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
    }

    &.pending,
    &.queued {
      color: var(--primary-600);
      .dot {
        background: var(--primary-500);
      }
    }
    &.running {
      color: var(--primary-600);
      .dot {
        background: var(--primary-500);
        animation: pulse 1.5s infinite;
      }
    }
    &.success {
      color: var(--success-600);
      .dot {
        background: var(--success-500);
      }
    }
    &.failed {
      color: var(--error-600);
      .dot {
        background: var(--error-500);
      }
    }
    &.cancelled {
      color: var(--gray-500);
      .dot {
        background: var(--gray-400);
      }
    }
  }

  .task-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--gray-900);
    margin-bottom: 8px;
    line-height: 1.5;
    word-break: break-word;
  }

  .task-meta {
    font-size: 12px;
    color: var(--gray-500);
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px 0;

    .id {
      font-family: monospace;
    }
    .separator {
      margin: 0 6px;
      color: var(--gray-300);
    }
  }
}

.task-progress-wrapper {
  margin-top: 12px;

  .progress-info {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--gray-600);
    margin-bottom: 4px;

    .percent {
      font-weight: 600;
      color: var(--primary-600);
    }
  }
}

.task-message-box,
.task-error-box {
  margin-top: 12px;
  padding: 10px;
  border-radius: 6px;
  font-size: 13px;
  display: flex;
  gap: 8px;
  line-height: 1.5;

  .icon {
    flex-shrink: 0;
    margin-top: 2px;
  }
}

.task-message-box {
  background: var(--gray-50);
  color: var(--gray-700);
  .icon {
    color: var(--primary-500);
  }
}

.task-error-box {
  background: var(--error-50);
  color: var(--error-700);
  .icon {
    color: var(--error-500);
  }
}

.task-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-top: 1px solid var(--gray-100);
  background: var(--gray-25);

  .footer-time {
    font-size: 12px;
    color: var(--gray-500);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .footer-actions {
    display: flex;
    gap: 8px;

    :deep(.ant-btn) {
      padding: 0 4px;
      height: 24px;
      font-size: 12px;

      &:hover {
        background: rgba(0, 0, 0, 0.05);
      }
      &.delete-btn {
        color: var(--gray-500);
        &:hover {
          color: var(--error-500);
        }
      }
    }
  }
}

.task-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;

  .empty-icon {
    font-size: 48px;
    color: var(--gray-300);
    margin-bottom: 16px;
  }

  .empty-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--gray-800);
    margin-bottom: 8px;
  }

  .empty-desc {
    font-size: 14px;
    color: var(--gray-500);
    max-width: 300px;
  }
}

@keyframes pulse {
  0% {
    transform: scale(0.95);
    opacity: 0.8;
  }
  50% {
    transform: scale(1.1);
    opacity: 1;
  }
  100% {
    transform: scale(0.95);
    opacity: 0.8;
  }
}

// Modal Styles
:deep(.task-detail-modal-content) {
  .detail-row {
    display: flex;
    margin-bottom: 12px;

    .label {
      width: 80px;
      color: var(--gray-500);
      font-weight: 500;
      flex-shrink: 0;
    }
    .value {
      color: var(--gray-900);
      flex: 1;
    }

    &.full {
      flex-direction: column;
      .label {
        margin-bottom: 4px;
      }
    }

    .description {
      background: var(--gray-50);
      padding: 12px;
      border-radius: 6px;
      border: 1px solid var(--gray-200);
      font-size: 13px;
      max-height: 200px;
      overflow-y: auto;
    }

    &.error {
      .error-text {
        background: var(--error-50);
        color: var(--error-700);
        padding: 12px;
        border-radius: 6px;
        border: 1px solid var(--error-200);
        font-family: monospace;
      }
    }
  }
}
</style>
