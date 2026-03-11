<template>
  <a-modal
    :open="visible"
    title="创建智能体"
    :width="860"
    :footer="null"
    :destroyOnClose="true"
    class="agent-creator-modal"
    @cancel="handleClose"
  >
    <div class="creator-content">
      <div v-if="step === 1" class="step-content">
        <div class="auto-team-panel">
          <h3 class="step-title">AI 一句话创建</h3>
          <p class="step-hint">如果需求还不够明确，直接进入 AI 创建工作台更高效。</p>
          <div class="auto-team-actions">
            <a-button type="primary" @click="goTeamBuilder">
              <Sparkles :size="14" />
              进入 AI 创建
            </a-button>
          </div>
        </div>

        <div v-if="blueprintTemplates.length || loadingTemplates" class="template-panel">
          <div class="template-panel-head">
            <div>
              <h3 class="step-title">从模板开始</h3>
              <p class="step-hint">保留旧内置 agent 的能力模板，适合作为新 Agent 的起点。</p>
            </div>
            <a-tag color="default">Templates</a-tag>
          </div>
          <div v-if="loadingTemplates" class="template-loading">
            <a-spin size="small" />
            <span>正在加载模板...</span>
          </div>
          <div class="template-cards">
            <button
              v-for="template in blueprintTemplates"
              :key="template.template_id"
              type="button"
              class="template-card"
              :class="{ active: selectedTemplateId === template.template_id }"
              @click="applyTemplate(template)"
            >
              <div class="template-card-head">
                <strong>{{ template.name }}</strong>
                <a-tag>{{ formatExecutionMode(template.blueprint?.execution_mode) }}</a-tag>
              </div>
              <p>{{ template.description }}</p>
              <div class="template-card-tags">
                <a-tag v-for="hint in (template.prompt_hints || []).slice(0, 2)" :key="hint" size="small">
                  {{ hint }}
                </a-tag>
              </div>
            </button>
          </div>
        </div>

        <div v-if="agentExamples.length || loadingExamples" class="template-panel">
          <div class="template-panel-head">
            <div>
              <h3 class="step-title">开发示例</h3>
              <p class="step-hint">直接载入完整 legacy 示例 blueprint，适合改造成自己的 Agent。</p>
            </div>
            <a-tag color="default">Examples</a-tag>
          </div>
          <div v-if="loadingExamples" class="template-loading">
            <a-spin size="small" />
            <span>正在加载开发示例...</span>
          </div>
          <div class="template-cards">
            <button
              v-for="example in agentExamples"
              :key="example.example_id"
              type="button"
              class="template-card"
              :class="{ active: selectedExampleId === example.example_id }"
              @click="applyExample(example)"
            >
              <div class="template-card-head">
                <strong>{{ example.name }}</strong>
                <a-tag>{{ formatExecutionMode(example.blueprint?.execution_mode) }}</a-tag>
              </div>
              <p>{{ example.description }}</p>
              <div class="template-card-tags">
                <a-tag v-for="hint in (example.sample_prompts || []).slice(0, 2)" :key="hint" size="small">
                  {{ hint }}
                </a-tag>
              </div>
            </button>
          </div>
        </div>

        <h3 class="step-title">选择执行架构</h3>
        <div class="mode-cards">
          <div
            v-for="mode in modeOptions"
            :key="mode.value"
            class="mode-card"
            :class="{ selected: form.execution_mode === mode.value }"
            @click="selectMode(mode.value)"
          >
            <div class="mode-icon">
              <component :is="mode.icon" :size="32" />
            </div>
            <div class="mode-info">
              <h4>{{ mode.label }}</h4>
              <p>{{ mode.description }}</p>
              <div class="mode-features">
                <a-tag v-for="feature in mode.features" :key="feature" size="small">{{ feature }}</a-tag>
              </div>
            </div>
            <div v-if="form.execution_mode === mode.value" class="mode-check">
              <Check :size="18" />
            </div>
          </div>
        </div>
      </div>

      <div v-if="step === 2" class="step-content scrollable-step">
        <h3 class="step-title">基础 Blueprint</h3>
        <a-form layout="vertical">
          <a-form-item label="智能体名称" required>
            <a-input v-model:value="form.name" placeholder="例如：销售情报 Agent" :maxlength="50" />
          </a-form-item>

          <a-form-item label="描述">
            <a-textarea v-model:value="form.description" :rows="2" placeholder="一句话说明这个 Agent 做什么" />
          </a-form-item>

          <a-form-item label="目标" required>
            <a-textarea
              v-model:value="form.goal"
              :rows="2"
              placeholder="例如：理解问题，检索资料，给出可执行结论"
            />
          </a-form-item>

          <a-form-item label="任务范围">
            <a-textarea
              v-model:value="form.task_scope"
              :rows="2"
              placeholder="说明负责什么、不负责什么"
            />
          </a-form-item>

          <a-form-item label="系统提示词">
            <div class="prompt-input-wrapper">
              <a-textarea
                v-model:value="form.system_prompt"
                :rows="4"
                placeholder="约束主 Agent 的职责、决策边界和输出风格"
              />
              <a-button
                type="link"
                size="small"
                class="optimize-btn"
                :loading="optimizingMain"
                :disabled="!form.system_prompt?.trim()"
                @click="optimizeMainPrompt"
              >
                <Sparkles :size="14" />
                优化
              </a-button>
            </div>
          </a-form-item>

          <a-form-item v-if="form.execution_mode === 'supervisor'" label="Supervisor 提示词">
            <div class="prompt-input-wrapper">
              <a-textarea
                v-model:value="form.supervisor_prompt"
                :rows="3"
                placeholder="可选：定义路由与协作约束"
              />
              <a-button
                type="link"
                size="small"
                class="optimize-btn"
                :loading="optimizingSupervisor"
                :disabled="!form.supervisor_prompt?.trim()"
                @click="optimizeSupervisorPrompt"
              >
                <Sparkles :size="14" />
                优化
              </a-button>
            </div>
          </a-form-item>

          <a-form-item label="默认模型">
            <ModelSelectorComponent
              :model_spec="form.default_model || ''"
              @select-model="(spec) => (form.default_model = spec)"
            />
          </a-form-item>

          <div class="resource-grid">
            <a-form-item label="工具">
              <a-select
                v-model:value="form.tools"
                mode="multiple"
                :options="toolOptions"
                placeholder="主 Agent 默认可用工具"
                allow-clear
                :loading="loadingOptions"
              />
            </a-form-item>
            <a-form-item label="知识库">
              <a-select
                v-model:value="form.knowledge_ids"
                mode="multiple"
                :options="knowledgeOptions"
                placeholder="主 Agent 默认可用知识库"
                allow-clear
                :loading="loadingOptions"
              />
            </a-form-item>
            <a-form-item label="MCP">
              <a-select
                v-model:value="form.mcps"
                mode="multiple"
                :options="mcpOptions"
                placeholder="主 Agent 默认可用 MCP"
                allow-clear
                :loading="loadingOptions"
              />
            </a-form-item>
            <a-form-item label="Skills">
              <a-select
                v-model:value="form.skills"
                mode="multiple"
                :options="skillOptions"
                placeholder="主 Agent 默认可用 Skills"
                allow-clear
                :loading="loadingOptions"
              />
            </a-form-item>
          </div>

          <a-form-item label="示例问题">
            <div class="examples-editor">
              <div v-for="(example, index) in form.examples" :key="index" class="example-row">
                <a-input
                  :value="example"
                  placeholder="输入一个示例问题"
                  @update:value="(value) => updateExample(index, value)"
                />
                <a-button type="text" danger size="small" @click="removeExample(index)">
                  <Trash2 :size="14" />
                </a-button>
              </div>
              <a-button type="dashed" size="small" :disabled="form.examples.length >= 5" @click="addExample">
                <Plus :size="14" />
                添加示例
              </a-button>
            </div>
          </a-form-item>
        </a-form>
      </div>

      <div v-if="step === 3" class="step-content scrollable-step">
        <div class="workers-header">
          <div>
            <h3 class="step-title">Worker 设计</h3>
            <p class="step-hint">{{ workerStepHint }}</p>
          </div>
          <a-button type="dashed" @click="addWorker">
            <Plus :size="14" />
            添加 Worker
          </a-button>
        </div>

        <div class="worker-list">
          <div v-for="(worker, index) in form.workers" :key="worker.local_id" class="worker-card">
            <div class="worker-card-header">
              <div class="worker-card-title">
                <span class="worker-index">{{ index + 1 }}</span>
                <span>{{ worker.name || `Worker ${index + 1}` }}</span>
              </div>
              <a-button type="text" danger size="small" @click="removeWorker(index)">
                <Trash2 :size="14" />
              </a-button>
            </div>

            <a-form layout="vertical">
              <div class="worker-grid two-col">
                <a-form-item label="名称" required>
                  <a-input v-model:value="worker.name" placeholder="例如：Research Worker" />
                </a-form-item>
                <a-form-item label="类型">
                  <a-select v-model:value="worker.kind">
                    <a-select-option value="reasoning">Reasoning</a-select-option>
                    <a-select-option value="tool">Tool</a-select-option>
                    <a-select-option value="retrieval">Retrieval</a-select-option>
                  </a-select>
                </a-form-item>
              </div>

              <a-form-item label="描述">
                <a-input v-model:value="worker.description" placeholder="描述这个 Worker 负责什么" />
              </a-form-item>

              <a-form-item label="目标">
                <a-input v-model:value="worker.objective" placeholder="例如：检索资料并产出事实摘要" />
              </a-form-item>

              <a-form-item label="系统提示词">
                <a-textarea
                  v-model:value="worker.system_prompt"
                  :rows="3"
                  placeholder="约束这个 Worker 的职责和输出"
                />
              </a-form-item>

              <a-form-item label="模型">
                <ModelSelectorComponent
                  :model_spec="worker.model || ''"
                  @select-model="(spec) => updateWorker(index, 'model', spec)"
                />
              </a-form-item>

              <div class="worker-grid">
                <a-form-item label="工具">
                  <a-select
                    v-model:value="worker.tools"
                    mode="multiple"
                    :options="toolOptions"
                    allow-clear
                    :loading="loadingOptions"
                  />
                </a-form-item>
                <a-form-item label="知识库">
                  <a-select
                    v-model:value="worker.knowledge_ids"
                    mode="multiple"
                    :options="knowledgeOptions"
                    allow-clear
                    :loading="loadingOptions"
                  />
                </a-form-item>
                <a-form-item label="MCP">
                  <a-select
                    v-model:value="worker.mcps"
                    mode="multiple"
                    :options="mcpOptions"
                    allow-clear
                    :loading="loadingOptions"
                  />
                </a-form-item>
                <a-form-item label="Skills">
                  <a-select
                    v-model:value="worker.skills"
                    mode="multiple"
                    :options="skillOptions"
                    allow-clear
                    :loading="loadingOptions"
                  />
                </a-form-item>
              </div>

              <div class="worker-grid two-col">
                <a-form-item label="依赖 Worker">
                  <a-select
                    v-model:value="worker.depends_on"
                    mode="multiple"
                    :options="workerRelationOptions(index)"
                    allow-clear
                  />
                </a-form-item>
                <a-form-item label="允许下一跳">
                  <a-select
                    v-model:value="worker.allowed_next"
                    mode="multiple"
                    :options="workerRelationOptions(index)"
                    allow-clear
                  />
                </a-form-item>
              </div>
            </a-form>
          </div>
        </div>
      </div>

      <div class="creator-footer">
        <a-button v-if="step > 1" @click="prevStep">上一步</a-button>
        <div class="footer-spacer"></div>
        <a-button v-if="step < totalSteps" type="primary" :disabled="!canNext" @click="nextStep">
          下一步
        </a-button>
        <a-button v-else type="primary" :loading="submitting" :disabled="!canSubmit" @click="handleSubmit">
          创建智能体
        </a-button>
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Bot, Check, Plus, Shuffle, Sparkles, Trash2, Users, Zap } from 'lucide-vue-next'
import { message } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { agentApi } from '@/apis/agent_api'
import { agentDesignApi } from '@/apis/agent_design_api'
import { useDatabaseStore } from '@/stores/database'

const props = defineProps({
  visible: { type: Boolean, default: false },
  editData: { type: Object, default: null }
})

const emit = defineEmits(['close', 'submit'])
const router = useRouter()
const databaseStore = useDatabaseStore()
const AGENT_PLATFORM_AGENT_ID = 'AgentPlatformAgent'

const modeOptions = [
  {
    value: 'single',
    label: 'Single Agent',
    description: '轻量单 Agent，适合简单问答、工具调用和基础 RAG。',
    icon: Bot,
    features: ['工具', 'RAG', 'MCP']
  },
  {
    value: 'supervisor',
    label: 'Supervisor',
    description: '适合强流程编排、审批和稳定执行。',
    icon: Users,
    features: ['多 Worker', '可观测', '稳定']
  },
  {
    value: 'deep_agents',
    label: 'Deep Agents',
    description: '适合复杂开放任务，允许更强的自治执行。',
    icon: Zap,
    features: ['深度执行', 'Skills', '动态性']
  },
  {
    value: 'swarm_handoff',
    label: 'Swarm Handoff',
    description: '适合会话型交接和角色切换。',
    icon: Shuffle,
    features: ['交接', '多角色', '动态路由']
  }
]

const createWorker = () => ({
  local_id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
  key: '',
  name: '',
  description: '',
  objective: '',
  system_prompt: '',
  kind: 'reasoning',
  model: '',
  tools: [],
  knowledge_ids: [],
  mcps: [],
  skills: [],
  depends_on: [],
  allowed_next: []
})

const defaultForm = () => ({
  name: '',
  description: '',
  goal: '',
  task_scope: '',
  execution_mode: 'single',
  system_prompt: '',
  supervisor_prompt: '',
  default_model: '',
  tools: [],
  knowledge_ids: [],
  mcps: [],
  skills: [],
  workers: [],
  examples: []
})

const form = ref(defaultForm())
const step = ref(1)
const submitting = ref(false)
const optimizingMain = ref(false)
const optimizingSupervisor = ref(false)
const loadingOptions = ref(false)
const loadingTemplates = ref(false)
const loadingExamples = ref(false)
const rawTools = ref([])
const rawKnowledges = ref([])
const rawMcps = ref([])
const rawSkills = ref([])
const blueprintTemplates = ref([])
const agentExamples = ref([])
const selectedTemplateId = ref('')
const selectedExampleId = ref('')

const toolOptions = computed(() =>
  rawTools.value.map((item) => ({ label: item.label || item.name || item, value: item.value || item.name || item }))
)
const knowledgeOptions = computed(() =>
  rawKnowledges.value.map((item) => ({
    label: typeof item === 'string' ? item : item.label || item.name,
    value: typeof item === 'string' ? item : item.value || item.name
  }))
)
const mcpOptions = computed(() =>
  rawMcps.value.map((item) => ({
    label: typeof item === 'string' ? item : item.label || item.name,
    value: typeof item === 'string' ? item : item.value || item.name
  }))
)
const skillOptions = computed(() =>
  rawSkills.value.map((item) => ({
    label: typeof item === 'string' ? item : item.label || item.name || item.id,
    value: typeof item === 'string' ? item : item.value || item.id || item.name
  }))
)

const needsWorkers = computed(() => form.value.execution_mode !== 'single')
const totalSteps = computed(() => (needsWorkers.value ? 3 : 2))
const workerStepHint = computed(() => {
  if (form.value.execution_mode === 'supervisor') return '用静态 Worker 定义清晰流程，适合高稳定性场景。'
  if (form.value.execution_mode === 'deep_agents') return '为复杂任务配置专用 Worker，保留更强的自治能力。'
  return '为不同角色定义 handoff 目标和上下文边界。'
})

const canNext = computed(() => {
  if (step.value === 1) return Boolean(form.value.execution_mode)
  if (step.value === 2) return Boolean(form.value.name.trim() && form.value.goal.trim())
  return true
})

const canSubmit = computed(() => {
  if (!form.value.name.trim() || !form.value.goal.trim()) return false
  if (!needsWorkers.value) return true
  return form.value.workers.length > 0 && form.value.workers.every((worker) => worker.name.trim())
})

const workerRelationOptions = (currentIndex) =>
  form.value.workers
    .filter((_, index) => index !== currentIndex)
    .filter((worker) => worker.name.trim())
    .map((worker) => ({ label: worker.name.trim(), value: worker.name.trim() }))

const fetchOptions = async () => {
  loadingOptions.value = true
  try {
    const detail = await agentApi.getAgentDetail(AGENT_PLATFORM_AGENT_ID)
    const items = detail.configurable_items || {}

    rawTools.value = (items.tools?.options || []).map((item) => ({
      label: item.name || item,
      value: item.name || item
    }))

    if (items.knowledges?.options?.length > 0) {
      rawKnowledges.value = items.knowledges.options
    } else {
      await databaseStore.loadDatabases()
      rawKnowledges.value = (databaseStore.databases || []).map((db) => db.name)
    }

    rawMcps.value = items.mcps?.options || []
    rawSkills.value = items.skills?.options || []
  } catch (error) {
    console.error('加载可用资源失败:', error)
  } finally {
    loadingOptions.value = false
  }
}

const fetchTemplates = async () => {
  loadingTemplates.value = true
  try {
    const payload = await agentDesignApi.templates()
    blueprintTemplates.value = payload.blueprint_templates || []
  } catch (error) {
    console.error('加载模板失败:', error)
  } finally {
    loadingTemplates.value = false
  }
}

const fetchExamples = async () => {
  loadingExamples.value = true
  try {
    const payload = await agentDesignApi.examples()
    agentExamples.value = payload.examples || []
  } catch (error) {
    console.error('加载开发示例失败:', error)
  } finally {
    loadingExamples.value = false
  }
}

const formatExecutionMode = (mode) => {
  if (mode === 'single') return 'Single'
  if (mode === 'supervisor') return 'Supervisor'
  if (mode === 'deep_agents') return 'Deep Agents'
  if (mode === 'swarm_handoff') return 'Swarm Handoff'
  return mode || 'Unknown'
}

const buildFormFromBlueprint = (blueprint, presetExamples = []) => ({
  name: blueprint?.name || '',
  description: blueprint?.description || '',
  goal: blueprint?.goal || '',
  task_scope: blueprint?.task_scope || '',
  execution_mode: blueprint?.execution_mode || 'single',
  system_prompt: blueprint?.system_prompt || '',
  supervisor_prompt: blueprint?.supervisor_prompt || '',
  default_model: blueprint?.default_model || '',
  tools: [...(blueprint?.tools || [])],
  knowledge_ids: [...(blueprint?.knowledge_ids || [])],
  mcps: [...(blueprint?.mcps || [])],
  skills: [...(blueprint?.skills || [])],
  workers: (blueprint?.workers || []).map((worker) => ({
    local_id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    key: worker.key || '',
    name: worker.name || '',
    description: worker.description || '',
    objective: worker.objective || '',
    system_prompt: worker.system_prompt || '',
    kind: worker.kind || 'reasoning',
    model: worker.model || '',
    tools: [...(worker.tools || [])],
    knowledge_ids: [...(worker.knowledge_ids || [])],
    mcps: [...(worker.mcps || [])],
    skills: [...(worker.skills || [])],
    depends_on: [...(worker.depends_on || [])],
    allowed_next: [...(worker.allowed_next || [])]
  })),
  examples: [...presetExamples]
})

const selectMode = (mode) => {
  form.value.execution_mode = mode
  if (mode === 'single') {
    form.value.workers = []
    return
  }
  if (form.value.workers.length === 0) {
    form.value.workers = [createWorker()]
  }
}

const applyTemplate = (template) => {
  selectedTemplateId.value = template.template_id
  selectedExampleId.value = ''
  form.value = buildFormFromBlueprint(template.blueprint)
  step.value = 2
}

const applyExample = (example) => {
  selectedTemplateId.value = ''
  selectedExampleId.value = example.example_id
  form.value = buildFormFromBlueprint(example.blueprint, example.sample_prompts || [])
  step.value = 2
}

const nextStep = () => {
  if (step.value < totalSteps.value) step.value += 1
}

const prevStep = () => {
  if (step.value > 1) step.value -= 1
}

const addExample = () => {
  if (form.value.examples.length < 5) {
    form.value.examples.push('')
  }
}

const updateExample = (index, value) => {
  form.value.examples[index] = value
}

const removeExample = (index) => {
  form.value.examples.splice(index, 1)
}

const addWorker = () => {
  form.value.workers.push(createWorker())
}

const removeWorker = (index) => {
  form.value.workers.splice(index, 1)
}

const updateWorker = (index, field, value) => {
  form.value.workers[index][field] = value
}

const optimizeMainPrompt = async () => {
  if (!form.value.system_prompt?.trim()) return
  optimizingMain.value = true
  try {
    const res = await agentApi.optimizePrompt(form.value.system_prompt)
    if (res.optimized_prompt) {
      form.value.system_prompt = res.optimized_prompt
      message.success('主提示词已优化')
    }
  } catch (error) {
    console.error('优化提示词失败:', error)
    message.error('优化失败，请稍后重试')
  } finally {
    optimizingMain.value = false
  }
}

const optimizeSupervisorPrompt = async () => {
  if (!form.value.supervisor_prompt?.trim()) return
  optimizingSupervisor.value = true
  try {
    const res = await agentApi.optimizePrompt(form.value.supervisor_prompt)
    if (res.optimized_prompt) {
      form.value.supervisor_prompt = res.optimized_prompt
      message.success('Supervisor 提示词已优化')
    }
  } catch (error) {
    console.error('优化 Supervisor 提示词失败:', error)
    message.error('优化失败，请稍后重试')
  } finally {
    optimizingSupervisor.value = false
  }
}

const buildBlueprint = () => ({
  name: form.value.name.trim(),
  description: form.value.description.trim(),
  goal: form.value.goal.trim(),
  task_scope: form.value.task_scope.trim(),
  execution_mode: form.value.execution_mode,
  system_prompt: form.value.system_prompt.trim(),
  supervisor_prompt: form.value.supervisor_prompt.trim(),
  default_model: form.value.default_model || null,
  tools: [...form.value.tools],
  mcps: [...form.value.mcps],
  knowledge_ids: [...form.value.knowledge_ids],
  skills: [...form.value.skills],
  max_parallel_workers: form.value.execution_mode === 'single' ? 1 : Math.max(1, form.value.workers.length),
  max_dynamic_workers:
    form.value.execution_mode === 'deep_agents' || form.value.execution_mode === 'swarm_handoff'
      ? Math.max(1, form.value.workers.length)
      : 0,
  workers: needsWorkers.value
    ? form.value.workers.map((worker) => ({
        key: worker.key || null,
        name: worker.name.trim(),
        description: worker.description.trim(),
        objective: worker.objective.trim(),
        system_prompt: worker.system_prompt.trim(),
        kind: worker.kind,
        model: worker.model || null,
        tools: [...worker.tools],
        knowledge_ids: [...worker.knowledge_ids],
        mcps: [...worker.mcps],
        skills: [...worker.skills],
        depends_on: [...worker.depends_on],
        allowed_next: [...worker.allowed_next]
      }))
    : []
})

const resetForm = () => {
  step.value = 1
  form.value = defaultForm()
  selectedTemplateId.value = ''
  selectedExampleId.value = ''
}

const handleClose = () => {
  resetForm()
  emit('close')
}

const goTeamBuilder = () => {
  handleClose()
  router.push('/team-builder')
}

const handleSubmit = async () => {
  submitting.value = true
  try {
    emit('submit', {
      blueprint: buildBlueprint(),
      examples: form.value.examples.map((item) => item.trim()).filter(Boolean)
    })
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      fetchOptions()
      fetchTemplates()
      fetchExamples()
    } else {
      resetForm()
    }
  }
)

watch(
  () => form.value.execution_mode,
  (mode) => {
    if (mode !== 'single' && form.value.workers.length === 0) {
      form.value.workers = [createWorker()]
    }
    if (mode === 'single') {
      form.value.workers = []
      if (step.value > 2) {
        step.value = 2
      }
    }
  }
)

onMounted(() => {
  fetchOptions()
  fetchTemplates()
  fetchExamples()
})
</script>

<style scoped lang="less">
.creator-content {
  min-height: 440px;
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
  margin: 0 0 14px;
  font-size: 16px;
  font-weight: 600;
  color: var(--gray-900);
}

.step-hint {
  margin: 0;
  font-size: 13px;
  color: var(--gray-500);
}

.auto-team-panel {
  padding: 14px;
  margin-bottom: 18px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
}

.auto-team-actions {
  margin-top: 12px;
}

.template-panel {
  padding: 14px;
  margin-bottom: 18px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-50);
}

.template-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.template-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.template-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--gray-500);
}

.template-card {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
  padding: 12px;
  text-align: left;
  cursor: pointer;
}

.template-card.active {
  border-color: var(--main-500);
  background: var(--main-50);
}

.template-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.template-card strong {
  font-size: 14px;
  color: var(--gray-900);
}

.template-card p {
  min-height: 36px;
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--gray-600);
}

.template-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mode-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.mode-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
  cursor: pointer;
  transition: border-color 0.2s ease;
}

.mode-card.selected {
  border-color: var(--main-500);
  background: var(--main-50);
}

.mode-icon {
  color: var(--main-500);
}

.mode-info h4 {
  margin: 0 0 6px;
  font-size: 15px;
  color: var(--gray-900);
}

.mode-info p {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--gray-600);
}

.mode-features {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mode-check {
  position: absolute;
  top: 12px;
  right: 12px;
  color: var(--main-600);
}

.resource-grid,
.worker-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.worker-grid.two-col {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.prompt-input-wrapper {
  position: relative;
}

.optimize-btn {
  padding-left: 0;
}

.examples-editor,
.worker-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.example-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workers-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.worker-card {
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
}

.worker-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.worker-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  color: var(--gray-900);
}

.worker-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--main-500);
  color: #fff;
  font-size: 12px;
}

.creator-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 18px;
  margin-top: 18px;
  border-top: 1px solid var(--gray-200);
}

.footer-spacer {
  flex: 1;
}

@media (max-width: 960px) {
  .template-cards,
  .mode-cards,
  .resource-grid,
  .worker-grid,
  .worker-grid.two-col {
    grid-template-columns: 1fr;
  }

  .workers-header {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
