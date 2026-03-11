<template>
  <div class="subagent-editor">
    <!-- 子智能体列表 -->
    <div class="subagent-list">
      <div
        v-for="(agent, index) in modelValue"
        :key="index"
        class="subagent-card"
        :class="{ 'is-default': agent.is_default }"
      >
        <div class="subagent-card-header" @click="toggleExpand(index)">
          <div class="subagent-header-left">
            <div class="subagent-name">
              <span class="subagent-index">{{ index + 1 }}</span>
              <span class="name-text">{{ agent.name || `子智能体 ${index + 1}` }}</span>
              <a-tag v-if="agent.is_default" color="blue" size="small" class="default-tag"
                >默认</a-tag
              >
            </div>
            <!-- 能力标签 -->
            <div class="capability-tags" v-if="!isExpanded(index)">
              <a-tooltip v-if="agent.tools?.length" :title="`工具: ${agent.tools.join(', ')}`">
                <span class="cap-tag cap-tools">
                  <Wrench :size="12" />
                  {{ agent.tools.length }}
                </span>
              </a-tooltip>
              <a-tooltip
                v-if="agent.knowledges?.length"
                :title="`知识库: ${agent.knowledges.join(', ')}`"
              >
                <span class="cap-tag cap-kb">
                  <Database :size="12" />
                  {{ agent.knowledges.length }}
                </span>
              </a-tooltip>
              <a-tooltip v-if="agent.mcps?.length" :title="`MCP: ${agent.mcps.join(', ')}`">
                <span class="cap-tag cap-mcp">
                  <Plug :size="12" />
                  {{ agent.mcps.length }}
                </span>
              </a-tooltip>
              <a-tooltip v-if="agent.skills?.length" :title="`Skills: ${agent.skills.join(', ')}`">
                <span class="cap-tag cap-skills">
                  <Zap :size="12" />
                  {{ agent.skills.length }}
                </span>
              </a-tooltip>
              <a-tooltip
                v-if="agent.depends_on?.length"
                :title="`依赖: ${agent.depends_on.join(', ')}`"
              >
                <span class="cap-tag cap-deps">
                  <GitBranch :size="12" />
                  {{ agent.depends_on.length }}
                </span>
              </a-tooltip>
            </div>
          </div>
          <div class="subagent-actions">
            <a-tooltip title="设为默认 Agent">
              <a-button
                type="text"
                size="small"
                @click.stop="setDefaultAgent(index)"
                :class="{ 'is-default-btn': agent.is_default }"
              >
                <Star :size="14" :fill="agent.is_default ? 'currentColor' : 'none'" />
              </a-button>
            </a-tooltip>
            <a-button type="text" size="small" @click.stop="toggleExpand(index)">
              <ChevronDown v-if="expandedIndex !== index" :size="14" />
              <ChevronUp v-else :size="14" />
            </a-button>
            <a-button type="text" size="small" danger @click.stop="removeAgent(index)">
              <Trash2 :size="14" />
            </a-button>
          </div>
        </div>

        <!-- 折叠内容 -->
        <div v-show="expandedIndex === index" class="subagent-card-body">
          <a-form layout="vertical" size="small">
            <a-form-item label="名称" required>
              <a-input
                :value="agent.name"
                @update:value="(val) => updateField(index, 'name', val)"
                placeholder="如：researcher、writer"
              />
            </a-form-item>

            <a-form-item label="描述" required>
              <a-input
                :value="agent.description"
                @update:value="(val) => updateField(index, 'description', val)"
                placeholder="描述此子智能体的职能"
              />
            </a-form-item>

            <a-form-item label="系统提示词" required>
              <div class="prompt-input-wrapper">
                <a-textarea
                  :value="agent.system_prompt"
                  @update:value="(val) => updateField(index, 'system_prompt', val)"
                  placeholder="指导此子智能体的行为"
                  :rows="3"
                />
                <a-button
                  type="link"
                  size="small"
                  class="optimize-btn"
                  :loading="optimizingIndex === index"
                  @click="optimizeSubagentPrompt(index)"
                  :disabled="!agent.system_prompt?.trim()"
                >
                  <Sparkles :size="14" />
                  优化
                </a-button>
              </div>
            </a-form-item>

            <a-form-item label="模型（可选）">
              <ModelSelectorComponent
                @select-model="(spec) => updateField(index, 'model', spec)"
                :model_spec="agent.model || ''"
              />
            </a-form-item>

            <!-- 工具选择 -->
            <a-form-item label="工具（可选）">
              <a-select
                mode="multiple"
                :value="agent.tools || []"
                @update:value="(val) => updateField(index, 'tools', val)"
                placeholder="选择需要的工具"
                :options="toolOptions"
                allow-clear
                class="full-width-select"
              />
            </a-form-item>

            <!-- 知识库选择 -->
            <a-form-item label="知识库（可选）">
              <a-select
                mode="multiple"
                :value="agent.knowledges || []"
                @update:value="(val) => updateField(index, 'knowledges', val)"
                placeholder="选择关联的知识库"
                :options="knowledgeOptions"
                allow-clear
                class="full-width-select"
              />
            </a-form-item>

            <!-- MCP 服务器选择 -->
            <a-form-item label="MCP 服务器（可选）">
              <a-select
                mode="multiple"
                :value="agent.mcps || []"
                @update:value="(val) => updateField(index, 'mcps', val)"
                placeholder="选择 MCP 服务器"
                :options="mcpOptions"
                allow-clear
                class="full-width-select"
              />
            </a-form-item>

            <!-- Skills 选择 -->
            <a-form-item label="Skills（可选）">
              <a-select
                mode="multiple"
                :value="agent.skills || []"
                @update:value="(val) => updateField(index, 'skills', val)"
                placeholder="选择 Skills"
                :options="skillOptions"
                allow-clear
                class="full-width-select"
              />
            </a-form-item>

            <!-- 依赖关系 -->
            <a-form-item label="依赖其他 Agent（可选）">
              <a-select
                mode="multiple"
                :value="agent.depends_on || []"
                @update:value="(val) => updateField(index, 'depends_on', val)"
                placeholder="选择依赖的 Agent"
                :options="getDependencyOptions(index)"
                allow-clear
                class="full-width-select"
              />
              <div class="dependency-hint" v-if="agent.depends_on?.length">
                <GitBranch :size="12" />
                此 Agent 将在 {{ agent.depends_on.join('、') }} 完成后执行
              </div>
            </a-form-item>
          </a-form>
        </div>
      </div>
    </div>

    <!-- 依赖关系可视化 -->
    <div v-if="modelValue?.length > 1 && hasDependencies" class="dependency-graph">
      <div class="dep-graph-header">
        <GitBranch :size="14" />
        <span>依赖关系图</span>
      </div>
      <div class="dep-graph-content">
        <div v-for="agent in modelValue" :key="agent.name" class="dep-node">
          <div class="dep-node-name" :class="{ 'is-default': agent.is_default }">
            {{ agent.name || '未命名' }}
          </div>
          <div v-if="agent.depends_on?.length" class="dep-arrows">
            <span class="arrow-text">← 依赖 →</span>
            <span v-for="dep in agent.depends_on" :key="dep" class="dep-target">
              {{ dep }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加按钮 -->
    <a-button type="dashed" block @click="addAgent" class="add-agent-btn">
      <Plus :size="14" />
      添加子智能体
    </a-button>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Wrench,
  Database,
  Plug,
  Zap,
  GitBranch,
  Star
} from 'lucide-vue-next'
import { message } from 'ant-design-vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { agentApi } from '@/apis/agent_api'
import { useDatabaseStore } from '@/stores/database'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => []
  },
  // 可以从外部传入可用选项，避免重复请求
  availableTools: { type: Array, default: null },
  availableKnowledges: { type: Array, default: null },
  availableMcps: { type: Array, default: null },
  availableSkills: { type: Array, default: null }
})

const emit = defineEmits(['update:modelValue'])

const expandedIndex = ref(null)
const optimizingIndex = ref(null)
const AGENT_PLATFORM_AGENT_ID = 'AgentPlatformAgent'

// 加载可用的工具/知识库/MCP 选项
const loadedTools = ref([])
const loadedKnowledges = ref([])
const loadedMcps = ref([])
const loadedSkills = ref([])
const databaseStore = useDatabaseStore()

const toolOptions = computed(() => {
  const tools = props.availableTools || loadedTools.value
  return tools.map((t) => ({
    label: t.label || t.name || t,
    value: t.value || t.name || t
  }))
})

const knowledgeOptions = computed(() => {
  const kbs = props.availableKnowledges || loadedKnowledges.value
  return kbs.map((k) => ({
    label: typeof k === 'string' ? k : k.label || k.name,
    value: typeof k === 'string' ? k : k.value || k.name
  }))
})

const mcpOptions = computed(() => {
  const mcps = props.availableMcps || loadedMcps.value
  return mcps.map((m) => ({
    label: typeof m === 'string' ? m : m.label || m.name,
    value: typeof m === 'string' ? m : m.value || m.name
  }))
})

const skillOptions = computed(() => {
  const skills = props.availableSkills || loadedSkills.value
  return skills.map((s) => ({
    label: typeof s === 'string' ? s : s.label || s.name || s.id,
    value: typeof s === 'string' ? s : s.value || s.id || s.name
  }))
})

const fetchOptions = async () => {
  try {
    const detail = await agentApi.getAgentDetail(AGENT_PLATFORM_AGENT_ID)
    const items = detail.configurable_items || {}

    // 工具
    if (!props.availableTools && items.tools) {
      loadedTools.value = (items.tools.options || []).map((t) => ({
        label: t.name || t,
        value: t.name || t
      }))
    }

    // 知识库 — 从 database store 获取
    if (!props.availableKnowledges) {
      if (items.knowledges && items.knowledges.options?.length > 0) {
        loadedKnowledges.value = items.knowledges.options
      } else {
        // 回退：从 database store 获取
        await databaseStore.loadDatabases()
        loadedKnowledges.value = (databaseStore.databases || []).map((db) => db.name)
      }
    }

    // MCP
    if (!props.availableMcps && items.mcps) {
      loadedMcps.value = items.mcps.options || []
    }

    // Skills
    if (!props.availableSkills && items.skills) {
      loadedSkills.value = items.skills.options || []
    }
  } catch (e) {
    console.error('加载可用选项失败:', e)
  }
}

const toggleExpand = (index) => {
  expandedIndex.value = expandedIndex.value === index ? null : index
}

const isExpanded = (index) => expandedIndex.value === index

// 是否有依赖关系
const hasDependencies = computed(() => {
  return props.modelValue?.some((agent) => agent.depends_on?.length > 0)
})

// 获取可依赖的 Agent 列表（排除自身）
const getDependencyOptions = (currentIndex) => {
  return (props.modelValue || [])
    .filter((_, idx) => idx !== currentIndex)
    .filter((agent) => agent.name) // 只显示有名称的 agent
    .map((agent) => ({
      label: agent.name,
      value: agent.name
    }))
}

// 设置默认 Agent
const setDefaultAgent = (index) => {
  const newAgents = (props.modelValue || []).map((agent, idx) => ({
    ...agent,
    is_default: idx === index
  }))
  emit('update:modelValue', newAgents)
}

const addAgent = () => {
  const newAgents = [
    ...(props.modelValue || []),
    {
      name: '',
      description: '',
      system_prompt: '',
      tools: [],
      model: null,
      knowledges: [],
      mcps: [],
      skills: []
    }
  ]
  emit('update:modelValue', newAgents)
  expandedIndex.value = newAgents.length - 1
}

const removeAgent = (index) => {
  const newAgents = [...(props.modelValue || [])]
  newAgents.splice(index, 1)
  emit('update:modelValue', newAgents)
  if (expandedIndex.value === index) {
    expandedIndex.value = null
  }
}

const updateField = (index, field, value) => {
  const newAgents = [...(props.modelValue || [])]
  newAgents[index] = { ...newAgents[index], [field]: value }
  emit('update:modelValue', newAgents)
}

const optimizeSubagentPrompt = async (index) => {
  const agent = props.modelValue[index]
  if (!agent?.system_prompt?.trim()) return

  optimizingIndex.value = index
  try {
    const res = await agentApi.optimizePrompt(agent.system_prompt)
    if (res.optimized_prompt) {
      updateField(index, 'system_prompt', res.optimized_prompt)
      message.success('提示词已优化')
    }
  } catch (e) {
    console.error('优化提示词失败:', e)
    message.error('优化失败，请稍后重试')
  } finally {
    optimizingIndex.value = null
  }
}

onMounted(() => {
  fetchOptions()
  // 如果没有设置默认 agent，设置第一个为默认
  if (props.modelValue?.length > 0 && !props.modelValue.some((a) => a.is_default)) {
    setDefaultAgent(0)
  }
})
</script>

<style scoped>
.subagent-editor {
  width: 100%;
}

.subagent-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}

.subagent-card {
  border: 1px solid var(--color-border, #e8e8e8);
  border-radius: 8px;
  overflow: hidden;
  background: var(--color-bg-container, #fff);
}

.subagent-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  background: var(--color-bg-layout, #f5f5f5);
}

.subagent-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  font-size: 13px;
}

.subagent-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-primary, #1677ff);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.subagent-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.subagent-card-body {
  padding: 12px;
  border-top: 1px solid var(--color-border, #e8e8e8);
}

.subagent-card-body :deep(.ant-form-item) {
  margin-bottom: 8px;
}

.subagent-card-body :deep(.ant-form-item-label) {
  padding-bottom: 2px;
}

.subagent-card-body :deep(.ant-form-item-label > label) {
  font-size: 12px;
  color: var(--color-text-secondary, #666);
}

.full-width-select {
  width: 100%;
}

.add-agent-btn {
  color: var(--color-text-secondary, #999);
  font-size: 13px;
}

.prompt-input-wrapper {
  position: relative;
  width: 100%;
}

.optimize-btn {
  position: absolute;
  right: 4px;
  bottom: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--main-600, #1677ff);
  padding: 2px 8px;
  height: auto;
  background: var(--gray-0, #fff);
  border-radius: 4px;
  opacity: 0.9;
}

.optimize-btn:hover:not(:disabled) {
  color: var(--main-700, #0958d9);
  opacity: 1;
}

.optimize-btn:disabled {
  color: var(--gray-400, #bfbfbf);
  cursor: not-allowed;
}

/* 卡片默认状态样式 */
.subagent-card.is-default {
  border-color: var(--color-primary, #1677ff);
  box-shadow: 0 0 0 1px var(--color-primary-bg, #e6f4ff);
}

.subagent-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.name-text {
  font-weight: 500;
}

.default-tag {
  font-size: 10px;
  padding: 0 4px;
  line-height: 16px;
  border-radius: 3px;
}

/* 能力标签 */
.capability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.cap-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}

.cap-tools {
  background: #e6f7ff;
  color: #1890ff;
}

.cap-kb {
  background: #f6ffed;
  color: #52c41a;
}

.cap-mcp {
  background: #fff7e6;
  color: #fa8c16;
}

.cap-skills {
  background: #f9f0ff;
  color: #722ed1;
}

.cap-deps {
  background: #fff1f0;
  color: #f5222d;
}

/* 默认按钮 */
.is-default-btn {
  color: var(--color-primary, #1677ff) !important;
}

/* 依赖提示 */
.dependency-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 6px 10px;
  background: var(--color-bg-layout, #f5f5f5);
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-text-secondary, #666);
}

/* 依赖关系图 */
.dependency-graph {
  margin-bottom: 12px;
  padding: 12px;
  background: var(--color-bg-layout, #fafafa);
  border: 1px dashed var(--color-border, #d9d9d9);
  border-radius: 8px;
}

.dep-graph-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary, #666);
}

.dep-graph-content {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dep-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--color-bg-container, #fff);
  border: 1px solid var(--color-border, #e8e8e8);
  border-radius: 6px;
  font-size: 12px;
}

.dep-node-name {
  font-weight: 500;
  color: var(--color-text, #333);
}

.dep-node-name.is-default {
  color: var(--color-primary, #1677ff);
}

.dep-arrows {
  display: flex;
  align-items: center;
  gap: 4px;
}

.arrow-text {
  color: var(--color-text-tertiary, #999);
  font-size: 10px;
}

.dep-target {
  padding: 2px 6px;
  background: #fff1f0;
  color: #f5222d;
  border-radius: 4px;
  font-size: 11px;
}
</style>
