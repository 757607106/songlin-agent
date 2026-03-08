<template>
  <div class="team-draft-card" :class="{ expanded: isExpanded }">
    <div class="draft-card-header" @click="toggleExpand">
      <div class="draft-icon">
        <FileText :size="18" />
      </div>
      <div class="draft-info">
        <h4 class="draft-title">{{ draft.team_goal || '团队草稿' }}</h4>
        <div class="draft-meta">
          <a-tag size="small" :color="modeColor">{{ modeLabel }}</a-tag>
          <span v-if="subagentCount > 0" class="meta-item">
            <Users :size="12" />
            {{ subagentCount }} 个子智能体
          </span>
        </div>
      </div>
      <div class="draft-actions">
        <a-button type="primary" size="small" @click.stop="$emit('create')">
          <Rocket :size="14" />
          直接创建
        </a-button>
        <a-button size="small" @click.stop="$emit('view-detail')">
          <ExternalLink :size="14" />
          查看详情
        </a-button>
        <div class="expand-icon" :class="{ rotated: isExpanded }">
          <ChevronDown :size="16" />
        </div>
      </div>
    </div>

    <transition name="slide">
      <div v-if="isExpanded" class="draft-card-body">
        <!-- 基本信息 -->
        <div class="draft-section">
          <label>团队目标</label>
          <p>{{ draft.team_goal || '未设置' }}</p>
        </div>

        <div class="draft-section" v-if="draft.task_scope">
          <label>任务范围</label>
          <p>{{ draft.task_scope }}</p>
        </div>

        <div class="draft-section" v-if="draft.system_prompt">
          <label>系统提示词</label>
          <p class="prompt-text">{{ truncateText(draft.system_prompt, 150) }}</p>
        </div>

        <!-- 子智能体列表 -->
        <div class="draft-section" v-if="subagentCount > 0">
          <label>子智能体</label>
          <div class="subagent-chips">
            <div v-for="(agent, idx) in draft.subagents" :key="idx" class="subagent-chip">
              <Bot :size="14" />
              <span class="chip-name">{{ agent.name || `子智能体 ${idx + 1}` }}</span>
              <span v-if="agent.tools?.length" class="chip-tools">
                {{ agent.tools.length }} 工具
              </span>
            </div>
          </div>
        </div>

        <!-- 资源配置 -->
        <div class="draft-resources">
          <div class="resource-item" v-if="draft.tools?.length">
            <Wrench :size="14" />
            <span>{{ draft.tools.length }} 个工具</span>
          </div>
          <div class="resource-item" v-if="draft.knowledges?.length">
            <Database :size="14" />
            <span>{{ draft.knowledges.length }} 个知识库</span>
          </div>
          <div class="resource-item" v-if="draft.skills?.length">
            <Sparkles :size="14" />
            <span>{{ draft.skills.length }} 个技能</span>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import {
  FileText,
  Users,
  Rocket,
  ExternalLink,
  ChevronDown,
  Bot,
  Wrench,
  Database,
  Sparkles
} from 'lucide-vue-next'

const props = defineProps({
  draft: {
    type: Object,
    default: () => ({})
  }
})

defineEmits(['create', 'view-detail'])

const isExpanded = ref(false)

const modeLabel = computed(() => {
  const mode = props.draft.multi_agent_mode || 'deep_agents'
  const labels = {
    disabled: '单智能体',
    supervisor: 'Supervisor',
    deep_agents: 'Deep Agents'
  }
  return labels[mode] || 'Deep Agents'
})

const modeColor = computed(() => {
  const mode = props.draft.multi_agent_mode || 'deep_agents'
  const colors = {
    disabled: 'default',
    supervisor: 'blue',
    deep_agents: 'green'
  }
  return colors[mode] || 'green'
})

const subagentCount = computed(() => {
  return (props.draft.subagents || []).length
})

const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
}

const truncateText = (text, maxLen) => {
  if (!text) return ''
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text
}
</script>

<style scoped lang="less">
.team-draft-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  overflow: hidden;
  transition: all 0.2s;

  &:hover {
    border-color: var(--main-300);
    box-shadow: var(--shadow-1);
  }

  &.expanded {
    border-color: var(--main-400);
  }
}

.draft-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover {
    background: var(--gray-50);
  }
}

.draft-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--main-100);
  color: var(--main-600);
  flex-shrink: 0;
}

.draft-info {
  flex: 1;
  min-width: 0;
}

.draft-title {
  margin: 0 0 4px 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.draft-meta {
  display: flex;
  align-items: center;
  gap: 10px;

  .meta-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--gray-500);
  }
}

.draft-actions {
  display: flex;
  align-items: center;
  gap: 8px;

  .ant-btn {
    display: flex;
    align-items: center;
    gap: 4px;
    border-radius: 8px;
    font-size: 13px;
  }
}

.expand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  color: var(--gray-400);
  transition: transform 0.2s;

  &.rotated {
    transform: rotate(180deg);
  }
}

.draft-card-body {
  padding: 0 16px 16px;
  border-top: 1px solid var(--gray-100);
  background: var(--gray-50);
}

.draft-section {
  margin-top: 12px;

  label {
    display: block;
    font-size: 12px;
    font-weight: 500;
    color: var(--gray-500);
    margin-bottom: 4px;
  }

  p {
    margin: 0;
    font-size: 13px;
    color: var(--gray-700);
    line-height: 1.5;
  }

  .prompt-text {
    padding: 8px 10px;
    background: var(--gray-0);
    border-radius: 6px;
    font-family: monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }
}

.subagent-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.subagent-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  font-size: 13px;

  .chip-name {
    font-weight: 500;
    color: var(--gray-800);
  }

  .chip-tools {
    font-size: 11px;
    color: var(--gray-500);
    padding: 2px 6px;
    background: var(--gray-100);
    border-radius: 4px;
  }
}

.draft-resources {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--gray-200);
}

.resource-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--gray-600);
}

/* 动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
  max-height: 400px;
  opacity: 1;
}

.slide-enter-from,
.slide-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
}
</style>
