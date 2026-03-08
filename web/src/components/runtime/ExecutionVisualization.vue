<template>
  <div class="execution-visualization">
    <!-- 执行状态头部 -->
    <div class="exec-header" v-if="isMultiAgent">
      <div class="exec-mode">
        <component :is="modeIcon" :size="16" />
        <span>{{ modeName }}</span>
      </div>
      <div class="exec-status">
        <span v-if="isRunning" class="status-running">
          <Loader2 :size="14" class="spinning" />
          执行中
        </span>
        <span v-else-if="isComplete" class="status-complete">
          <CheckCircle :size="14" />
          已完成
        </span>
      </div>
    </div>

    <!-- Agent 执行流程图 -->
    <div class="exec-flow" v-if="isMultiAgent && agents.length > 0">
      <div
        v-for="(agent, idx) in agents"
        :key="agent.name"
        class="agent-node"
        :class="{
          'is-active': activeAgent === agent.name,
          'is-completed': completedAgents.includes(agent.name)
        }"
      >
        <div class="agent-avatar">
          <User :size="14" />
        </div>
        <div class="agent-info">
          <span class="agent-name">{{ agent.name }}</span>
          <span class="agent-status">
            <span v-if="activeAgent === agent.name" class="status-dot active"></span>
            <span
              v-else-if="completedAgents.includes(agent.name)"
              class="status-dot completed"
            ></span>
            <span v-else class="status-dot pending"></span>
          </span>
        </div>
        <!-- 连接线 -->
        <div v-if="idx < agents.length - 1" class="connection-line">
          <ArrowRight :size="12" />
        </div>
      </div>
    </div>

    <!-- 执行日志时间线 -->
    <div class="exec-timeline" v-if="executionLog.length > 0">
      <div class="timeline-header">
        <Clock :size="14" />
        <span>执行日志</span>
        <a-button type="link" size="small" @click="showAllLogs = !showAllLogs">
          {{ showAllLogs ? '收起' : '展开全部' }}
        </a-button>
      </div>
      <div class="timeline-entries" :class="{ collapsed: !showAllLogs }">
        <div
          v-for="(entry, idx) in displayedLogs"
          :key="idx"
          class="timeline-entry"
          :class="getEntryClass(entry)"
        >
          <div class="entry-time">{{ formatTime(entry.ts) }}</div>
          <div class="entry-content">
            <span class="entry-type">{{ getEntryLabel(entry.type) }}</span>
            <span class="entry-detail">{{ getEntryDetail(entry) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import {
  Users,
  Zap,
  Shuffle,
  Bot,
  User,
  ArrowRight,
  Clock,
  Loader2,
  CheckCircle
} from 'lucide-vue-next'

const props = defineProps({
  mode: {
    type: String,
    default: 'disabled' // disabled | supervisor | deep_agents | swarm
  },
  agents: {
    type: Array,
    default: () => []
  },
  activeAgent: {
    type: String,
    default: null
  },
  completedAgents: {
    type: Array,
    default: () => []
  },
  executionLog: {
    type: Array,
    default: () => []
  },
  isRunning: {
    type: Boolean,
    default: false
  },
  isComplete: {
    type: Boolean,
    default: false
  }
})

const showAllLogs = ref(false)

const isMultiAgent = computed(() => props.mode !== 'disabled')

const modeIcon = computed(() => {
  switch (props.mode) {
    case 'supervisor':
      return Users
    case 'deep_agents':
      return Zap
    case 'swarm':
      return Shuffle
    default:
      return Bot
  }
})

const modeName = computed(() => {
  switch (props.mode) {
    case 'supervisor':
      return 'Supervisor 模式'
    case 'deep_agents':
      return 'Deep Agents 模式'
    case 'swarm':
      return 'Swarm Handoff 模式'
    default:
      return '单智能体'
  }
})

const displayedLogs = computed(() => {
  if (showAllLogs.value) {
    return props.executionLog
  }
  return props.executionLog.slice(-5)
})

const formatTime = (ts) => {
  if (!ts) return ''
  try {
    const date = new Date(ts)
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  } catch {
    return ts
  }
}

const getEntryClass = (entry) => {
  switch (entry.type) {
    case 'route':
      return 'entry-route'
    case 'finish':
    case 'guard_finish':
    case 'eligible_targets_empty_finish':
      return 'entry-finish'
    case 'dependency_gate':
    case 'communication_gate':
      return 'entry-gate'
    case 'retry_guard_finish':
      return 'entry-warning'
    default:
      return ''
  }
}

const getEntryLabel = (type) => {
  const labels = {
    route: '路由',
    finish: '完成',
    guard_finish: '终止',
    eligible_targets_empty_finish: '无可用目标',
    dependency_gate: '依赖检查',
    communication_gate: '通信检查',
    retry_guard_finish: '重试超限'
  }
  return labels[type] || type
}

const getEntryDetail = (entry) => {
  if (entry.target) {
    return `→ ${entry.target}${entry.reason ? `: ${entry.reason}` : ''}`
  }
  return entry.reason || ''
}
</script>

<style scoped lang="less">
.execution-visualization {
  padding: 12px;
  background: var(--gray-50, #fafafa);
  border-radius: 8px;
  margin-bottom: 12px;
}

.exec-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.exec-mode {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-700, #374151);
}

.exec-status {
  font-size: 12px;
}

.status-running {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--main-600, #1677ff);
}

.status-complete {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--green-600, #16a34a);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.exec-flow {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px;
  background: var(--gray-0, #fff);
  border-radius: 6px;
  border: 1px solid var(--gray-200, #e5e7eb);
}

.agent-node {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--gray-100, #f3f4f6);
  border-radius: 6px;
  transition: all 0.2s;

  &.is-active {
    background: var(--main-100, #dbeafe);
    border: 1px solid var(--main-400, #60a5fa);
  }

  &.is-completed {
    background: var(--green-50, #f0fdf4);
    border: 1px solid var(--green-300, #86efac);
  }
}

.agent-avatar {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-200, #e5e7eb);
  border-radius: 50%;
  color: var(--gray-600, #4b5563);
}

.agent-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.agent-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--gray-800, #1f2937);
}

.agent-status {
  display: flex;
  align-items: center;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;

  &.active {
    background: var(--main-500, #3b82f6);
    animation: pulse 1.5s infinite;
  }

  &.completed {
    background: var(--green-500, #22c55e);
  }

  &.pending {
    background: var(--gray-300, #d1d5db);
  }
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.connection-line {
  color: var(--gray-400, #9ca3af);
  margin: 0 4px;
}

.exec-timeline {
  background: var(--gray-0, #fff);
  border-radius: 6px;
  border: 1px solid var(--gray-200, #e5e7eb);
  overflow: hidden;
}

.timeline-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: var(--gray-50, #f9fafb);
  border-bottom: 1px solid var(--gray-200, #e5e7eb);
  font-size: 12px;
  font-weight: 500;
  color: var(--gray-600, #4b5563);

  .ant-btn-link {
    margin-left: auto;
    padding: 0;
    height: auto;
    font-size: 11px;
  }
}

.timeline-entries {
  max-height: 200px;
  overflow-y: auto;

  &.collapsed {
    max-height: 120px;
  }
}

.timeline-entry {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--gray-100, #f3f4f6);
  font-size: 12px;

  &:last-child {
    border-bottom: none;
  }

  &.entry-route {
    background: var(--main-50, #eff6ff);
  }

  &.entry-finish {
    background: var(--green-50, #f0fdf4);
  }

  &.entry-gate {
    background: var(--yellow-50, #fffbeb);
  }

  &.entry-warning {
    background: var(--red-50, #fef2f2);
  }
}

.entry-time {
  flex-shrink: 0;
  font-family: monospace;
  color: var(--gray-500, #6b7280);
  font-size: 11px;
}

.entry-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.entry-type {
  font-weight: 500;
  color: var(--gray-700, #374151);
}

.entry-detail {
  color: var(--gray-500, #6b7280);
  font-size: 11px;
}
</style>
