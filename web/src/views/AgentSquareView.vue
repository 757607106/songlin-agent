<template>
  <div class="agent-square">
    <!-- 顶部标题栏 -->
    <div class="square-header">
      <div class="header-left">
        <LayoutGrid :size="28" class="header-icon" />
        <div>
          <h1>智能体广场</h1>
          <p class="header-desc">创建与管理你的自定义智能体</p>
        </div>
      </div>
      <a-button type="primary" size="large" @click="showCreator = true" class="create-btn">
        <Plus :size="16" />
        创建智能体
      </a-button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <a-spin size="large" />
    </div>

    <template v-else>
      <!-- 内置智能体区 -->
      <div class="section" v-if="builtinAgents.length > 0">
        <h2 class="section-title">
          <Sparkles :size="18" />
          内置智能体
        </h2>
        <div class="agent-grid">
          <div v-for="agent in builtinAgents" :key="agent.id" class="agent-card builtin-card">
            <div class="card-header">
              <div class="card-avatar builtin-avatar">
                <Bot :size="24" />
              </div>
              <div class="card-mode-tag mode-builtin">内置</div>
            </div>
            <div class="card-body">
              <h3 class="card-title">{{ agent.name }}</h3>
              <p class="card-desc">{{ agent.description || '暂无描述' }}</p>
              <div class="card-caps" v-if="agent.capabilities && agent.capabilities.length > 0">
                <a-tag
                  v-for="cap in agent.capabilities.slice(0, 3)"
                  :key="cap"
                  size="small"
                  class="cap-tag"
                >
                  {{ cap }}
                </a-tag>
              </div>
            </div>
            <div class="card-footer">
              <a-button type="primary" size="small" @click="goChatBuiltin(agent)">
                <MessageCircle :size="14" />
                对话
              </a-button>
              <a-button size="small" @click="editBuiltinAgent(agent)">
                <Settings :size="14" />
                配置
              </a-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 我的自定义智能体区 -->
      <div class="section">
        <h2 class="section-title">
          <Puzzle :size="18" />
          我的自定义智能体
        </h2>

        <!-- 空状态 -->
        <div v-if="customAgents.length === 0" class="empty-state">
          <div class="empty-icon">
            <Plus :size="32" />
          </div>
          <p>还没有自定义智能体，点击上方按钮创建</p>
        </div>

        <!-- 自定义智能体卡片网格 -->
        <div v-else class="agent-grid">
          <div v-for="agent in customAgents" :key="agent.id" class="agent-card">
            <div class="card-header">
              <div class="card-avatar">
                <component :is="getModeIcon(agent)" :size="24" />
              </div>
              <div class="card-mode-tag" :class="getModeClass(agent)">
                {{ getModeLabel(agent) }}
              </div>
            </div>
            <div class="card-body">
              <h3 class="card-title">{{ agent.name }}</h3>
              <p class="card-desc">{{ agent.description || '暂无描述' }}</p>
              <div class="card-meta" v-if="getSubagentCount(agent) > 0">
                <Users :size="14" />
                <span>{{ getSubagentCount(agent) }} 个子智能体</span>
              </div>
            </div>
            <div class="card-footer">
              <a-button type="primary" size="small" @click="goChat(agent)">
                <MessageCircle :size="14" />
                对话
              </a-button>
              <a-button size="small" @click="editCustomAgent(agent)">
                <Pencil :size="14" />
                编辑
              </a-button>
              <a-popconfirm
                title="确定删除这个智能体？"
                ok-text="删除"
                cancel-text="取消"
                @confirm="deleteAgent(agent)"
              >
                <a-button size="small" danger>
                  <Trash2 :size="14" />
                </a-button>
              </a-popconfirm>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 创建/编辑弹窗 -->
    <AgentCreatorModal
      :visible="showCreator"
      :editData="editingAgent"
      @close="closeCreator"
      @submit="handleSubmit"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  LayoutGrid,
  Plus,
  Bot,
  Users,
  Zap,
  Pencil,
  Trash2,
  MessageCircle,
  Sparkles,
  Puzzle,
  Settings
} from 'lucide-vue-next'
import { agentApi } from '@/apis/agent_api'
import { useAgentStore } from '@/stores/agent'
import { useChatUIStore } from '@/stores/chatUI'
import AgentCreatorModal from '@/components/AgentCreatorModal.vue'

const router = useRouter()
const agentStore = useAgentStore()
const chatUIStore = useChatUIStore()
const DYNAMIC_AGENT_ID = 'DynamicAgent'

const loading = ref(false)
const builtinAgents = ref([])
const customAgents = ref([])
const showCreator = ref(false)
const editingAgent = ref(null)

const fetchAll = async () => {
  loading.value = true
  try {
    const [agentsRes, configsRes] = await Promise.all([
      agentApi.getAgents(),
      agentApi.getAgentConfigs(DYNAMIC_AGENT_ID).catch(() => ({ configs: [] }))
    ])

    const allAgents = agentsRes.agents || agentsRes || []
    builtinAgents.value = allAgents.filter((a) => a.id !== DYNAMIC_AGENT_ID)

    const configs = configsRes.configs || configsRes || []
    const detailed = await Promise.all(
      configs.map((c) =>
        agentApi
          .getAgentConfigProfile(DYNAMIC_AGENT_ID, c.id)
          .then((res) => res.config || res)
          .catch(() => c)
      )
    )
    customAgents.value = detailed
  } catch (e) {
    console.error('加载智能体失败:', e)
    message.error('加载智能体列表失败')
  } finally {
    loading.value = false
  }
}

const getModeIcon = (agent) => {
  const mode = agent.config_json?.multi_agent_mode || 'disabled'
  if (mode === 'supervisor') return Users
  if (mode === 'deep_agents') return Zap
  return Bot
}

const getModeClass = (agent) => {
  const mode = agent.config_json?.multi_agent_mode || 'disabled'
  return `mode-${mode}`
}

const getModeLabel = (agent) => {
  const mode = agent.config_json?.multi_agent_mode || 'disabled'
  if (mode === 'supervisor') return 'Supervisor'
  if (mode === 'deep_agents') return 'Deep Agents'
  return '单智能体'
}

const getSubagentCount = (agent) => {
  return (agent.config_json?.subagents || []).length
}

// === 导航操作 ===

const goChatBuiltin = (agent) => {
  router.push(`/agent/${agent.id}`)
}

const goChat = (agent) => {
  router.push({
    path: `/agent/${DYNAMIC_AGENT_ID}`,
    query: { config_id: agent.id }
  })
}

// 编辑内置智能体 — 跳转到管理页面并打开配置侧边栏
const editBuiltinAgent = async (agent) => {
  await agentStore.selectAgent(agent.id)
  chatUIStore.isConfigSidebarOpen = true
  router.push('/agent')
}

// 编辑自定义智能体 — 打开 Creator Modal 修改模式/子智能体
const editCustomAgent = (agent) => {
  editingAgent.value = agent
  showCreator.value = true
}

const closeCreator = () => {
  showCreator.value = false
  editingAgent.value = null
}

const handleSubmit = async ({ payload, configId }) => {
  if (!payload) {
    await fetchAll()
    return
  }
  try {
    if (configId) {
      await agentApi.updateAgentConfigProfile(DYNAMIC_AGENT_ID, configId, payload)
      message.success('智能体更新成功')
    } else {
      await agentApi.createAgentConfigProfile(DYNAMIC_AGENT_ID, payload)
      message.success('智能体创建成功')
    }
    closeCreator()
    await fetchAll()
  } catch (e) {
    console.error('保存智能体失败:', e)
    message.error('保存失败: ' + (e.message || '未知错误'))
  }
}

const deleteAgent = async (agent) => {
  try {
    await agentApi.deleteAgentConfigProfile(DYNAMIC_AGENT_ID, agent.id)
    message.success('已删除')
    await fetchAll()
  } catch (e) {
    console.error('删除失败:', e)
    message.error('删除失败')
  }
}

onMounted(() => {
  fetchAll()
})
</script>

<style scoped>
.agent-square {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  padding: 32px 40px;
  background: var(--color-bg-layout, #f5f5f5);
}

.square-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 32px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-icon {
  color: var(--color-primary, #1677ff);
}

.header-left h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text, #333);
}

.header-desc {
  margin: 2px 0 0 0;
  font-size: 14px;
  color: var(--color-text-secondary, #666);
}

.create-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  border-radius: 10px;
  font-weight: 500;
}

/* Sections */
.section {
  margin-bottom: 36px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px 0;
  color: var(--color-text, #333);
}

/* Loading */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}

/* Empty */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 150px;
  text-align: center;
}

.empty-icon {
  width: 64px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: var(--color-fill-quaternary, #f0f0f0);
  color: var(--color-text-tertiary, #bbb);
  margin-bottom: 12px;
}

.empty-state p {
  margin: 0;
  color: var(--color-text-secondary, #999);
  font-size: 14px;
}

/* Grid */
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.agent-card {
  background: var(--color-bg-container, #fff);
  border-radius: 14px;
  border: 1px solid var(--color-border, #e8e8e8);
  overflow: hidden;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
}

.agent-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 12px;
}

.card-avatar {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: var(--color-primary, #1677ff);
  color: #fff;
}

.builtin-avatar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.card-mode-tag {
  font-size: 12px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: 20px;
}

.card-mode-tag.mode-builtin {
  background: linear-gradient(135deg, #e8e0f0 0%, #dde4f5 100%);
  color: #764ba2;
}

.card-mode-tag.mode-disabled {
  background: #f0f0f0;
  color: #666;
}

.card-mode-tag.mode-supervisor {
  background: #e6f4ff;
  color: #1677ff;
}

.card-mode-tag.mode-deep_agents {
  background: #f6ffed;
  color: #52c41a;
}

.card-body {
  padding: 0 20px;
  flex: 1;
}

.card-title {
  margin: 0 0 6px 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text, #333);
}

.card-desc {
  margin: 0 0 8px 0;
  font-size: 13px;
  color: var(--color-text-secondary, #999);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-caps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
}

.cap-tag {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 4px;
  line-height: 20px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-tertiary, #bbb);
  margin-bottom: 4px;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--color-border-secondary, #f0f0f0);
}

.card-footer .ant-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}
</style>
