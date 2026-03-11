<template>
  <div class="agent-detail-page">
    <!-- 顶部导航栏 -->
    <div class="detail-header">
      <div class="header-left">
        <a-button type="text" class="back-btn" @click="goBack">
          <ArrowLeft :size="18" />
          <span>返回广场</span>
        </a-button>
        <div class="header-divider"></div>
        <h1 class="agent-title">{{ agentData?.name || '加载中...' }}</h1>
        <a-tag v-if="isBuiltin" class="type-tag builtin">内置</a-tag>
        <a-tag v-else class="type-tag custom">{{ modeLabel }}</a-tag>
      </div>
      <div class="header-right">
        <a-button size="large" @click="goChat" :disabled="!agentData">
          <MessageCircle :size="16" />
          对话
        </a-button>
        <a-button
          v-if="!isEditing && canEdit"
          type="primary"
          size="large"
          @click="enterEditMode"
          :disabled="!agentData"
        >
          <Pencil :size="16" />
          编辑
        </a-button>
        <template v-else>
          <a-button size="large" @click="cancelEdit">取消</a-button>
          <a-button type="primary" size="large" @click="saveChanges" :loading="saving">
            <Check :size="16" />
            保存
          </a-button>
        </template>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-container">
      <a-spin size="large" />
    </div>

    <!-- 详情内容 -->
    <div v-else-if="agentData" class="detail-content">
      <!-- 基本信息卡片 -->
      <div class="info-card">
        <div class="card-header">
          <div class="card-icon">
            <component :is="modeIcon" :size="24" />
          </div>
          <h2>基本信息</h2>
        </div>
        <div class="card-body">
          <div class="info-grid">
            <div class="info-item">
              <label>名称</label>
              <template v-if="isEditing && !isBuiltin">
                <a-input v-model:value="editForm.name" placeholder="智能体名称" />
              </template>
              <span v-else class="info-value">{{ agentData.name }}</span>
            </div>
            <div class="info-item">
              <label>描述</label>
              <template v-if="isEditing && !isBuiltin">
                <a-textarea
                  v-model:value="editForm.description"
                  placeholder="智能体描述"
                  :rows="2"
                />
              </template>
              <span v-else class="info-value desc">
                {{ agentData.description || '暂无描述' }}
              </span>
            </div>
            <div class="info-item" v-if="isPlatformCustom">
              <label>目标</label>
              <template v-if="isEditing">
                <a-textarea v-model:value="editForm.goal" placeholder="智能体目标" :rows="2" />
              </template>
              <span v-else class="info-value desc">
                {{ configData.goal || '暂无目标' }}
              </span>
            </div>
            <div class="info-item" v-if="isPlatformCustom">
              <label>任务范围</label>
              <template v-if="isEditing">
                <a-textarea v-model:value="editForm.task_scope" placeholder="任务范围" :rows="2" />
              </template>
              <span v-else class="info-value desc">
                {{ configData.task_scope || '未设置' }}
              </span>
            </div>
            <div class="info-item" v-if="!isBuiltin">
              <label>模式</label>
              <template v-if="isEditing">
                <a-select v-model:value="editForm.multi_agent_mode" class="mode-select">
                  <a-select-option value="disabled">单智能体</a-select-option>
                  <a-select-option value="supervisor">Supervisor</a-select-option>
                  <a-select-option value="deep_agents">Deep Agents</a-select-option>
                  <a-select-option value="swarm">Swarm</a-select-option>
                </a-select>
              </template>
              <span v-else class="info-value">
                <a-tag :color="modeColor">{{ modeLabel }}</a-tag>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 配置详情卡片 -->
      <div class="info-card">
        <div class="card-header">
          <Settings :size="20" />
          <h2>配置详情</h2>
        </div>
        <div class="card-body">
          <div class="config-section">
            <label>系统提示词</label>
            <template v-if="isEditing">
              <a-textarea
                v-model:value="editForm.system_prompt"
                placeholder="指导智能体的行为和角色"
                :rows="4"
              />
            </template>
            <div v-else class="prompt-preview">
              {{ configData.system_prompt || '未设置' }}
            </div>
          </div>

          <div v-if="isPlatformCustom" class="config-section">
            <label>Supervisor 提示词</label>
            <template v-if="isEditing">
              <a-textarea
                v-model:value="editForm.supervisor_prompt"
                placeholder="可选：定义多 Worker 的路由与协作策略"
                :rows="3"
              />
            </template>
            <div v-else class="prompt-preview">
              {{ configData.supervisor_prompt || '未设置' }}
            </div>
          </div>

          <div class="config-row">
            <div class="config-section half">
              <label>工具</label>
              <template v-if="isEditing">
                <a-select
                  v-model:value="editForm.tools"
                  mode="multiple"
                  placeholder="选择工具"
                  :options="toolOptions"
                  allow-clear
                  class="full-width"
                />
              </template>
              <div v-else class="tags-preview">
                <a-tag v-for="tool in configData.tools || []" :key="tool">{{ tool }}</a-tag>
                <span v-if="!configData.tools?.length" class="empty-hint">未配置</span>
              </div>
            </div>
            <div class="config-section half">
              <label>知识库</label>
              <template v-if="isEditing">
                <a-select
                  v-model:value="editForm.knowledges"
                  mode="multiple"
                  placeholder="选择知识库"
                  :options="knowledgeOptions"
                  allow-clear
                  class="full-width"
                />
              </template>
              <div v-else class="tags-preview">
                <a-tag v-for="kb in configData.knowledges || []" :key="kb" color="green">
                  {{ kb }}
                </a-tag>
                <span v-if="!configData.knowledges?.length" class="empty-hint">未配置</span>
              </div>
            </div>
          </div>

          <div class="config-row">
            <div class="config-section half">
              <label>MCP 服务器</label>
              <template v-if="isEditing">
                <a-select
                  v-model:value="editForm.mcps"
                  mode="multiple"
                  placeholder="选择 MCP"
                  :options="mcpOptions"
                  allow-clear
                  class="full-width"
                />
              </template>
              <div v-else class="tags-preview">
                <a-tag v-for="mcp in configData.mcps || []" :key="mcp" color="purple">
                  {{ mcp }}
                </a-tag>
                <span v-if="!configData.mcps?.length" class="empty-hint">未配置</span>
              </div>
            </div>
            <div class="config-section half">
              <label>技能</label>
              <template v-if="isEditing">
                <a-select
                  v-model:value="editForm.skills"
                  mode="multiple"
                  placeholder="选择技能"
                  :options="skillOptions"
                  allow-clear
                  class="full-width"
                />
              </template>
              <div v-else class="tags-preview">
                <a-tag v-for="skill in configData.skills || []" :key="skill" color="orange">
                  {{ skill }}
                </a-tag>
                <span v-if="!configData.skills?.length" class="empty-hint">未配置</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 子智能体卡片 (仅多智能体模式) -->
      <div v-if="hasSubagents" class="info-card">
        <div class="card-header">
          <Users :size="20" />
          <h2>子智能体 ({{ (isEditing ? editForm.subagents || [] : subagents).length }})</h2>
        </div>
        <div class="card-body">
          <!-- 编辑模式：使用 SubagentEditor -->
          <SubagentEditor v-if="isEditing" v-model="editForm.subagents" />
          <!-- 只读模式：卡片展示 -->
          <div v-else class="subagents-grid">
            <div v-for="(agent, idx) in subagents" :key="idx" class="subagent-card">
              <div class="subagent-header">
                <Bot :size="18" />
                <span class="subagent-name">{{ agent.name || `子智能体 ${idx + 1}` }}</span>
              </div>
              <p class="subagent-desc">{{ agent.description || '暂无描述' }}</p>
              <div class="subagent-tags">
                <a-tag v-for="tool in (agent.tools || []).slice(0, 3)" :key="tool" size="small">
                  {{ tool }}
                </a-tag>
                <span v-if="(agent.tools || []).length > 3" class="more-hint">
                  +{{ agent.tools.length - 3 }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 示例问题 -->
      <div v-if="examples.length > 0 || isEditing" class="info-card">
        <div class="card-header">
          <HelpCircle :size="20" />
          <h2>示例问题</h2>
        </div>
        <div class="card-body">
          <template v-if="isEditing">
            <div class="examples-editor">
              <div v-for="(ex, idx) in editForm.examples" :key="idx" class="example-row">
                <a-input v-model:value="editForm.examples[idx]" placeholder="输入示例问题" />
                <a-button type="text" danger size="small" @click="editForm.examples.splice(idx, 1)">
                  <Trash2 :size="14" />
                </a-button>
              </div>
              <a-button
                type="dashed"
                size="small"
                @click="editForm.examples.push('')"
                :disabled="editForm.examples.length >= 5"
              >
                <Plus :size="14" /> 添加示例
              </a-button>
            </div>
          </template>
          <template v-else>
            <div class="examples-list">
              <div v-for="(ex, idx) in examples" :key="idx" class="example-item">
                <span class="example-icon">💡</span>
                {{ ex }}
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 危险操作区 (仅自定义智能体) -->
      <div v-if="!isBuiltin" class="info-card danger-zone">
        <div class="card-header">
          <AlertTriangle :size="20" />
          <h2>危险操作</h2>
        </div>
        <div class="card-body">
          <div class="danger-item">
            <div class="danger-info">
              <h4>删除智能体</h4>
              <p>删除后无法恢复，所有相关配置将被清除。</p>
            </div>
            <a-popconfirm
              title="确定要删除这个智能体吗？"
              ok-text="删除"
              cancel-text="取消"
              @confirm="deleteAgent"
            >
              <a-button danger :loading="deleting">删除智能体</a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <p>未找到智能体信息</p>
      <a-button type="primary" @click="goBack">返回广场</a-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeft,
  MessageCircle,
  Pencil,
  Check,
  Settings,
  Users,
  Bot,
  Zap,
  Shuffle,
  Plus,
  Trash2,
  HelpCircle,
  AlertTriangle
} from 'lucide-vue-next'
import { agentApi } from '@/apis/agent_api'
import { agentDesignApi } from '@/apis/agent_design_api'
import { useDatabaseStore } from '@/stores/database'
import SubagentEditor from '@/components/SubagentEditor.vue'
import {
  AGENT_PLATFORM_AGENT_ID,
  isAgentPlatformConfig,
  normalizeAgentPlatformConfig
} from '@/utils/agentPlatformConfig'

const route = useRoute()
const router = useRouter()
const databaseStore = useDatabaseStore()

// 状态
const loading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const isEditing = ref(false)
const agentData = ref(null)
const editForm = ref({})
const builtinConfig = ref({})

// 选项数据
const toolOptions = ref([])
const knowledgeOptions = ref([])
const mcpOptions = ref([])
const skillOptions = ref([])

// 计算属性
const agentType = computed(() => route.params.type) // 'builtin' | 'custom'
const agentId = computed(() => route.params.id)
const isBuiltin = computed(() => agentType.value === 'builtin')
const customRuntimeAgentId = computed(() => route.query.runtime_agent_id || AGENT_PLATFORM_AGENT_ID)
const isPlatformCustom = computed(
  () => !isBuiltin.value && customRuntimeAgentId.value === AGENT_PLATFORM_AGENT_ID
)
const canEdit = computed(() => true)

const configData = computed(() => {
  if (isBuiltin.value) {
    return normalizeBuiltinConfig(builtinConfig.value || {})
  }
  return normalizePlatformConfig(agentData.value?.config_json || {})
})

const modeValue = computed(() => configData.value?.multi_agent_mode || 'disabled')

const modeLabel = computed(() => {
  const labels = {
    disabled: '单智能体',
    supervisor: 'Supervisor',
    deep_agents: 'Deep Agents',
    swarm: 'Swarm'
  }
  return labels[modeValue.value] || '单智能体'
})

const modeColor = computed(() => {
  const colors = {
    disabled: 'default',
    supervisor: 'blue',
    deep_agents: 'green',
    swarm: 'purple'
  }
  return colors[modeValue.value] || 'default'
})

const modeIcon = computed(() => {
  if (modeValue.value === 'supervisor') return Users
  if (modeValue.value === 'deep_agents') return Zap
  if (modeValue.value === 'swarm') return Shuffle
  return Bot
})

const hasSubagents = computed(() => {
  if (isEditing.value) {
    if (isBuiltin.value) return false
    const editSubagents = Array.isArray(editForm.value?.subagents) ? editForm.value.subagents : []
    return (editForm.value?.multi_agent_mode || 'disabled') !== 'disabled' || editSubagents.length > 0
  }
  return modeValue.value !== 'disabled' || subagents.value.length > 0
})

const subagents = computed(() => configData.value?.subagents || [])
const examples = computed(() => agentData.value?.examples || [])
const platformConfig = computed(() =>
  isPlatformCustom.value ? agentData.value?.config_json || {} : {}
)
const platformBlueprint = computed(() =>
  platformConfig.value?.blueprint && typeof platformConfig.value.blueprint === 'object'
    ? platformConfig.value.blueprint
    : null
)

const normalizeBuiltinConfig = (config) => {
  if (!config || typeof config !== 'object') return {}
  return config
}

const normalizePlatformConfig = (config) => {
  return normalizeAgentPlatformConfig(config) || {}
}

// 方法
const fetchAgentData = async () => {
  loading.value = true
  try {
    if (isBuiltin.value) {
      // 获取内置智能体详情
      const detail = await agentApi.getAgentDetail(agentId.value)
      agentData.value = detail
      const configRes = await agentApi.getAgentConfig(agentId.value)
      builtinConfig.value = configRes?.config || {}
    } else {
      // 获取自定义智能体配置
      const res = await agentApi.getAgentConfigProfile(customRuntimeAgentId.value, agentId.value)
      const profile = res.config || res
      if (!isAgentPlatformConfig(profile?.config_json || {})) {
        throw new Error('仅支持新的 agent_platform_v2 自定义智能体配置')
      }
      agentData.value = profile
      builtinConfig.value = {}
    }
  } catch (e) {
    console.error('获取智能体信息失败:', e)
    message.error('获取智能体信息失败')
  } finally {
    loading.value = false
  }
}

const fetchOptions = async () => {
  try {
    const detail = await agentApi.getAgentDetail(AGENT_PLATFORM_AGENT_ID)
    const items = detail.configurable_items || {}

    if (items.tools) {
      toolOptions.value = (items.tools.options || []).map((t) => ({
        label: t.name || t,
        value: t.name || t
      }))
    }

    if (items.knowledges?.options?.length > 0) {
      knowledgeOptions.value = items.knowledges.options.map((k) => ({
        label: typeof k === 'string' ? k : k.name,
        value: typeof k === 'string' ? k : k.name
      }))
    } else {
      await databaseStore.loadDatabases()
      knowledgeOptions.value = (databaseStore.databases || []).map((db) => ({
        label: db.name,
        value: db.name
      }))
    }

    if (items.mcps) {
      mcpOptions.value = (items.mcps.options || []).map((m) => ({
        label: typeof m === 'string' ? m : m.name,
        value: typeof m === 'string' ? m : m.name
      }))
    }

    if (items.skills) {
      skillOptions.value = (items.skills.options || []).map((s) => ({
        label: typeof s === 'string' ? s : s.name || s.id,
        value: typeof s === 'string' ? s : s.id || s.name
      }))
    }
  } catch (e) {
    console.error('加载选项失败:', e)
  }
}

const enterEditMode = () => {
  // 复制数据到编辑表单
  if (isBuiltin.value) {
    editForm.value = {
      name: agentData.value?.name || '',
      description: agentData.value?.description || '',
      multi_agent_mode: 'disabled',
      goal: '',
      task_scope: '',
      system_prompt: configData.value?.system_prompt || '',
      supervisor_prompt: '',
      tools: configData.value?.tools || [],
      knowledges: configData.value?.knowledges || [],
      mcps: configData.value?.mcps || [],
      skills: configData.value?.skills || [],
      subagents: [],
      examples: [...(agentData.value?.examples || [])]
    }
  } else {
    if (isPlatformCustom.value) {
      const blueprint = platformBlueprint.value || {}
      const normalizedWorkers = JSON.parse(JSON.stringify(configData.value?.subagents || []))
      editForm.value = {
        name: agentData.value?.name || blueprint.name || '',
        description: agentData.value?.description || blueprint.description || '',
        multi_agent_mode: configData.value?.multi_agent_mode || 'disabled',
        goal: blueprint.goal || configData.value?.goal || '',
        task_scope: blueprint.task_scope || configData.value?.task_scope || '',
        system_prompt: blueprint.system_prompt || configData.value?.system_prompt || '',
        supervisor_prompt: blueprint.supervisor_prompt || configData.value?.supervisor_prompt || '',
        default_model: blueprint.default_model || configData.value?.default_model || '',
        tools: blueprint.tools || configData.value?.tools || [],
        knowledges: blueprint.knowledge_ids || configData.value?.knowledges || [],
        mcps: blueprint.mcps || configData.value?.mcps || [],
        skills: blueprint.skills || configData.value?.skills || [],
        subagents: normalizedWorkers,
        examples: [...(agentData.value?.examples || [])]
      }
    } else {
      message.error('当前自定义智能体不是新平台配置，无法在此编辑')
      return
    }
  }
  isEditing.value = true
}

const cancelEdit = () => {
  isEditing.value = false
  editForm.value = {}
}

const saveChanges = async () => {
  if (!editForm.value.name?.trim()) {
    message.warning('请输入智能体名称')
    return
  }

  saving.value = true
  try {
    if (isBuiltin.value) {
      // 保存内置智能体配置
      await agentApi.saveAgentConfig(agentId.value, {
        system_prompt: editForm.value.system_prompt,
        tools: editForm.value.tools,
        knowledges: editForm.value.knowledges,
        mcps: editForm.value.mcps,
        skills: editForm.value.skills
      })
    } else {
      if (isPlatformCustom.value) {
        const blueprint = buildPlatformBlueprintPayload(editForm.value)
        const validation = await agentDesignApi.validate({ blueprint })
        if (!validation.valid) {
          message.error(validation.errors?.[0] || 'Blueprint 校验失败')
          return
        }
        const compiled = await agentDesignApi.compile({ blueprint })
        await agentApi.updateAgentConfigProfile(customRuntimeAgentId.value, agentId.value, {
          name: editForm.value.name.trim(),
          description: editForm.value.description?.trim() || '',
          examples: editForm.value.examples.filter((e) => e?.trim()),
          config_json: {
            version: 'agent_platform_v2',
            blueprint,
            spec: compiled.spec
          }
        })
      } else {
        message.error('当前自定义智能体不是新平台配置，无法保存')
        return
      }
    }

    message.success('保存成功')
    isEditing.value = false
    await fetchAgentData()
  } catch (e) {
    console.error('保存失败:', e)
    message.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

const buildPlatformBlueprintPayload = (formState) => {
  const modeMap = {
    disabled: 'single',
    supervisor: 'supervisor',
    deep_agents: 'deep_agents',
    swarm: 'swarm_handoff'
  }
  return {
    name: formState.name.trim(),
    description: formState.description?.trim() || '',
    goal: formState.goal?.trim() || formState.description?.trim() || formState.name.trim(),
    task_scope: formState.task_scope?.trim() || '',
    execution_mode: modeMap[formState.multi_agent_mode] || 'single',
    system_prompt: formState.system_prompt?.trim() || '',
    supervisor_prompt: formState.supervisor_prompt?.trim() || '',
    default_model: formState.default_model || null,
    tools: [...(formState.tools || [])],
    knowledge_ids: [...(formState.knowledges || [])],
    mcps: [...(formState.mcps || [])],
    skills: [...(formState.skills || [])],
    max_parallel_workers:
      formState.multi_agent_mode === 'disabled' ? 1 : Math.max(1, (formState.subagents || []).length || 1),
    max_dynamic_workers:
      formState.multi_agent_mode === 'deep_agents' || formState.multi_agent_mode === 'swarm'
        ? Math.max(1, (formState.subagents || []).length || 1)
        : 0,
    workers:
      formState.multi_agent_mode === 'disabled'
        ? []
        : (formState.subagents || []).map((agent) => ({
            key: agent.key || null,
            name: (agent.name || '').trim(),
            description: agent.description || '',
            objective: agent.objective || agent.description || '',
            system_prompt: agent.system_prompt || '',
            kind: agent.kind || 'reasoning',
            model: agent.model || null,
            tools: [...(agent.tools || [])],
            knowledge_ids: [...(agent.knowledges || [])],
            mcps: [...(agent.mcps || [])],
            skills: [...(agent.skills || [])],
            depends_on: [...(agent.depends_on || [])],
            allowed_next: [...(agent.allowed_next || [])]
          }))
  }
}

const deleteAgent = async () => {
  deleting.value = true
  try {
    await agentApi.deleteAgentConfigProfile(customRuntimeAgentId.value, agentId.value)
    message.success('删除成功')
    router.push('/agent-square')
  } catch (e) {
    console.error('删除失败:', e)
    message.error('删除失败')
  } finally {
    deleting.value = false
  }
}

const goBack = () => {
  router.push('/agent-square')
}

const goChat = () => {
  if (isBuiltin.value) {
    router.push(`/agent/${agentId.value}`)
  } else {
    router.push({
      path: `/agent/${customRuntimeAgentId.value}`,
      query: { config_id: agentId.value }
    })
  }
}

// 生命周期
onMounted(() => {
  fetchAgentData()
  fetchOptions()
})

watch(
  () => route.fullPath,
  () => {
    if (route.params.id) {
      isEditing.value = false
      fetchAgentData()
    }
  }
)
</script>

<style scoped lang="less">
.agent-detail-page {
  min-height: 100%;
  background: var(--gray-100);
  padding: 0;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 32px;
  background: var(--gray-0);
  border-bottom: 1px solid var(--gray-200);
  position: sticky;
  top: 0;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--gray-600);
  font-weight: 500;

  &:hover {
    color: var(--main-600);
  }
}

.header-divider {
  width: 1px;
  height: 24px;
  background: var(--gray-300);
}

.agent-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--gray-900);
}

.type-tag {
  margin-left: 8px;
  font-size: 12px;
  border-radius: 4px;

  &.builtin {
    background: linear-gradient(135deg, #e8e0f0 0%, #dde4f5 100%);
    color: #764ba2;
    border: none;
  }

  &.custom {
    background: var(--main-50);
    color: var(--main-700);
    border: none;
  }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;

  .ant-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    border-radius: 8px;
  }
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}

.detail-content {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 32px 48px;
}

.info-card {
  background: var(--gray-0);
  border-radius: 12px;
  border: 1px solid var(--gray-200);
  margin-bottom: 16px;
  overflow: hidden;

  &.danger-zone {
    border-color: var(--color-error-100);

    .card-header {
      background: var(--color-error-50);
      color: var(--color-error-700);

      h2 {
        color: var(--color-error-700);
      }
    }
  }
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  background: var(--gray-50);
  border-bottom: 1px solid var(--gray-200);

  h2 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: var(--gray-800);
    flex: 1;
  }

  .card-icon {
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    background: var(--main-500);
    color: white;
  }
}

.card-body {
  padding: 20px;
}

.info-grid {
  display: grid;
  gap: 16px;
}

.info-item {
  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--gray-500);
    margin-bottom: 6px;
  }

  .info-value {
    font-size: 14px;
    color: var(--gray-900);

    &.desc {
      color: var(--gray-600);
      line-height: 1.6;
    }
  }
}

.mode-select {
  width: 200px;
}

.config-section {
  margin-bottom: 16px;

  &:last-child {
    margin-bottom: 0;
  }

  &.half {
    flex: 1;
  }

  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--gray-500);
    margin-bottom: 8px;
  }
}

.config-row {
  display: flex;
  gap: 20px;
  margin-bottom: 16px;

  &:last-child {
    margin-bottom: 0;
  }
}

.prompt-preview {
  padding: 12px 14px;
  background: var(--gray-50);
  border-radius: 8px;
  font-size: 13px;
  color: var(--gray-700);
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 150px;
  overflow-y: auto;
}

.tags-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 32px;
  align-items: center;

  .empty-hint {
    font-size: 13px;
    color: var(--gray-400);
  }
}

.subagents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.subagent-card {
  padding: 14px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--gray-50);
}

.subagent-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--main-600);
}

.subagent-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--gray-900);
}

.subagent-desc {
  font-size: 13px;
  color: var(--gray-600);
  margin: 0 0 10px 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.subagent-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.more-hint {
  font-size: 12px;
  color: var(--gray-500);
}

.examples-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.example-row {
  display: flex;
  gap: 8px;
  align-items: center;

  .ant-input {
    flex: 1;
  }
}

.examples-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.example-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  background: var(--gray-50);
  border-radius: 8px;
  font-size: 13px;
  color: var(--gray-700);
}

.example-icon {
  flex-shrink: 0;
}

.danger-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.danger-info {
  h4 {
    margin: 0 0 4px 0;
    font-size: 14px;
    font-weight: 600;
    color: var(--gray-900);
  }

  p {
    margin: 0;
    font-size: 13px;
    color: var(--gray-500);
  }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  gap: 16px;
  color: var(--gray-500);
}

.full-width {
  width: 100%;
}

@media (max-width: 768px) {
  .detail-header {
    padding: 12px 16px;
    flex-wrap: wrap;
    gap: 12px;
  }

  .detail-content {
    padding: 16px;
  }

  .config-row {
    flex-direction: column;
  }

  .subagents-grid {
    grid-template-columns: 1fr;
  }
}
</style>
