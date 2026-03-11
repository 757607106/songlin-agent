<template>
  <div class="team-builder-view">
    <div class="builder-shell">
      <div class="builder-header">
        <div class="header-left">
          <a-button type="text" class="back-btn" @click="goBack">
            <ArrowLeft :size="18" />
            <span>返回广场</span>
          </a-button>
          <div>
            <h1>一句话创建 Agent</h1>
            <p>输入目标，生成 blueprint，并直接部署到新平台运行时。</p>
          </div>
        </div>
        <div class="header-right">
          <a-button @click="resetDraft" :disabled="drafting || deploying">重置</a-button>
          <a-button type="primary" @click="handleDeploy" :loading="deploying" :disabled="!canDeploy">
            生成并部署
          </a-button>
        </div>
      </div>

      <div class="builder-grid">
        <div class="panel compose-panel">
          <div class="panel-head">
            <div>
              <h2>需求输入</h2>
              <p>优先描述目标、输入来源、是否需要工具、RAG 或多智能体协作。</p>
            </div>
            <a-tag color="blue">Agent Design</a-tag>
          </div>

          <a-form layout="vertical">
            <a-form-item label="创建指令" required>
              <a-textarea
                v-model:value="prompt"
                :rows="5"
                :maxlength="500"
                placeholder="例如：创建一个数据库分析 Agent，先理解问题，再检索表结构和示例 SQL，生成 SQL 执行后输出报表结论。"
              />
            </a-form-item>

            <div v-if="blueprintTemplates.length || loadingTemplates" class="template-section">
              <div class="template-section-head">
                <div>
                  <h3>模板起步</h3>
                  <p>直接从 legacy 模板生成草案，再按需修改目标和资源。</p>
                </div>
                <a-tag color="default">Templates</a-tag>
              </div>
              <div v-if="loadingTemplates" class="template-loading">
                <a-spin size="small" />
                <span>正在加载模板...</span>
              </div>
              <div class="template-list">
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
                    <a-tag v-for="hint in (template.prompt_hints || []).slice(0, 3)" :key="hint" size="small">
                      {{ hint }}
                    </a-tag>
                  </div>
                </button>
              </div>
            </div>

            <div v-if="agentExamples.length || loadingExamples" class="template-section">
              <div class="template-section-head">
                <div>
                  <h3>开发示例</h3>
                  <p>直接加载完整示例 blueprint，适合从 legacy 能力快速起步。</p>
                </div>
                <a-tag color="default">Examples</a-tag>
              </div>
              <div v-if="loadingExamples" class="template-loading">
                <a-spin size="small" />
                <span>正在加载开发示例...</span>
              </div>
              <div class="template-list">
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

            <div class="resource-grid">
              <a-form-item label="工具">
                <a-select
                  v-model:value="selectedResources.tools"
                  mode="multiple"
                  placeholder="可选：限定 AI 可用工具"
                  :options="toolOptions"
                  allow-clear
                  :loading="loadingOptions"
                />
              </a-form-item>
              <a-form-item label="知识库">
                <a-select
                  v-model:value="selectedResources.knowledges"
                  mode="multiple"
                  placeholder="可选：限定可用知识库"
                  :options="knowledgeOptions"
                  allow-clear
                  :loading="loadingOptions"
                />
              </a-form-item>
              <a-form-item label="MCP">
                <a-select
                  v-model:value="selectedResources.mcps"
                  mode="multiple"
                  placeholder="可选：限定 MCP"
                  :options="mcpOptions"
                  allow-clear
                  :loading="loadingOptions"
                />
              </a-form-item>
              <a-form-item label="Skills">
                <a-select
                  v-model:value="selectedResources.skills"
                  mode="multiple"
                  placeholder="可选：限定 Skills"
                  :options="skillOptions"
                  allow-clear
                  :loading="loadingOptions"
                />
              </a-form-item>
            </div>

            <div class="compose-actions">
              <a-button type="primary" @click="handleDraft" :loading="drafting" :disabled="!canDraft">
                <Sparkles :size="16" />
                生成草案
              </a-button>
            </div>
          </a-form>
        </div>

        <div class="panel result-panel">
          <div class="panel-head">
            <div>
              <h2>Blueprint 草案</h2>
              <p>先审阅 blueprint，再决定是否部署。</p>
            </div>
            <a-tag v-if="draftSource" :color="sourceTagColor">
              {{ sourceTagLabel }}
            </a-tag>
          </div>

          <div v-if="drafting" class="loading-state">
            <a-spin />
            <span>正在生成 blueprint...</span>
          </div>

          <template v-else-if="draftBlueprint">
            <div class="intent-strip">
              <div class="intent-item">
                <label>名称</label>
                <a-input v-model:value="draftBlueprint.name" />
              </div>
              <div class="intent-item">
                <label>模式</label>
                <a-select v-model:value="draftBlueprint.execution_mode">
                  <a-select-option value="single">Single</a-select-option>
                  <a-select-option value="supervisor">Supervisor</a-select-option>
                  <a-select-option value="deep_agents">Deep Agents</a-select-option>
                  <a-select-option value="swarm_handoff">Swarm Handoff</a-select-option>
                </a-select>
              </div>
            </div>

            <a-form layout="vertical">
              <a-form-item label="描述">
                <a-textarea v-model:value="draftBlueprint.description" :rows="2" />
              </a-form-item>
              <a-form-item label="目标">
                <a-textarea v-model:value="draftBlueprint.goal" :rows="2" />
              </a-form-item>
              <a-form-item label="范围">
                <a-textarea v-model:value="draftBlueprint.task_scope" :rows="2" />
              </a-form-item>
              <a-form-item label="系统提示词">
                <a-textarea v-model:value="draftBlueprint.system_prompt" :rows="4" />
              </a-form-item>
            </a-form>

            <div class="meta-row">
              <a-tag v-for="note in intentNotes" :key="note" color="processing">{{ note }}</a-tag>
              <span v-if="!intentNotes.length" class="empty-hint">未附加额外说明</span>
            </div>

            <div class="workers-section">
              <div class="section-title">
                <Users :size="16" />
                <span>Worker 设计 ({{ draftBlueprint.workers?.length || 0 }})</span>
              </div>
              <div class="worker-list">
                <div v-for="worker in draftBlueprint.workers || []" :key="worker.key || worker.name" class="worker-card">
                  <div class="worker-top">
                    <div>
                      <h3>{{ worker.name }}</h3>
                      <p>{{ worker.description || worker.objective || '未填写说明' }}</p>
                    </div>
                    <a-tag>{{ worker.kind }}</a-tag>
                  </div>
                  <div class="worker-meta">
                    <span v-if="worker.tools?.length">Tools: {{ worker.tools.join(', ') }}</span>
                    <span v-if="worker.knowledge_ids?.length">
                      RAG: {{ worker.knowledge_ids.join(', ') }}
                    </span>
                    <span v-if="worker.mcps?.length">MCP: {{ worker.mcps.join(', ') }}</span>
                    <span v-if="worker.skills?.length">Skills: {{ worker.skills.join(', ') }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="empty-state">
            <Bot :size="28" />
            <p>还没有生成 blueprint</p>
          </div>
        </div>
      </div>

      <div v-if="deployedConfig" class="deploy-banner">
        <div>
          <h3>部署完成</h3>
          <p>{{ deployedConfig.name }} 已写入新平台运行时。</p>
        </div>
        <div class="deploy-actions">
          <a-button @click="goDetail">查看详情</a-button>
          <a-button type="primary" @click="goChat">
            <MessageCircle :size="16" />
            立即对话
          </a-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ArrowLeft, Bot, MessageCircle, Sparkles, Users } from 'lucide-vue-next'
import { agentApi } from '@/apis/agent_api'
import { agentDesignApi } from '@/apis/agent_design_api'
import { useDatabaseStore } from '@/stores/database'

const router = useRouter()
const databaseStore = useDatabaseStore()

const AGENT_PLATFORM_AGENT_ID = 'AgentPlatformAgent'

const prompt = ref('')
const drafting = ref(false)
const deploying = ref(false)
const loadingOptions = ref(false)
const loadingTemplates = ref(false)
const loadingExamples = ref(false)
const draftSource = ref('')
const draftIntent = ref(null)
const draftBlueprint = ref(null)
const deployedConfig = ref(null)
const selectedTemplateId = ref('')
const selectedExampleId = ref('')
const blueprintTemplates = ref([])
const agentExamples = ref([])

const rawTools = ref([])
const rawKnowledges = ref([])
const rawMcps = ref([])
const rawSkills = ref([])

const selectedResources = ref({
  tools: [],
  knowledges: [],
  mcps: [],
  skills: []
})

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

const intentNotes = computed(() => draftIntent.value?.notes || [])
const canDraft = computed(() => prompt.value.trim().length > 0)
const canDeploy = computed(() => !!draftBlueprint.value && !drafting.value)
const sourceTagLabel = computed(() => {
  if (draftSource.value === 'llm') return 'LLM'
  if (draftSource.value === 'template') return 'Template'
  if (draftSource.value === 'example') return 'Example'
  return 'Rules'
})
const sourceTagColor = computed(() => {
  if (draftSource.value === 'llm') return 'green'
  if (draftSource.value === 'template') return 'gold'
  if (draftSource.value === 'example') return 'cyan'
  return 'default'
})

const buildAvailableResources = () => ({
  tools: selectedResources.value.tools,
  knowledges: selectedResources.value.knowledges,
  mcps: selectedResources.value.mcps,
  skills: selectedResources.value.skills
})

const loadOptions = async () => {
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
    console.error('加载 Agent 设计资源失败:', error)
    message.error('加载可用资源失败')
  } finally {
    loadingOptions.value = false
  }
}

const loadTemplates = async () => {
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

const loadExamples = async () => {
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

const handleDraft = async () => {
  if (!canDraft.value) {
    message.warning('请输入创建指令')
    return
  }

  drafting.value = true
  deployedConfig.value = null
  try {
    selectedTemplateId.value = ''
    selectedExampleId.value = ''
    const result = await agentDesignApi.draft({
      prompt: prompt.value.trim(),
      available_resources: buildAvailableResources(),
      use_ai: true
    })
    draftSource.value = result.source || 'rules'
    draftIntent.value = result.intent || null
    draftBlueprint.value = result.blueprint || null
  } catch (error) {
    console.error('生成 blueprint 失败:', error)
    message.error(`生成失败: ${error.message || '未知错误'}`)
  } finally {
    drafting.value = false
  }
}

const applyTemplate = async (template) => {
  drafting.value = true
  deployedConfig.value = null
  selectedTemplateId.value = template.template_id
  selectedExampleId.value = ''
  try {
    if (!prompt.value.trim()) {
      prompt.value = template.prompt_hints?.[0] || template.name || ''
    }
    const result = await agentDesignApi.draftTemplate(template.template_id, {
      prompt: prompt.value.trim(),
      available_resources: buildAvailableResources()
    })
    draftSource.value = result.source || 'template'
    draftIntent.value = result.intent || null
    draftBlueprint.value = result.blueprint || null
  } catch (error) {
    console.error('应用模板失败:', error)
    message.error(`模板应用失败: ${error.message || '未知错误'}`)
  } finally {
    drafting.value = false
  }
}

const cloneBlueprint = (blueprint) => JSON.parse(JSON.stringify(blueprint || {}))

const applyExample = (example) => {
  deployedConfig.value = null
  selectedTemplateId.value = ''
  selectedExampleId.value = example.example_id
  prompt.value = prompt.value.trim() || example.sample_prompts?.[0] || example.name || ''
  draftSource.value = 'example'
  draftIntent.value = null
  draftBlueprint.value = cloneBlueprint(example.blueprint)
}

const handleDeploy = async () => {
  if (!draftBlueprint.value) {
    await handleDraft()
  }
  if (!draftBlueprint.value) return

  deploying.value = true
  try {
    const validation = await agentDesignApi.validate({ blueprint: draftBlueprint.value })
    if (!validation.valid) {
      message.error(validation.errors?.[0] || 'Blueprint 校验失败')
      return
    }

    const compiled = await agentDesignApi.compile({ blueprint: draftBlueprint.value })
    const deployed = await agentDesignApi.deploy({
      blueprint: draftBlueprint.value,
      spec: compiled.spec,
      name: draftBlueprint.value.name,
      description: draftBlueprint.value.description,
      examples: [prompt.value.trim()]
    })
    deployedConfig.value = deployed.config
    message.success('Agent 已部署')
  } catch (error) {
    console.error('部署 Agent 失败:', error)
    message.error(`部署失败: ${error.message || '未知错误'}`)
  } finally {
    deploying.value = false
  }
}

const resetDraft = () => {
  prompt.value = ''
  draftSource.value = ''
  draftIntent.value = null
  draftBlueprint.value = null
  deployedConfig.value = null
  selectedTemplateId.value = ''
  selectedExampleId.value = ''
  selectedResources.value = {
    tools: [],
    knowledges: [],
    mcps: [],
    skills: []
  }
}

const goBack = () => {
  router.push('/agent-square')
}

const goDetail = () => {
  if (!deployedConfig.value?.id) return
  router.push({
    path: `/agent-square/custom/${deployedConfig.value.id}`,
    query: { runtime_agent_id: AGENT_PLATFORM_AGENT_ID }
  })
}

const goChat = () => {
  if (!deployedConfig.value?.id) return
  router.push({
    path: `/agent/${AGENT_PLATFORM_AGENT_ID}`,
    query: { config_id: deployedConfig.value.id }
  })
}

onMounted(() => {
  loadOptions()
  loadTemplates()
  loadExamples()
})
</script>

<style scoped lang="less">
.team-builder-view {
  min-height: 100%;
  padding: 24px;
  background: var(--gray-100);
}

.builder-shell {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.builder-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.header-left h1 {
  margin: 0;
  font-size: 24px;
  color: var(--gray-900);
}

.header-left p {
  margin: 6px 0 0;
  color: var(--gray-500);
}

.header-right {
  display: flex;
  gap: 10px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.builder-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
}

.panel {
  border: 1px solid var(--gray-200);
  border-radius: 16px;
  background: var(--gray-0);
  padding: 20px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
}

.panel-head h2 {
  margin: 0;
  font-size: 18px;
  color: var(--gray-900);
}

.panel-head p {
  margin: 6px 0 0;
  color: var(--gray-500);
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.template-section {
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid var(--gray-200);
  border-radius: 14px;
  background: var(--gray-50);
}

.template-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.template-section-head h3 {
  margin: 0;
  font-size: 14px;
  color: var(--gray-900);
}

.template-section-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--gray-500);
}

.template-list {
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

.compose-actions {
  display: flex;
  justify-content: flex-end;
}

.loading-state,
.empty-state {
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 12px;
  color: var(--gray-500);
}

.intent-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 12px;
  margin-bottom: 16px;
}

.intent-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.intent-item label {
  font-size: 13px;
  color: var(--gray-600);
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 18px;
}

.empty-hint {
  font-size: 13px;
  color: var(--gray-500);
}

.workers-section {
  border-top: 1px solid var(--gray-200);
  padding-top: 18px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 600;
  color: var(--gray-800);
}

.worker-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.worker-card {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 14px;
  background: var(--gray-50);
}

.worker-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.worker-top h3 {
  margin: 0 0 4px;
  font-size: 15px;
  color: var(--gray-900);
}

.worker-top p {
  margin: 0;
  color: var(--gray-600);
  font-size: 13px;
}

.worker-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--gray-600);
}

.deploy-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 16px;
  background: var(--gray-0);
  padding: 18px 20px;
}

.deploy-banner h3 {
  margin: 0;
  color: var(--gray-900);
}

.deploy-banner p {
  margin: 6px 0 0;
  color: var(--gray-500);
}

.deploy-actions {
  display: flex;
  gap: 10px;
}

@media (max-width: 1080px) {
  .builder-grid {
    grid-template-columns: 1fr;
  }

  .intent-strip,
  .resource-grid,
  .template-list {
    grid-template-columns: 1fr;
  }

  .builder-header,
  .deploy-banner {
    flex-direction: column;
    align-items: stretch;
  }

  .header-right,
  .deploy-actions {
    justify-content: flex-end;
  }
}
</style>
