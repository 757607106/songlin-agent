<template>
  <a-drawer
    :open="open"
    :title="null"
    :width="420"
    :closable="false"
    :maskClosable="true"
    @close="$emit('close')"
    class="team-config-drawer"
  >
    <template #extra>
      <a-button type="text" @click="$emit('close')">
        <X :size="18" />
      </a-button>
    </template>

    <div class="drawer-header">
      <h3>团队配置</h3>
      <p>查看并编辑当前草稿的详细配置</p>
    </div>

    <div class="drawer-content">
      <!-- 基础信息 -->
      <div class="config-section">
        <div class="section-header">
          <Settings :size="16" />
          <span>基础信息</span>
        </div>
        <div class="section-body">
          <div class="form-item">
            <label>协作模式</label>
            <a-select v-model:value="localDraft.multi_agent_mode" class="full-width">
              <a-select-option value="disabled">单智能体</a-select-option>
              <a-select-option value="supervisor">Supervisor</a-select-option>
              <a-select-option value="deep_agents">Deep Agents</a-select-option>
              <a-select-option value="swarm">Swarm Handoff</a-select-option>
            </a-select>
          </div>
          <div class="form-item">
            <label>团队目标</label>
            <a-textarea
              v-model:value="localDraft.team_goal"
              placeholder="描述团队的核心目标"
              :rows="2"
            />
          </div>
          <div class="form-item">
            <label>任务范围</label>
            <a-textarea
              v-model:value="localDraft.task_scope"
              placeholder="说明团队职责边界"
              :rows="2"
            />
          </div>
        </div>
      </div>

      <!-- 主智能体配置 -->
      <div class="config-section">
        <div class="section-header">
          <Bot :size="16" />
          <span>主智能体</span>
        </div>
        <div class="section-body">
          <div class="form-item">
            <label>系统提示词</label>
            <a-textarea
              v-model:value="localDraft.system_prompt"
              placeholder="指导智能体的行为和角色"
              :rows="3"
            />
          </div>
          <div class="form-item">
            <label>工具</label>
            <a-select
              v-model:value="localDraft.tools"
              mode="multiple"
              placeholder="选择工具"
              :options="toolOptions"
              allow-clear
              class="full-width"
            />
          </div>
          <div class="form-item">
            <label>知识库</label>
            <a-select
              v-model:value="localDraft.knowledges"
              mode="multiple"
              placeholder="选择知识库"
              :options="knowledgeOptions"
              allow-clear
              class="full-width"
            />
          </div>
          <div class="form-item">
            <label>技能</label>
            <a-select
              v-model:value="localDraft.skills"
              mode="multiple"
              placeholder="选择技能"
              :options="skillOptions"
              allow-clear
              class="full-width"
            />
          </div>
        </div>
      </div>

      <!-- Supervisor / Swarm 配置 -->
      <div v-if="localDraft.multi_agent_mode === 'supervisor' || localDraft.multi_agent_mode === 'swarm'" class="config-section">
        <div class="section-header">
          <Network :size="16" />
          <span>{{ localDraft.multi_agent_mode === 'swarm' ? 'Swarm' : 'Supervisor' }} 配置</span>
        </div>
        <div class="section-body">
          <div class="form-item">
            <label>{{ localDraft.multi_agent_mode === 'swarm' ? '入口 Agent 提示词' : '路由提示词' }}</label>
            <a-textarea
              v-model:value="localDraft.supervisor_system_prompt"
              :placeholder="localDraft.multi_agent_mode === 'swarm' ? '配置入口 Agent 的行为' : '自定义 Supervisor 的路由决策逻辑'"
              :rows="3"
            />
          </div>
        </div>
      </div>

      <!-- 子智能体列表 -->
      <div
        v-if="localDraft.multi_agent_mode !== 'disabled'"
        class="config-section subagents-section"
      >
        <div class="section-header">
          <Users :size="16" />
          <span>子智能体 ({{ localDraft.subagents?.length || 0 }})</span>
          <a-button type="link" size="small" @click="addSubagent">
            <Plus :size="14" /> 添加
          </a-button>
        </div>
        <div class="section-body">
          <div v-if="!localDraft.subagents?.length" class="empty-hint">
            暂无子智能体，点击上方按钮添加
          </div>
          <div
            v-for="(agent, idx) in localDraft.subagents"
            :key="idx"
            class="subagent-item"
          >
            <div class="subagent-header">
              <a-input
                v-model:value="agent.name"
                placeholder="子智能体名称"
                size="small"
                class="name-input"
              />
              <a-button type="text" danger size="small" @click="removeSubagent(idx)">
                <Trash2 :size="14" />
              </a-button>
            </div>
            <a-input
              v-model:value="agent.description"
              placeholder="职责描述"
              size="small"
              class="mt-6"
            />
            <a-select
              v-model:value="agent.tools"
              mode="multiple"
              placeholder="选择工具"
              :options="toolOptions"
              allow-clear
              size="small"
              class="full-width mt-6"
            />
          </div>
        </div>
      </div>

      <!-- 高级设置 -->
      <div class="config-section">
        <div class="section-header collapsible" @click="showAdvanced = !showAdvanced">
          <Sliders :size="16" />
          <span>高级设置</span>
          <ChevronDown :size="14" :class="{ rotated: showAdvanced }" />
        </div>
        <transition name="slide">
          <div v-if="showAdvanced" class="section-body">
            <div class="form-item">
              <label>通信协议</label>
              <a-select v-model:value="localDraft.communication_protocol" class="full-width">
                <a-select-option value="sync">同步</a-select-option>
                <a-select-option value="async">异步</a-select-option>
                <a-select-option value="hybrid">混合</a-select-option>
              </a-select>
            </div>
            <div class="form-item">
              <label>最大并行任务</label>
              <a-input-number
                v-model:value="localDraft.max_parallel_tasks"
                :min="1"
                :max="20"
                class="full-width"
              />
            </div>
            <div class="form-item switch-item">
              <label>允许跨 Agent 通信</label>
              <a-switch v-model:checked="localDraft.allow_cross_agent_comm" size="small" />
            </div>
          </div>
        </transition>
      </div>
    </div>

    <div class="drawer-footer">
      <a-button @click="$emit('close')">取消</a-button>
      <a-button type="primary" :loading="saving" @click="handleSave">
        保存草稿
      </a-button>
    </div>
  </a-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import {
  X,
  Settings,
  Bot,
  Users,
  Network,
  Plus,
  Trash2,
  Sliders,
  ChevronDown
} from 'lucide-vue-next'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  draft: {
    type: Object,
    default: () => ({})
  },
  toolOptions: {
    type: Array,
    default: () => []
  },
  knowledgeOptions: {
    type: Array,
    default: () => []
  },
  skillOptions: {
    type: Array,
    default: () => []
  },
  mcpOptions: {
    type: Array,
    default: () => []
  },
  saving: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'save'])

const showAdvanced = ref(false)
const localDraft = ref(getDefaultDraft())

function getDefaultDraft() {
  return {
    multi_agent_mode: 'deep_agents',
    team_goal: '',
    task_scope: '',
    system_prompt: '',
    supervisor_system_prompt: '',
    communication_protocol: 'hybrid',
    max_parallel_tasks: 4,
    allow_cross_agent_comm: false,
    tools: [],
    knowledges: [],
    mcps: [],
    skills: [],
    subagents: []
  }
}

watch(
  () => props.draft,
  (newDraft) => {
    if (newDraft) {
      localDraft.value = {
        ...getDefaultDraft(),
        ...newDraft,
        tools: [...(newDraft.tools || [])],
        knowledges: [...(newDraft.knowledges || [])],
        mcps: [...(newDraft.mcps || [])],
        skills: [...(newDraft.skills || [])],
        subagents: (newDraft.subagents || []).map((s) => ({ ...s }))
      }
    }
  },
  { immediate: true, deep: true }
)

const addSubagent = () => {
  if (!localDraft.value.subagents) {
    localDraft.value.subagents = []
  }
  localDraft.value.subagents.push({
    name: '',
    description: '',
    system_prompt: '',
    tools: [],
    knowledges: [],
    mcps: [],
    skills: []
  })
}

const removeSubagent = (idx) => {
  localDraft.value.subagents.splice(idx, 1)
}

const handleSave = () => {
  emit('save', { ...localDraft.value })
}
</script>

<style scoped lang="less">
.team-config-drawer {
  :deep(.ant-drawer-body) {
    padding: 0;
    display: flex;
    flex-direction: column;
  }

  :deep(.ant-drawer-header) {
    padding: 12px 16px;
    border-bottom: none;
  }
}

.drawer-header {
  padding: 0 20px 16px;
  border-bottom: 1px solid var(--gray-200);

  h3 {
    margin: 0 0 4px 0;
    font-size: 18px;
    font-weight: 600;
    color: var(--gray-900);
  }

  p {
    margin: 0;
    font-size: 13px;
    color: var(--gray-500);
  }
}

.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.config-section {
  margin-bottom: 20px;
  background: var(--gray-50);
  border-radius: 10px;
  overflow: hidden;

  &.subagents-section {
    .section-header {
      cursor: default;
    }
  }
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  background: var(--gray-100);
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-700);

  &.collapsible {
    cursor: pointer;

    &:hover {
      background: var(--gray-200);
    }

    .lucide-chevron-down {
      margin-left: auto;
      transition: transform 0.2s;

      &.rotated {
        transform: rotate(180deg);
      }
    }
  }

  .ant-btn-link {
    margin-left: auto;
    padding: 0;
    height: auto;
    font-size: 12px;
  }
}

.section-body {
  padding: 14px;
}

.form-item {
  margin-bottom: 12px;

  &:last-child {
    margin-bottom: 0;
  }

  &.switch-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  label {
    display: block;
    font-size: 12px;
    font-weight: 500;
    color: var(--gray-600);
    margin-bottom: 6px;
  }
}

.full-width {
  width: 100%;
}

.mt-6 {
  margin-top: 6px;
}

.empty-hint {
  text-align: center;
  padding: 16px;
  color: var(--gray-400);
  font-size: 13px;
}

.subagent-item {
  padding: 12px;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  margin-bottom: 10px;

  &:last-child {
    margin-bottom: 0;
  }
}

.subagent-header {
  display: flex;
  align-items: center;
  gap: 8px;

  .name-input {
    flex: 1;
  }
}

.drawer-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--gray-200);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  background: var(--gray-0);
}

/* 动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
  max-height: 300px;
  opacity: 1;
}

.slide-enter-from,
.slide-leave-to {
  max-height: 0;
  opacity: 0;
  overflow: hidden;
}
</style>
