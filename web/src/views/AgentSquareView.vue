<template>
  <div class="agent-square">
    <!-- 顶部标题栏 -->
    <div class="square-header">
      <div class="header-left">
        <LayoutGrid :size="28" class="header-icon" />
        <div>
          <h1>智能体广场</h1>
          <p class="header-desc">发现与管理你的智能体</p>
        </div>
      </div>
      <a-space>
        <a-button size="large" @click="goTeamBuilder" class="action-btn">
          <Users :size="16" />
          聊天组队
        </a-button>
        <a-button type="primary" size="large" @click="showCreator = true" class="action-btn">
          <Plus :size="16" />
          创建智能体
        </a-button>
      </a-space>
    </div>

    <!-- 筛选和搜索栏 -->
    <div class="filter-bar">
      <div class="filter-tabs">
        <div
          class="filter-tab"
          :class="{ active: activeFilter === 'all' }"
          @click="activeFilter = 'all'"
        >
          全部
          <span class="count">{{ allAgents.length }}</span>
        </div>
        <div
          class="filter-tab"
          :class="{ active: activeFilter === 'builtin' }"
          @click="activeFilter = 'builtin'"
        >
          内置
          <span class="count">{{ builtinAgents.length }}</span>
        </div>
        <div
          class="filter-tab"
          :class="{ active: activeFilter === 'custom' }"
          @click="activeFilter = 'custom'"
        >
          自定义
          <span class="count">{{ customAgents.length }}</span>
        </div>
      </div>
      <div class="search-box">
        <Search :size="16" class="search-icon" />
        <input v-model="searchQuery" type="text" placeholder="搜索智能体..." class="search-input" />
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <a-spin size="large" />
    </div>

    <!-- 智能体卡片网格 -->
    <template v-else>
      <div v-if="filteredAgents.length === 0" class="empty-state">
        <div class="empty-icon">
          <Bot :size="40" />
        </div>
        <p v-if="searchQuery">未找到匹配的智能体</p>
        <p v-else>暂无智能体</p>
        <a-button v-if="activeFilter === 'custom'" type="primary" @click="showCreator = true">
          创建第一个智能体
        </a-button>
      </div>

      <div v-else class="agents-grid">
        <!-- 智能体卡片 -->
        <div
          v-for="agent in filteredAgents"
          :key="agent._uid"
          class="agent-card"
          :class="{ builtin: agent._isBuiltin }"
          @click="openDetail(agent)"
        >
          <div class="card-header">
            <div class="card-avatar" :class="{ 'builtin-avatar': agent._isBuiltin }">
              <component :is="getAgentIcon(agent)" :size="22" />
            </div>
            <div class="card-badge" :class="getBadgeClass(agent)">
              {{ getBadgeText(agent) }}
            </div>
          </div>
          <div class="card-body">
            <h3 class="card-title">{{ agent.name }}</h3>
            <p class="card-desc">{{ agent.description || '暂无描述' }}</p>
            <div class="card-meta" v-if="getSubagentCount(agent) > 0">
              <Users :size="14" />
              <span>{{ getSubagentCount(agent) }} 个子智能体</span>
            </div>
            <div class="card-caps" v-if="agent.capabilities?.length > 0">
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
          <div class="card-footer" @click.stop>
            <a-button type="primary" size="small" @click.stop="goChat(agent)">
              <MessageCircle :size="14" />
              对话
            </a-button>
            <a-button size="small" @click.stop="openDetail(agent)">
              <Eye :size="14" />
              详情
            </a-button>
            <a-popconfirm
              v-if="!agent._isBuiltin"
              title="确定删除这个智能体？"
              ok-text="删除"
              cancel-text="取消"
              @confirm="deleteAgent(agent)"
            >
              <a-button size="small" danger @click.stop>
                <Trash2 :size="14" />
              </a-button>
            </a-popconfirm>
          </div>
        </div>

        <!-- 创建新智能体卡片 -->
        <div class="agent-card create-card" @click="showCreator = true">
          <div class="create-content">
            <div class="create-icon">
              <Plus :size="28" />
            </div>
            <span>创建新智能体</span>
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  LayoutGrid,
  Plus,
  Bot,
  Users,
  Zap,
  Trash2,
  MessageCircle,
  Search,
  Eye
} from 'lucide-vue-next'
import { agentApi } from '@/apis/agent_api'
import AgentCreatorModal from '@/components/AgentCreatorModal.vue'

const router = useRouter()
const DYNAMIC_AGENT_ID = 'DynamicAgent'

// 状态
const loading = ref(false)
const builtinAgents = ref([])
const customAgents = ref([])
const showCreator = ref(false)
const editingAgent = ref(null)
const activeFilter = ref('all')
const searchQuery = ref('')

// 计算属性
const allAgents = computed(() => {
  const builtin = builtinAgents.value.map((a) => ({
    ...a,
    _isBuiltin: true,
    _uid: `builtin_${a.id}`
  }))
  const custom = customAgents.value.map((a) => ({
    ...a,
    _isBuiltin: false,
    _uid: `custom_${a.id}`
  }))
  return [...builtin, ...custom]
})

const filteredAgents = computed(() => {
  let list = allAgents.value

  // 按类型筛选
  if (activeFilter.value === 'builtin') {
    list = list.filter((a) => a._isBuiltin)
  } else if (activeFilter.value === 'custom') {
    list = list.filter((a) => !a._isBuiltin)
  }

  // 搜索过滤
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase()
    list = list.filter(
      (a) => a.name?.toLowerCase().includes(query) || a.description?.toLowerCase().includes(query)
    )
  }

  return list
})

// 方法
const fetchAll = async () => {
  loading.value = true
  try {
    const [agentsRes, configsRes] = await Promise.all([
      agentApi.getAgents(),
      agentApi.getAgentConfigs(DYNAMIC_AGENT_ID).catch(() => ({ configs: [] }))
    ])

    const allAgentsList = agentsRes.agents || agentsRes || []
    builtinAgents.value = allAgentsList.filter((a) => a.id !== DYNAMIC_AGENT_ID)

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

const getAgentIcon = (agent) => {
  if (agent._isBuiltin) return Bot
  const mode = agent.config_json?.context?.multi_agent_mode || agent.config_json?.multi_agent_mode
  if (mode === 'supervisor') return Users
  if (mode === 'deep_agents') return Zap
  return Bot
}

const getBadgeClass = (agent) => {
  if (agent._isBuiltin) return 'badge-builtin'
  const mode = agent.config_json?.context?.multi_agent_mode || agent.config_json?.multi_agent_mode
  if (mode === 'supervisor') return 'badge-supervisor'
  if (mode === 'deep_agents') return 'badge-deep'
  return 'badge-single'
}

const getBadgeText = (agent) => {
  if (agent._isBuiltin) return '内置'
  const mode = agent.config_json?.context?.multi_agent_mode || agent.config_json?.multi_agent_mode
  if (mode === 'supervisor') return 'Supervisor'
  if (mode === 'deep_agents') return 'Deep Agents'
  return '单智能体'
}

const getSubagentCount = (agent) => {
  if (agent._isBuiltin) return 0
  const ctx = agent.config_json?.context || agent.config_json || {}
  return (ctx.subagents || []).length
}

// 导航
const openDetail = (agent) => {
  const type = agent._isBuiltin ? 'builtin' : 'custom'
  router.push(`/agent-square/${type}/${agent.id}`)
}

const goChat = (agent) => {
  if (agent._isBuiltin) {
    router.push(`/agent/${agent.id}`)
  } else {
    router.push({
      path: `/agent/${DYNAMIC_AGENT_ID}`,
      query: { config_id: agent.id }
    })
  }
}

const goTeamBuilder = () => {
  router.push('/team-builder')
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

<style scoped lang="less">
.agent-square {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px;
  background: var(--gray-100);
}

.square-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.header-icon {
  color: var(--main-500);
}

.header-left h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--gray-900);
}

.header-desc {
  margin: 2px 0 0 0;
  font-size: 13px;
  color: var(--gray-500);
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  border-radius: 10px;
  font-weight: 500;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;
}

.filter-tabs {
  display: flex;
  gap: 4px;
  background: var(--gray-0);
  padding: 4px;
  border-radius: 10px;
  border: 1px solid var(--gray-200);
}

.filter-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--gray-600);
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    color: var(--gray-800);
    background: var(--gray-100);
  }

  &.active {
    background: var(--main-500);
    color: white;

    .count {
      background: rgba(255, 255, 255, 0.25);
      color: white;
    }
  }

  .count {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--gray-200);
    color: var(--gray-600);
  }
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  width: 280px;
  transition: all 0.2s;

  &:focus-within {
    border-color: var(--main-400);
    box-shadow: 0 0 0 2px var(--main-100);
  }
}

.search-icon {
  color: var(--gray-400);
  flex-shrink: 0;
}

.search-input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  width: 100%;
  color: var(--gray-900);

  &::placeholder {
    color: var(--gray-400);
  }
}

/* 加载 & 空状态 */
.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  text-align: center;
}

.empty-icon {
  width: 80px;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px;
  background: var(--gray-200);
  color: var(--gray-400);
  margin-bottom: 16px;
}

.empty-state p {
  margin: 0 0 16px 0;
  color: var(--gray-500);
  font-size: 15px;
}

/* 卡片网格 */
.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.agent-card {
  background: var(--gray-0);
  border-radius: 14px;
  border: 1px solid var(--gray-200);
  overflow: hidden;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  cursor: pointer;

  &:hover {
    border-color: var(--main-300);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  }

  &.builtin {
    .card-avatar {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
  }
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px 12px;
}

.card-avatar {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: var(--main-500);
  color: #fff;
}

.card-badge {
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 20px;

  &.badge-builtin {
    background: linear-gradient(135deg, #e8e0f0 0%, #dde4f5 100%);
    color: #764ba2;
  }

  &.badge-single {
    background: var(--gray-100);
    color: var(--gray-600);
  }

  &.badge-supervisor {
    background: var(--color-info-50);
    color: var(--color-info-700);
  }

  &.badge-deep {
    background: var(--color-success-50);
    color: var(--color-success-700);
  }
}

.card-body {
  padding: 0 18px;
  flex: 1;
}

.card-title {
  margin: 0 0 6px 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--gray-900);
}

.card-desc {
  margin: 0 0 10px 0;
  font-size: 13px;
  color: var(--gray-500);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--gray-400);
  margin-bottom: 8px;
}

.card-caps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
}

.cap-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  line-height: 18px;
  background: var(--gray-100);
  border: none;
  color: var(--gray-600);
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  border-top: 1px solid var(--gray-100);
  background: var(--gray-50);
}

.card-footer .ant-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  border-radius: 8px;
}

/* 创建卡片 */
.create-card {
  border: 2px dashed var(--gray-300);
  background: var(--gray-50);
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover {
    border-color: var(--main-400);
    background: var(--main-50);

    .create-content {
      color: var(--main-600);
    }

    .create-icon {
      background: var(--main-100);
      color: var(--main-600);
    }
  }
}

.create-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--gray-500);
  font-size: 14px;
  font-weight: 500;
  transition: color 0.2s;
}

.create-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: var(--gray-200);
  color: var(--gray-400);
  transition: all 0.2s;
}

@media (max-width: 768px) {
  .agent-square {
    padding: 16px;
  }

  .square-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }

  .filter-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-tabs {
    width: 100%;
    justify-content: center;
  }

  .search-box {
    width: 100%;
  }

  .agents-grid {
    grid-template-columns: 1fr;
  }
}
</style>
