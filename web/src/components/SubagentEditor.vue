<template>
  <div class="subagent-editor">
    <!-- 子智能体列表 -->
    <div class="subagent-list">
      <div v-for="(agent, index) in modelValue" :key="index" class="subagent-card">
        <div class="subagent-card-header" @click="toggleExpand(index)">
          <div class="subagent-name">
            <span class="subagent-index">{{ index + 1 }}</span>
            <span>{{ agent.name || `子智能体 ${index + 1}` }}</span>
          </div>
          <div class="subagent-actions">
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
          </a-form>
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
import { Plus, Trash2, ChevronDown, ChevronUp, Sparkles } from 'lucide-vue-next'
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
  availableMcps: { type: Array, default: null }
})

const emit = defineEmits(['update:modelValue'])

const expandedIndex = ref(null)
const optimizingIndex = ref(null)

// 加载可用的工具/知识库/MCP 选项
const loadedTools = ref([])
const loadedKnowledges = ref([])
const loadedMcps = ref([])
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

const fetchOptions = async () => {
  try {
    // 获取 DynamicAgent 的 configurable_items 以获得可用的工具/知识库/MCP
    const detail = await agentApi.getAgentDetail('DynamicAgent')
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
  } catch (e) {
    console.error('加载可用选项失败:', e)
  }
}

const toggleExpand = (index) => {
  expandedIndex.value = expandedIndex.value === index ? null : index
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
      mcps: []
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
</style>
