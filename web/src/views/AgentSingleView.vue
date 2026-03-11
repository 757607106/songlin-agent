<template>
  <div class="agent-single-view">
    <!-- 智能体选择弹窗 -->
    <a-modal
      v-model:open="agentModalOpen"
      title="选择智能体"
      :width="800"
      :footer="null"
      :maskClosable="true"
      class="agent-modal"
    >
      <div class="agent-modal-content">
        <div class="agents-grid">
          <div
            v-for="agent in selectableAgents"
            :key="agent._key"
            class="agent-card"
            :class="{ selected: isAgentOptionSelected(agent) }"
            @click="selectAgentFromModal(agent)"
          >
            <div class="agent-card-header">
              <div class="agent-card-title">
                <span class="agent-card-name">{{ agent.name || 'Unknown' }}</span>
              </div>
              <StarFilled
                v-if="!agent._isCustom && agent.id === defaultAgentId"
                class="default-icon"
              />
              <StarOutlined
                v-else-if="!agent._isCustom"
                @click.prevent="setAsDefaultAgent(agent.id)"
                class="default-icon"
              />
            </div>

            <div class="agent-card-description">
              {{ agent.description || '' }}
            </div>
          </div>
        </div>
      </div>
    </a-modal>

    <!-- 智能体聊天界面 -->
    <AgentChatComponent ref="chatComponentRef" :agent-id="agentId" :single-mode="true">
      <template #header-left>
        <div type="button" class="agent-nav-btn" @click="openAgentModal">
          <span class="text">{{ currentAgentName || '选择智能体' }}</span>
          <ChevronDown size="16" class="switch-icon" />
        </div>
      </template>
      <template #header-right>
        <div
          v-if="canEditCurrentCustomAgent"
          type="button"
          class="agent-nav-btn"
          @click="goEditCurrentCustomAgent"
        >
          <Pencil size="18" class="nav-btn-icon" />
          <span class="text">编辑蓝图</span>
        </div>
        <div type="button" class="agent-nav-btn" @click="handleShareChat">
          <Share2 size="18" class="nav-btn-icon" />
          <span class="text">分享</span>
        </div>
        <UserInfoComponent />
      </template>
    </AgentChatComponent>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import { useRoute, useRouter } from 'vue-router'
import { Share2, ChevronDown, Pencil } from 'lucide-vue-next'
import { StarFilled, StarOutlined } from '@ant-design/icons-vue'
import AgentChatComponent from '@/components/AgentChatComponent.vue'
import UserInfoComponent from '@/components/UserInfoComponent.vue'
import { ChatExporter } from '@/utils/chatExporter'
import { handleChatError } from '@/utils/errorHandler'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/apis/agent_api'
import { AGENT_PLATFORM_AGENT_ID, isAgentPlatformConfig } from '@/utils/agentPlatformConfig'
import { storeToRefs } from 'pinia'

const CUSTOM_RUNTIME_AGENT_IDS = [AGENT_PLATFORM_AGENT_ID]

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

const agentId = computed(() => route.params.agent_id)
const chatComponentRef = ref(null)

// 智能体选择弹窗状态
const agentModalOpen = ref(false)

// 从 store 获取智能体数据
const { agents, defaultAgentId } = storeToRefs(agentStore)
const customAgentOptions = ref([])

const currentConfigId = computed(() => {
  const raw = route.query.config_id
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isNaN(parsed) ? null : parsed
})
const isCustomRuntimeAgent = computed(() => CUSTOM_RUNTIME_AGENT_IDS.includes(agentId.value))
const canEditCurrentCustomAgent = computed(
  () => isCustomRuntimeAgent.value && Boolean(currentConfigId.value)
)

const selectableAgents = computed(() => {
  const builtinAgents = (agents.value || [])
    .filter((agent) => agent.product_visible !== false)
    .map((agent) => ({
      ...agent,
      _isCustom: false,
      _key: `builtin_${agent.id}`
    }))

  const customAgents = customAgentOptions.value.map((agent) => ({
    ...agent,
    _isCustom: true,
    _key: `custom_${agent.id}`
  }))

  return [...builtinAgents, ...customAgents]
})

const isAgentOptionSelected = (agent) => {
  if (agent._isCustom) {
    return agentId.value === agent._runtimeAgentId && currentConfigId.value === agent.id
  }
  return agent.id === agentId.value
}

const fetchCustomAgentOptions = async () => {
  try {
    const groupedConfigs = await Promise.all(
      CUSTOM_RUNTIME_AGENT_IDS.map(async (runtimeAgentId) => {
        const configsRes = await agentApi.getAgentConfigs(runtimeAgentId)
        const configs = configsRes.configs || []
        return Promise.all(
          configs.map((config) =>
            agentApi
              .getAgentConfigProfile(runtimeAgentId, config.id)
              .then((res) => ({
                ...(res.config || res),
                _runtimeAgentId: runtimeAgentId
              }))
              .catch(() => ({
                ...config,
                _runtimeAgentId: runtimeAgentId
              }))
          )
        )
      })
    )
    customAgentOptions.value = groupedConfigs.flat().filter((item) => isAgentPlatformConfig(item?.config_json))
  } catch (error) {
    console.error('加载自定义智能体列表失败:', error)
    customAgentOptions.value = []
  }
}

const syncConfigByRoute = async () => {
  if (!isCustomRuntimeAgent.value || !currentConfigId.value) return
  try {
    await agentStore.selectAgent(agentId.value)
    await agentStore.selectAgentConfig(currentConfigId.value)
  } catch (error) {
    console.error('加载指定配置失败:', error)
  }
}

// 当前智能体名称
const currentAgentName = computed(() => {
  if (isCustomRuntimeAgent.value && currentConfigId.value) {
    const customAgent = customAgentOptions.value.find(
      (item) => item._runtimeAgentId === agentId.value && item.id === currentConfigId.value
    )
    if (customAgent?.name) return customAgent.name
    return '自定义智能体'
  }

  if (!agentId.value || !agents.value?.length) return '智能体加载中……'
  const agent = agents.value.find((a) => a.id === agentId.value)
  return agent ? agent.name : '未知智能体'
})

// 打开智能体选择弹窗
const openAgentModal = () => {
  agentModalOpen.value = true
  void fetchCustomAgentOptions()
}

// 从弹窗中选择智能体 - 切换路由
const selectAgentFromModal = (agent) => {
  if (agent._isCustom) {
    if (agentId.value === agent._runtimeAgentId && currentConfigId.value === agent.id) {
      agentModalOpen.value = false
      return
    }
    router.push({
      path: `/agent/${agent._runtimeAgentId}`,
      query: { config_id: agent.id }
    })
    agentModalOpen.value = false
    return
  }

  if (agent.id === agentId.value) {
    agentModalOpen.value = false
    return
  }

  router.push(`/agent/${agent.id}`)
  agentModalOpen.value = false
}

const goEditCurrentCustomAgent = () => {
  if (!canEditCurrentCustomAgent.value) return
  router.push({
    path: `/agent-square/custom/${currentConfigId.value}`,
    query: { runtime_agent_id: AGENT_PLATFORM_AGENT_ID }
  })
}

// 设置默认智能体
const setAsDefaultAgent = async (agentIdToSet) => {
  try {
    await agentStore.setDefaultAgent(agentIdToSet)
    message.success('已设置为默认智能体')
  } catch (error) {
    handleChatError(error, 'save')
  }
}

const handleShareChat = async () => {
  try {
    const exportData = chatComponentRef.value?.getExportPayload?.()

    if (!exportData) {
      message.warning('当前没有可导出的对话内容')
      return
    }

    const hasMessages = Boolean(exportData.messages?.length)
    const hasOngoingMessages = Boolean(exportData.onGoingMessages?.length)

    if (!hasMessages && !hasOngoingMessages) {
      message.warning('当前对话暂无内容可导出，请先进行对话')
      return
    }

    const result = await ChatExporter.exportToHTML(exportData)
    message.success(`对话已导出为HTML文件: ${result.filename}`)
  } catch (error) {
    if (error?.message?.includes('没有可导出的对话内容')) {
      message.warning('当前对话暂无内容可导出，请先进行对话')
      return
    }
    handleChatError(error, 'export')
  }
}

// 初始化时确保智能体 store 已加载
onMounted(async () => {
  if (!agentStore.isInitialized) {
    try {
      await agentStore.initialize()
    } catch (error) {
      console.error('初始化智能体 store 失败:', error)
    }
  }

  await fetchCustomAgentOptions()
  await syncConfigByRoute()
})

watch(
  () => [route.params.agent_id, route.query.config_id],
  () => {
    void syncConfigByRoute()
  }
)
</script>

<style lang="less" scoped>
.agent-single-view {
  width: 100%;
  height: 100vh;
  overflow: hidden;
  position: relative;
  display: flex;
  flex-direction: row;
}

.user-info-wrapper {
  position: absolute;
  top: 10px;
  right: 20px;
  z-index: 10;
}

// 智能体选择弹窗样式
.agent-modal {
  :deep(.ant-modal-content) {
    border-radius: 8px;
    overflow: hidden;
  }

  :deep(.ant-modal-header) {
    background: var(--gray-0);
    border-bottom: 1px solid var(--gray-200);
    padding: 16px 20px;

    .ant-modal-title {
      font-weight: 600;
      color: var(--gray-900);
    }
  }

  :deep(.ant-modal-body) {
    padding: 20px;
    background: var(--gray-0);
  }

  .agent-modal-content {
    .agents-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 12px;
      max-height: 500px;
      overflow-y: auto;
    }

    .agent-card {
      border: 1px solid var(--gray-200);
      border-radius: 8px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.2s ease;
      background: var(--gray-0);

      &:hover {
        border-color: var(--main-color);
      }

      .agent-card-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 12px;

        .agent-card-title {
          flex: 1;

          .agent-card-name {
            font-size: 16px;
            font-weight: 600;
            color: var(--gray-900);
            line-height: 1.4;
          }
        }

        .default-icon {
          color: var(--color-warning-500);
          font-size: 16px;
          flex-shrink: 0;
          margin-left: 8px;
          cursor: pointer;

          &:hover {
            color: var(--color-warning-600);
          }
        }
      }

      .agent-card-description {
        font-size: 14px;
        color: var(--gray-700);
        line-height: 1.5;
        word-break: break-word;
        white-space: pre-wrap;
      }

      &.selected {
        border-color: var(--main-color);
        background: var(--main-20);

        .agent-card-header .agent-card-title .agent-card-name {
          color: var(--main-color);
        }

        .agent-card-description {
          color: var(--gray-900);
        }
      }
    }
  }
}

// 响应式适配智能体弹窗
@media (max-width: 768px) {
  .agent-modal {
    .agent-modal-content {
      .agents-grid {
        grid-template-columns: 1fr;
      }
    }
  }
}

// 侧边栏样式
.sidebar {
  // position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  width: 240px;
  background-color: var(--gray-50);
  transition: all 0.3s ease;
  z-index: 20;
  display: flex;

  &.collapsed {
    width: 60px;
  }

  .sidebar-content {
    flex: 1;
    padding: 20px 10px;
    overflow-y: auto;
  }

  .user-icon {
    cursor: pointer;
    margin-bottom: 20px;
    padding-left: 4px 8px;

    img {
      width: 32px;
      height: 32px;
    }
  }

  .toggle-button {
    position: absolute;
    right: -15px;
    top: 50%;
    transform: translateY(-50%);
    width: 30px;
    height: 30px;
    background-color: var(--gray-0);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);

    img {
      width: 16px;
      height: 16px;
    }
  }
}
</style>

<style lang="less">
.agent-nav-btn {
  display: flex;
  gap: 6px;
  padding: 6px 8px;
  justify-content: center;
  align-items: center;
  border-radius: 6px;
  color: var(--gray-900);
  cursor: pointer;
  width: auto;
  font-size: 15px;
  transition: background-color 0.3s;
  border: none;
  background: transparent;

  &:hover {
    background-color: var(--gray-50);
  }

  .nav-btn-icon {
    height: 24px;
  }

  .switch-icon {
    color: var(--gray-500);
    transition: all 0.2s ease;
  }

  &:hover .switch-icon {
    color: var(--main-500);
  }
}
</style>
