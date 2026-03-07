<template>
  <a-modal
    :open="visible"
    :title="isEditing ? '编辑智能体' : '创建智能体'"
    :width="760"
    :footer="null"
    @cancel="handleClose"
    :destroyOnClose="true"
    class="agent-creator-modal"
  >
    <div class="creator-content">
      <!-- 步骤 1: 选择模式 -->
      <div v-if="step === 1" class="step-content">
        <div class="auto-team-panel">
          <h3 class="step-title">一句话自动组建团队</h3>
          <p class="step-hint">输入目标即可自动生成团队职责分工，默认基于 Deep Agents 协作模式。</p>
          <a-textarea
            v-model:value="autoTeamPrompt"
            :rows="3"
            placeholder="示例：帮我组建一个需求开发团队，包含前端、后端、测试、文档和产品角色。"
          />
          <div class="auto-team-actions">
            <a-button
              type="primary"
              :loading="autoGenerating"
              :disabled="!autoTeamPrompt.trim()"
              @click="generateTeamFromPrompt"
            >
              <Sparkles :size="14" />
              AI 生成团队草稿
            </a-button>
            <a-button
              :loading="autoCreating"
              :disabled="!autoTeamPrompt.trim()"
              @click="autoCreateTeam"
            >
              一键创建并保存
            </a-button>
          </div>
        </div>

        <h3 class="step-title">选择智能体模式</h3>
        <div class="mode-cards">
          <div
            v-for="mode in modeOptions"
            :key="mode.value"
            class="mode-card"
            :class="{ selected: form.multi_agent_mode === mode.value }"
            @click="form.multi_agent_mode = mode.value"
          >
            <div class="mode-icon">
              <component :is="mode.icon" :size="32" />
            </div>
            <div class="mode-info">
              <h4>{{ mode.label }}</h4>
              <p>{{ mode.description }}</p>
              <div class="mode-features">
                <a-tag v-for="feat in mode.features" :key="feat" size="small">{{ feat }}</a-tag>
              </div>
            </div>
            <div v-if="form.multi_agent_mode === mode.value" class="mode-check">
              <Check :size="18" />
            </div>
          </div>
        </div>
      </div>

      <!-- 步骤 2: 基础配置 -->
      <div v-if="step === 2" class="step-content scrollable-step">
        <h3 class="step-title">基础配置</h3>
        <a-form layout="vertical">
          <a-form-item label="智能体名称" required>
            <a-input v-model:value="form.name" placeholder="给你的智能体起个名字" :maxlength="50" />
          </a-form-item>
          <a-form-item label="描述">
            <a-textarea
              v-model:value="form.description"
              placeholder="描述这个智能体的功能"
              :rows="2"
              :maxlength="200"
            />
          </a-form-item>
          <template v-if="needsSubagents">
            <a-form-item label="团队目标">
              <a-textarea
                v-model:value="form.team_goal"
                placeholder="例如：交付一个可上线的需求版本"
                :rows="2"
              />
            </a-form-item>
            <a-form-item label="任务范围">
              <a-textarea
                v-model:value="form.task_scope"
                placeholder="说明团队职责边界与不包含内容"
                :rows="2"
              />
            </a-form-item>
          </template>
          <a-form-item label="系统提示词">
            <div class="prompt-input-wrapper">
              <a-textarea
                v-model:value="form.system_prompt"
                placeholder="指导智能体的行为和角色"
                :rows="4"
              />
              <a-button
                type="link"
                size="small"
                class="optimize-btn"
                :loading="optimizingMain"
                @click="optimizeMainPrompt"
                :disabled="!form.system_prompt?.trim()"
              >
                <Sparkles :size="14" />
                优化
              </a-button>
            </div>
          </a-form-item>
          <a-form-item label="模型">
            <ModelSelectorComponent
              @select-model="(spec) => (form.model = spec)"
              :model_spec="form.model || ''"
            />
          </a-form-item>

          <!-- 单智能体模式：工具/知识库/MCP -->
          <template v-if="form.multi_agent_mode === 'disabled'">
            <a-form-item label="工具">
              <a-select
                mode="multiple"
                v-model:value="form.tools"
                placeholder="选择需要的工具"
                :options="toolOptions"
                allow-clear
                class="full-width-select"
                :loading="loadingOptions"
              />
            </a-form-item>
            <a-form-item label="知识库">
              <a-select
                mode="multiple"
                v-model:value="form.knowledges"
                placeholder="选择关联的知识库"
                :options="knowledgeOptions"
                allow-clear
                class="full-width-select"
                :loading="loadingOptions"
              />
            </a-form-item>
            <a-form-item label="MCP 服务器">
              <a-select
                mode="multiple"
                v-model:value="form.mcps"
                placeholder="选择 MCP 服务器"
                :options="mcpOptions"
                allow-clear
                class="full-width-select"
                :loading="loadingOptions"
              />
            </a-form-item>
          </template>

          <a-form-item label="示例问题">
            <div class="examples-editor">
              <div v-for="(example, idx) in form.examples" :key="idx" class="example-row">
                <a-input
                  :value="example"
                  @update:value="(val) => updateExample(idx, val)"
                  placeholder="输入一个示例问题"
                />
                <a-button type="text" danger size="small" @click="removeExample(idx)">
                  <Trash2 :size="14" />
                </a-button>
              </div>
              <a-button
                type="dashed"
                size="small"
                @click="addExample"
                :disabled="form.examples.length >= 5"
              >
                <Plus :size="14" /> 添加示例
              </a-button>
            </div>
          </a-form-item>
        </a-form>
      </div>

      <!-- 步骤 3: 子智能体配置 (仅 supervisor / deep_agents 模式) -->
      <div v-if="step === 3" class="step-content scrollable-step">
        <h3 class="step-title">配置子智能体</h3>
        <p class="step-hint" v-if="form.multi_agent_mode === 'supervisor'">
          Supervisor 模式下，主智能体将协调以下子智能体，执行过程完全可观测。
        </p>
        <p class="step-hint" v-else>Deep Agents 模式下，子智能体将高效并行执行，但过程不可见。</p>

        <a-form layout="vertical" v-if="form.multi_agent_mode === 'supervisor'">
          <a-form-item label="Supervisor 提示词">
            <div class="prompt-input-wrapper">
              <a-textarea
                v-model:value="form.supervisor_system_prompt"
                placeholder="可选：自定义 Supervisor 的路由决策提示词"
                :rows="3"
              />
              <a-button
                type="link"
                size="small"
                class="optimize-btn"
                :loading="optimizingSupervisor"
                @click="optimizeSupervisorPrompt"
                :disabled="!form.supervisor_system_prompt?.trim()"
              >
                <Sparkles :size="14" />
                优化
              </a-button>
            </div>
          </a-form-item>
        </a-form>

        <SubagentEditor
          :modelValue="form.subagents"
          @update:modelValue="(val) => (form.subagents = val)"
          :availableTools="rawTools"
          :availableKnowledges="rawKnowledges"
          :availableMcps="rawMcps"
        />
      </div>

      <!-- 底部操作栏 -->
      <div class="creator-footer">
        <a-button v-if="step > 1" @click="prevStep">上一步</a-button>
        <div class="footer-spacer"></div>
        <a-button v-if="step < totalSteps" type="primary" @click="nextStep" :disabled="!canNext">
          下一步
        </a-button>
        <a-button
          v-else
          type="primary"
          @click="handleSubmit"
          :loading="submitting"
          :disabled="!canSubmit"
        >
          {{ isEditing ? '保存修改' : '创建智能体' }}
        </a-button>
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Bot, Users, Zap, Check, Plus, Trash2, Sparkles } from 'lucide-vue-next'
import { message } from 'ant-design-vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import SubagentEditor from '@/components/SubagentEditor.vue'
import { agentApi } from '@/apis/agent_api'
import { useDatabaseStore } from '@/stores/database'

const props = defineProps({
  visible: { type: Boolean, default: false },
  editData: { type: Object, default: null }
})

const emit = defineEmits(['close', 'submit'])

const isEditing = computed(() => !!props.editData)

const modeOptions = [
  {
    value: 'disabled',
    label: '单智能体',
    description: '标准单 Agent 模式，适合简单任务场景。',
    icon: Bot,
    features: ['工具', '知识库', 'MCP']
  },
  {
    value: 'supervisor',
    label: 'Supervisor 子图模式',
    description: '主智能体协调多个子智能体，执行过程完全可观测。',
    icon: Users,
    features: ['多智能体', '可观测', '工具', '知识库', 'MCP']
  },
  {
    value: 'deep_agents',
    label: 'Deep Agents 模式',
    description: '子智能体高效并行执行，适合复杂研究任务。',
    icon: Zap,
    features: ['多智能体', '高效并行', '工具', '知识库', 'MCP']
  }
]

const defaultForm = () => ({
  name: '',
  description: '',
  multi_agent_mode: 'disabled',
  team_goal: '',
  task_scope: '',
  communication_protocol: 'hybrid',
  max_parallel_tasks: 4,
  allow_cross_agent_comm: false,
  system_prompt: '',
  model: '',
  tools: [],
  knowledges: [],
  mcps: [],
  subagents: [],
  supervisor_system_prompt: '',
  examples: []
})

const form = ref(defaultForm())
const autoTeamPrompt = ref('')
const step = ref(1)
const submitting = ref(false)
const optimizingMain = ref(false)
const optimizingSupervisor = ref(false)
const autoGenerating = ref(false)
const autoCreating = ref(false)

// 工具/知识库/MCP 选项加载
const loadingOptions = ref(false)
const rawTools = ref([])
const rawKnowledges = ref([])
const rawMcps = ref([])
const databaseStore = useDatabaseStore()

const toolOptions = computed(() =>
  rawTools.value.map((t) => ({
    label: t.label || t.name || t,
    value: t.value || t.name || t
  }))
)

const knowledgeOptions = computed(() =>
  rawKnowledges.value.map((k) => ({
    label: typeof k === 'string' ? k : k.label || k.name,
    value: typeof k === 'string' ? k : k.value || k.name
  }))
)

const mcpOptions = computed(() =>
  rawMcps.value.map((m) => ({
    label: typeof m === 'string' ? m : m.label || m.name,
    value: typeof m === 'string' ? m : m.value || m.name
  }))
)

const fetchOptions = async () => {
  loadingOptions.value = true
  try {
    const detail = await agentApi.getAgentDetail('DynamicAgent')
    const items = detail.configurable_items || {}

    // Tools
    if (items.tools) {
      rawTools.value = (items.tools.options || []).map((t) => ({
        label: t.name || t,
        value: t.name || t
      }))
    }

    // Knowledges
    if (items.knowledges && items.knowledges.options?.length > 0) {
      rawKnowledges.value = items.knowledges.options
    } else {
      await databaseStore.loadDatabases()
      rawKnowledges.value = (databaseStore.databases || []).map((db) => db.name)
    }

    // MCPs
    if (items.mcps) {
      rawMcps.value = items.mcps.options || []
    }
  } catch (e) {
    console.error('加载工具/知识库/MCP选项失败:', e)
  } finally {
    loadingOptions.value = false
  }
}

const needsSubagents = computed(
  () =>
    form.value.multi_agent_mode === 'supervisor' || form.value.multi_agent_mode === 'deep_agents'
)

const totalSteps = computed(() => (needsSubagents.value ? 3 : 2))

const canNext = computed(() => {
  if (step.value === 1) return !!form.value.multi_agent_mode
  if (step.value === 2) return form.value.name.trim().length > 0
  return true
})

const canSubmit = computed(() => {
  if (!form.value.name.trim()) return false
  if (needsSubagents.value && form.value.subagents.length === 0) return false
  return true
})

const nextStep = () => {
  if (step.value < totalSteps.value) step.value++
}

const prevStep = () => {
  if (step.value > 1) step.value--
}

const addExample = () => {
  if (form.value.examples.length < 5) {
    form.value.examples.push('')
  }
}

const removeExample = (idx) => {
  form.value.examples.splice(idx, 1)
}

const updateExample = (idx, val) => {
  form.value.examples[idx] = val
}

// 优化主智能体提示词
const optimizeMainPrompt = async () => {
  if (!form.value.system_prompt?.trim()) return
  optimizingMain.value = true
  try {
    const res = await agentApi.optimizePrompt(form.value.system_prompt)
    if (res.optimized_prompt) {
      form.value.system_prompt = res.optimized_prompt
      message.success('提示词已优化')
    }
  } catch (e) {
    console.error('优化提示词失败:', e)
    message.error('优化失败，请稍后重试')
  } finally {
    optimizingMain.value = false
  }
}

// 优化 Supervisor 提示词
const optimizeSupervisorPrompt = async () => {
  if (!form.value.supervisor_system_prompt?.trim()) return
  optimizingSupervisor.value = true
  try {
    const res = await agentApi.optimizePrompt(form.value.supervisor_system_prompt)
    if (res.optimized_prompt) {
      form.value.supervisor_system_prompt = res.optimized_prompt
      message.success('提示词已优化')
    }
  } catch (e) {
    console.error('优化提示词失败:', e)
    message.error('优化失败，请稍后重试')
  } finally {
    optimizingSupervisor.value = false
  }
}

const handleClose = () => {
  step.value = 1
  form.value = defaultForm()
  autoTeamPrompt.value = ''
  emit('close')
}

const applyTeamDraft = (draft) => {
  if (!draft || typeof draft !== 'object') return
  form.value.multi_agent_mode = draft.multi_agent_mode || form.value.multi_agent_mode || 'deep_agents'
  form.value.team_goal = draft.team_goal || form.value.team_goal
  form.value.task_scope = draft.task_scope || form.value.task_scope
  form.value.communication_protocol = draft.communication_protocol || form.value.communication_protocol
  form.value.max_parallel_tasks = draft.max_parallel_tasks || form.value.max_parallel_tasks
  form.value.allow_cross_agent_comm =
    typeof draft.allow_cross_agent_comm === 'boolean'
      ? draft.allow_cross_agent_comm
      : form.value.allow_cross_agent_comm
  form.value.system_prompt = draft.system_prompt || form.value.system_prompt
  form.value.supervisor_system_prompt = draft.supervisor_system_prompt || form.value.supervisor_system_prompt
  form.value.subagents = draft.subagents || form.value.subagents

  if (!form.value.name?.trim()) {
    const seed = draft.team_goal || autoTeamPrompt.value
    if (seed) {
      form.value.name = seed.slice(0, 24)
    }
  }
  if (!form.value.description?.trim() && draft.task_scope) {
    form.value.description = draft.task_scope.slice(0, 120)
  }
}

const generateTeamFromPrompt = async () => {
  if (!autoTeamPrompt.value.trim()) return
  autoGenerating.value = true
  try {
    const res = await agentApi.teamWizardStep('DynamicAgent', autoTeamPrompt.value, null, true)
    const draft = res.draft || {}
    applyTeamDraft(draft)
    const subCount = (draft.subagents || []).length
    if (subCount > 0) {
      message.success(`已生成团队草稿（${subCount} 个子智能体）`)
    } else {
      message.warning('草稿已生成，但还缺少子智能体，请补充输入后重试')
    }
    step.value = 2
  } catch (e) {
    console.error('自动组队失败:', e)
    message.error('自动组队失败，请稍后重试')
  } finally {
    autoGenerating.value = false
  }
}

const autoCreateTeam = async () => {
  if (!autoTeamPrompt.value.trim()) return
  autoCreating.value = true
  try {
    const payload = {
      message: autoTeamPrompt.value,
      name: form.value.name?.trim() || undefined,
      description: form.value.description?.trim() || undefined,
      set_default: true,
      auto_complete: true
    }
    await agentApi.autoCreateTeamProfile('DynamicAgent', payload)
    message.success('AI 团队已创建')
    handleClose()
    emit('submit', { refreshOnly: true })
  } catch (e) {
    console.error('自动创建团队失败:', e)
    message.error('自动创建失败，请先生成草稿并手动确认')
  } finally {
    autoCreating.value = false
  }
}

const handleSubmit = async () => {
  submitting.value = true
  try {
    const contextConfig = {
      multi_agent_mode: form.value.multi_agent_mode,
      team_goal: form.value.team_goal,
      task_scope: form.value.task_scope,
      communication_protocol: form.value.communication_protocol,
      max_parallel_tasks: form.value.max_parallel_tasks,
      allow_cross_agent_comm: form.value.allow_cross_agent_comm,
      system_prompt: form.value.system_prompt,
      model: form.value.model,
      supervisor_system_prompt: form.value.supervisor_system_prompt
    }

    if (form.value.multi_agent_mode === 'disabled') {
      // 单智能体：工具/知识库/MCP 放在配置中
      contextConfig.tools = form.value.tools
      contextConfig.knowledges = form.value.knowledges
      contextConfig.mcps = form.value.mcps
      contextConfig.subagents = []
    } else {
      // 多智能体：子智能体各自携带 tools/knowledges/mcps
      contextConfig.subagents = form.value.subagents
      contextConfig.tools = []
      contextConfig.knowledges = []
      contextConfig.mcps = []
    }

    const payload = {
      name: form.value.name.trim(),
      description: form.value.description.trim(),
      examples: form.value.examples.filter((e) => e.trim()),
      // 包裹在 context 中以匹配后端读取逻辑
      config_json: { context: contextConfig }
    }
    emit('submit', { payload, configId: props.editData?.id || null })
  } finally {
    submitting.value = false
  }
}

// 编辑模式：填充表单
watch(
  () => props.editData,
  (data) => {
    if (data) {
      // 优先从 config_json.context 读取，否则 fallback 到 config_json 顶层
      const cfg = data.config_json?.context || data.config_json || {}
      form.value = {
        name: data.name || '',
        description: data.description || '',
        multi_agent_mode: cfg.multi_agent_mode || 'disabled',
        team_goal: cfg.team_goal || '',
        task_scope: cfg.task_scope || '',
        communication_protocol: cfg.communication_protocol || 'hybrid',
        max_parallel_tasks: cfg.max_parallel_tasks || 4,
        allow_cross_agent_comm: !!cfg.allow_cross_agent_comm,
        system_prompt: cfg.system_prompt || '',
        model: cfg.model || '',
        tools: cfg.tools || [],
        knowledges: cfg.knowledges || [],
        mcps: cfg.mcps || [],
        subagents: cfg.subagents || [],
        supervisor_system_prompt: cfg.supervisor_system_prompt || '',
        examples: data.examples || []
      }
      step.value = 2
    } else {
      form.value = defaultForm()
      step.value = 1
    }
  },
  { immediate: true }
)

// 弹窗打开时加载选项
watch(
  () => props.visible,
  (val) => {
    if (val && rawTools.value.length === 0) {
      fetchOptions()
    }
  }
)

onMounted(() => {
  // 预加载选项
  fetchOptions()
})
</script>

<style scoped>
.creator-content {
  min-height: 400px;
  display: flex;
  flex-direction: column;
}

.step-content {
  flex: 1;
}

.scrollable-step {
  max-height: 60vh;
  overflow-y: auto;
  padding-right: 4px;
}

.step-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--color-text, #333);
}

.step-hint {
  font-size: 13px;
  color: var(--color-text-secondary, #666);
  margin-bottom: 16px;
}

.auto-team-panel {
  padding: 14px;
  margin-bottom: 18px;
  border: 1px solid var(--color-border, #e8e8e8);
  border-radius: 10px;
  background: var(--color-bg-container, #fff);
}

.auto-team-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.mode-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mode-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border: 2px solid var(--color-border, #e8e8e8);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.mode-card:hover {
  border-color: var(--color-primary, #1677ff);
  background: var(--color-primary-bg, #e6f4ff);
}

.mode-card.selected {
  border-color: var(--color-primary, #1677ff);
  background: var(--color-primary-bg, #e6f4ff);
}

.mode-icon {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: var(--color-primary, #1677ff);
  color: #fff;
}

.mode-info h4 {
  margin: 0 0 4px 0;
  font-size: 15px;
  font-weight: 600;
}

.mode-info p {
  margin: 0 0 6px 0;
  font-size: 13px;
  color: var(--color-text-secondary, #666);
}

.mode-features {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.mode-features .ant-tag {
  font-size: 11px;
  padding: 0 6px;
  line-height: 18px;
  border-radius: 4px;
  margin: 0;
}

.mode-check {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-primary, #1677ff);
  color: #fff;
}

.creator-footer {
  display: flex;
  align-items: center;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border, #e8e8e8);
}

.footer-spacer {
  flex: 1;
}

.examples-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.example-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.example-row .ant-input {
  flex: 1;
}

.full-width-select {
  width: 100%;
}

.prompt-input-wrapper {
  position: relative;
}

.prompt-input-wrapper .optimize-btn {
  position: absolute;
  right: 4px;
  bottom: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 8px;
  height: auto;
  color: var(--color-primary, #1677ff);
}

.prompt-input-wrapper .optimize-btn:hover {
  background: var(--color-primary-bg, #e6f4ff);
  border-radius: 4px;
}
</style>
