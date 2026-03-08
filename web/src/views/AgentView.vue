<template>
  <div class="agent-view">
    <div class="agent-view-body">
      <!-- 智能体选择弹窗 -->
      <a-modal
        v-model:open="chatUIStore.agentModalOpen"
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

      <a-modal
        v-model:open="createConfigModalOpen"
        title="新建配置"
        :width="320"
        :confirmLoading="createConfigLoading"
        @ok="handleCreateConfig"
        @cancel="() => (createConfigModalOpen = false)"
      >
        <a-input v-model:value="createConfigName" placeholder="请输入配置名称" allow-clear />
      </a-modal>

      <!-- 中间内容区域 -->
      <div class="content">
        <AgentChatComponent
          ref="chatComponentRef"
          :single-mode="false"
          @open-config="toggleConf"
          @open-agent-modal="openAgentModal"
          @close-config-sidebar="() => (chatUIStore.isConfigSidebarOpen = false)"
        >
          <template #header-right>
            <a-dropdown v-if="selectedAgentId" :trigger="['click']">
              <div type="button" class="agent-nav-btn">
                <Settings2 size="18" class="nav-btn-icon" />
                <span class="text hide-text">
                  {{ selectedConfigSummary?.name || '配置' }}
                </span>
                <ChevronDown size="16" class="nav-btn-icon" />
              </div>
              <template #overlay>
                <a-menu
                  :selectedKeys="selectedAgentConfigId ? [String(selectedAgentConfigId)] : []"
                >
                  <a-menu-item
                    v-for="cfg in agentConfigs[selectedAgentId] || []"
                    :key="String(cfg.id)"
                    @click="selectAgentConfig(cfg.id)"
                  >
                    <div class="menu-item-full">
                      <Star
                        :size="14"
                        :fill="cfg.is_default ? 'currentColor' : 'none'"
                        :style="{
                          color: cfg.is_default ? 'var(--color-warning-500)' : 'var(--gray-400)'
                        }"
                      />
                      <span>{{ cfg.name }}</span>
                    </div>
                  </a-menu-item>
                  <a-menu-divider v-if="userStore.isAdmin" />
                  <a-menu-item
                    v-if="userStore.isAdmin"
                    key="create_config"
                    @click="openCreateConfigModal"
                  >
                    <div class="menu-item-layout">
                      <Plus :size="16" />
                      <span>新建配置</span>
                    </div>
                  </a-menu-item>
                  <a-menu-item
                    v-if="userStore.isAdmin"
                    key="open_config"
                    @click="openConfigSidebar"
                  >
                    <div class="menu-item-layout">
                      <SquarePen :size="16" />
                      <span>编辑当前配置</span>
                    </div>
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
            <div
              v-if="selectedAgentId"
              ref="moreButtonRef"
              type="button"
              class="agent-nav-btn"
              @click="toggleMoreMenu"
            >
              <Ellipsis size="18" class="nav-btn-icon" />
            </div>
          </template>
        </AgentChatComponent>
      </div>

      <!-- 配置侧边栏 -->
      <AgentConfigSidebar
        :isOpen="chatUIStore.isConfigSidebarOpen"
        @close="() => (chatUIStore.isConfigSidebarOpen = false)"
      />

      <!-- 反馈模态框 -->
      <FeedbackModalComponent ref="feedbackModal" :agent-id="selectedAgentId" />

      <!-- 自定义更多菜单 -->
      <Teleport to="body">
        <Transition name="menu-fade">
          <div
            v-if="chatUIStore.moreMenuOpen"
            ref="moreMenuRef"
            class="more-popup-menu"
            :style="{
              left: chatUIStore.moreMenuPosition.x + 'px',
              top: chatUIStore.moreMenuPosition.y + 'px'
            }"
          >
            <div class="menu-item" @click="handleShareChat">
              <ShareAltOutlined class="menu-icon" />
              <span class="menu-text">分享对话</span>
            </div>
            <div class="menu-item" @click="handleFeedback">
              <MessageOutlined class="menu-icon" />
              <span class="menu-text">查看反馈</span>
            </div>
            <div class="menu-item" @click="handlePreview">
              <EyeOutlined class="menu-icon" />
              <span class="menu-text">预览页面</span>
            </div>
          </div>
        </Transition>
      </Teleport>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  StarOutlined,
  StarFilled,
  MessageOutlined,
  ShareAltOutlined,
  EyeOutlined
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { Settings2, Ellipsis, ChevronDown, Star, Plus, SquarePen } from 'lucide-vue-next'
import AgentChatComponent from '@/components/AgentChatComponent.vue'
import AgentConfigSidebar from '@/components/AgentConfigSidebar.vue'
import FeedbackModalComponent from '@/components/dashboard/FeedbackModalComponent.vue'
import { useUserStore } from '@/stores/user'
import { useAgentStore } from '@/stores/agent'
import { useChatUIStore } from '@/stores/chatUI'
import { ChatExporter } from '@/utils/chatExporter'
import { handleChatError } from '@/utils/errorHandler'
import { onClickOutside } from '@vueuse/core'
import { agentApi } from '@/apis/agent_api'

import { storeToRefs } from 'pinia'

const DYNAMIC_AGENT_ID = 'DynamicAgent'

// 组件引用
const feedbackModal = ref(null)
const chatComponentRef = ref(null)

// Stores
const userStore = useUserStore()
const agentStore = useAgentStore()
const chatUIStore = useChatUIStore()

// 从 agentStore 中获取响应式状态
const {
  agents,
  selectedAgentId,
  defaultAgentId,
  agentConfigs,
  selectedAgentConfigId,
  selectedConfigSummary
} = storeToRefs(agentStore)
const customAgentOptions = ref([])

const selectableAgents = computed(() => {
  const builtinAgents = (agents.value || [])
    .filter((agent) => agent.id !== DYNAMIC_AGENT_ID)
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
    return selectedAgentId.value === DYNAMIC_AGENT_ID && selectedAgentConfigId.value === agent.id
  }
  return agent.id === selectedAgentId.value
}

const fetchCustomAgentOptions = async () => {
  try {
    const configsRes = await agentApi.getAgentConfigs(DYNAMIC_AGENT_ID)
    const configs = configsRes.configs || []
    const detailedConfigs = await Promise.all(
      configs.map((config) =>
        agentApi
          .getAgentConfigProfile(DYNAMIC_AGENT_ID, config.id)
          .then((res) => res.config || res)
          .catch(() => config)
      )
    )
    customAgentOptions.value = detailedConfigs
  } catch (error) {
    console.error('加载自定义智能体列表失败:', error)
    customAgentOptions.value = []
  }
}

// 设置为默认智能体
const setAsDefaultAgent = async (agentId) => {
  if (!agentId || !userStore.isAdmin) return

  try {
    await agentStore.setDefaultAgent(agentId)
    message.success('已将当前智能体设为默认')
  } catch (error) {
    console.error('设置默认智能体错误:', error)
    message.error(error.message || '设置默认智能体时发生错误')
  }
}

// 这些方法现在由agentStore处理，无需在组件中定义

// 选择智能体（使用store方法）
const selectAgent = async (agentId) => {
  await agentStore.selectAgent(agentId)
}

// 打开智能体选择弹窗
const openAgentModal = () => {
  chatUIStore.agentModalOpen = true
  void fetchCustomAgentOptions()
}

// 从弹窗中选择智能体
const selectAgentFromModal = async (agent) => {
  if (agent._isCustom) {
    await agentStore.selectAgent(DYNAMIC_AGENT_ID)
    await agentStore.selectAgentConfig(agent.id)
  } else {
    await selectAgent(agent.id)
  }
  chatUIStore.agentModalOpen = false
}

const toggleConf = () => {
  chatUIStore.isConfigSidebarOpen = !chatUIStore.isConfigSidebarOpen
}

const openConfigSidebar = () => {
  chatUIStore.isConfigSidebarOpen = true
}

const createConfigModalOpen = ref(false)
const createConfigLoading = ref(false)
const createConfigName = ref('')

const openCreateConfigModal = () => {
  createConfigName.value = ''
  createConfigModalOpen.value = true
}

const handleCreateConfig = async () => {
  if (!selectedAgentId.value) return
  if (!createConfigName.value) {
    message.error('请输入配置名称')
    return
  }

  createConfigLoading.value = true
  try {
    await agentStore.createAgentConfigProfile({
      name: createConfigName.value,
      setDefault: false,
      fromCurrent: false
    })
    createConfigModalOpen.value = false
    chatUIStore.isConfigSidebarOpen = true
    message.success('配置已创建')
  } catch (error) {
    console.error('创建配置出错:', error)
    message.error(error.message || '创建配置失败')
  } finally {
    createConfigLoading.value = false
  }
}

const selectAgentConfig = async (configId) => {
  try {
    await agentStore.selectAgentConfig(configId)
  } catch (error) {
    console.error('切换配置出错:', error)
    message.error('切换配置失败')
  }
}

// 更多菜单相关
const moreMenuRef = ref(null)
const moreButtonRef = ref(null)

const toggleMoreMenu = (event) => {
  event.stopPropagation()
  // 切换状态，而不是只打开
  chatUIStore.moreMenuOpen = !chatUIStore.moreMenuOpen

  if (chatUIStore.moreMenuOpen) {
    // 只在打开时计算位置
    const rect = event.currentTarget.getBoundingClientRect()
    chatUIStore.openMoreMenu(rect.right - 130, rect.bottom + 8)
  }
}

const closeMoreMenu = () => {
  chatUIStore.closeMoreMenu()
}

// 使用 VueUse 的 onClickOutside
onClickOutside(
  moreMenuRef,
  () => {
    if (chatUIStore.moreMenuOpen) {
      closeMoreMenu()
    }
  },
  { ignore: [moreButtonRef] }
)

const handleShareChat = async () => {
  closeMoreMenu()

  try {
    // 从聊天组件获取导出数据
    const exportData = chatComponentRef.value?.getExportPayload?.()

    console.log('[AgentView] Export data:', exportData)

    if (!exportData) {
      message.warning('当前没有可导出的对话内容')
      return
    }

    // 检查是否有实际的消息内容
    const hasMessages = exportData.messages && exportData.messages.length > 0
    const hasOngoingMessages = exportData.onGoingMessages && exportData.onGoingMessages.length > 0

    if (!hasMessages && !hasOngoingMessages) {
      console.warn('[AgentView] Export data has no messages:', {
        messages: exportData.messages,
        onGoingMessages: exportData.onGoingMessages
      })
      message.warning('当前对话暂无内容可导出，请先进行对话')
      return
    }

    const result = await ChatExporter.exportToHTML(exportData)
    message.success(`对话已导出为HTML文件: ${result.filename}`)
  } catch (error) {
    console.error('[AgentView] Export error:', error)
    if (error?.message?.includes('没有可导出的对话内容')) {
      message.warning('当前对话暂无内容可导出，请先进行对话')
      return
    }
    handleChatError(error, 'export')
  }
}

const handleFeedback = () => {
  closeMoreMenu()
  feedbackModal.value?.show()
}

const handlePreview = () => {
  closeMoreMenu()
  if (selectedAgentId.value) {
    if (selectedAgentId.value === DYNAMIC_AGENT_ID && selectedAgentConfigId.value) {
      const configId = selectedAgentConfigId.value
      window.open(`/agent/${DYNAMIC_AGENT_ID}?config_id=${configId}`, '_blank')
      return
    }
    window.open(`/agent/${selectedAgentId.value}`, '_blank')
  }
}

onMounted(() => {
  void fetchCustomAgentOptions()
})
</script>

<style lang="less" scoped>
.agent-view {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  background-color: var(--gray-0);
}

.agent-view-body {
  --gap-radius: 12px;
  display: flex;
  flex-direction: row;
  width: 100%;
  flex: 1;
  height: 100%;
  overflow: hidden;
  position: relative;

  .content {
    flex: 1;
    display: flex;
    flex-direction: column;
    background: var(--gray-50);
  }

  .no-agent-selected {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: var(--gray-50);
  }

  .no-agent-content {
    text-align: center;
    color: var(--gray-500);

    svg {
      margin-bottom: 16px;
      opacity: 0.6;
      color: var(--gray-400);
    }

    h3 {
      margin-bottom: 16px;
      color: var(--gray-800);
      font-weight: 600;
    }
  }
}

.content {
  flex: 1;
  overflow: hidden;
}

// 配置弹窗内容样式
.conf-content {
  max-height: 70vh;
  overflow-y: auto;

  .agent-info {
    padding: 0;
    width: 100%;
    overflow-y: visible;
    max-height: none;
  }
}

.agent-model {
  width: 100%;
}

.config-modal-content {
  user-select: text;

  div[role='alert'] {
    margin-bottom: 16px;
    border-radius: 8px;
  }

  .description {
    font-size: 13px;
    color: var(--gray-500);
    margin-top: 4px;
  }

  .form-actions {
    display: flex;
    justify-content: space-between;
    margin-top: 24px;
    gap: 12px;

    .form-actions-left,
    .form-actions-right {
      display: flex;
      gap: 12px;
    }
  }
}

// 添加新按钮的样式
.agent-action-buttons {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.action-button {
  background-color: var(--gray-0);
  border: 1px solid var(--gray-200);
  text-align: left;
  height: auto;
  padding: 10px 16px;
  border-radius: 8px;
  transition: all 0.2s ease;
  box-shadow: var(--shadow-sm);

  &:hover {
    background-color: var(--gray-50);
    border-color: var(--main-300);
    transform: translateY(-1px);
    box-shadow: var(--shadow-1);
  }

  &.primary-action {
    color: var(--main-600);
    border-color: var(--main-200);
    background-color: var(--main-50);

    &:hover {
      background-color: var(--main-100);
      border-color: var(--main-400);
    }

    &:disabled {
      color: var(--main-400);
      background-color: var(--main-20);
      cursor: not-allowed;
      opacity: 0.7;
      transform: none;
      box-shadow: none;
    }
  }

  .anticon {
    margin-right: 10px;
  }
}

.agent-option {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 4px 0;

  .agent-option-content {
    display: flex;
    flex-direction: column;
    gap: 4px;

    p {
      margin: 0;
      font-weight: 500;
      color: var(--gray-900);
    }

    .agent-option-description {
      font-size: 12px;
      color: var(--gray-500);
      word-break: break-word;
      white-space: pre-wrap;
      line-height: 1.4;
    }
  }
}

// 工具选择器样式（与项目风格一致）
.tools-selector {
  .tools-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    background: var(--gray-50);
    border-radius: 10px;
    border: 1px solid var(--gray-200);
    font-size: 14px;
    color: var(--gray-700);
    transition: all 0.2s ease;

    &:hover {
      border-color: var(--main-300);
      background: var(--gray-0);
    }

    .tools-summary-left {
      display: flex;
      align-items: center;
      gap: 10px;

      .tools-count {
        color: var(--gray-900);
        font-weight: 600;
        background: var(--gray-200);
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
      }
    }

    .select-tools-btn {
      background: var(--main-500);
      border: none;
      color: var(--gray-0);
      border-radius: 8px;
      padding: 6px 14px;
      font-size: 13px;
      font-weight: 600;
      height: 32px;
      transition: all 0.2s ease;
      cursor: pointer;
      display: flex;
      align-items: center;

      &:hover {
        background: var(--main-600);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(6, 182, 212, 0.3);
      }

      &:active {
        transform: translateY(0);
      }
    }
  }

  .selected-tools-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 12px 0;
    background: none;
    border: none;
    min-height: 32px;

    :deep(.ant-tag) {
      margin: 0;
      padding: 6px 12px;
      border-radius: 8px;
      background: var(--gray-0);
      border: 1px solid var(--gray-200);
      color: var(--gray-700);
      font-size: 13px;
      font-weight: 500;
      display: flex;
      align-items: center;
      transition: all 0.2s ease;

      &:hover {
        border-color: var(--main-300);
        color: var(--main-700);
        background: var(--main-50);
      }

      .anticon-close {
        color: var(--gray-400);
        margin-left: 6px;
        font-size: 12px;
        transition: color 0.2s;

        &:hover {
          color: var(--color-error-500);
        }
      }
    }
  }
}

// 工具选择弹窗样式（与项目风格一致）
.tools-modal {
  :deep(.ant-modal-content) {
    border-radius: 16px;
    box-shadow: var(--shadow-4);
    overflow: hidden;
    padding: 0;
  }
  :deep(.ant-modal-header) {
    background: var(--gray-0);
    border-bottom: 1px solid var(--gray-100);
    padding: 20px 24px;
    margin-bottom: 0;

    .ant-modal-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--gray-900);
      letter-spacing: -0.01em;
    }
  }
  :deep(.ant-modal-body) {
    padding: 24px;
    background: var(--gray-0);
  }
  .tools-modal-content {
    .tools-search {
      margin-bottom: 20px;
      :deep(.ant-input) {
        border-radius: 10px;
        border: 1px solid var(--gray-200);
        padding: 10px 14px;
        font-size: 14px;
        transition: all 0.2s;

        &:hover {
          border-color: var(--main-300);
        }

        &:focus {
          border-color: var(--main-500);
          box-shadow: 0 0 0 2px var(--main-100);
        }
      }
    }
    .tools-list {
      max-height: 400px;
      overflow-y: auto;
      border: 1px solid var(--gray-200);
      border-radius: 12px;
      margin-bottom: 20px;
      background: var(--gray-0);

      .tool-item {
        padding: 16px 20px;
        border-bottom: 1px solid var(--gray-100);
        cursor: pointer;
        transition: all 0.2s ease;
        border-left: 4px solid transparent;

        &:last-child {
          border-bottom: none;
        }

        &:hover {
          background: var(--gray-50);
        }

        &.selected {
          background: var(--main-50);
          border-left-color: var(--main-500);

          .tool-content .tool-header .tool-name {
            color: var(--main-700);
          }
        }

        .tool-content {
          .tool-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;

            .tool-name {
              font-weight: 600;
              color: var(--gray-900);
              font-size: 15px;
              transition: color 0.2s;
            }
          }

          .tool-description {
            font-size: 13px;
            color: var(--gray-500);
            margin-bottom: 0;
            line-height: 1.6;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
          }
        }
      }
    }
    .tools-modal-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 20px;
      border-top: 1px solid var(--gray-100);

      .selected-count {
        font-size: 14px;
        color: var(--gray-600);
        font-weight: 500;
      }

      .modal-actions {
        display: flex;
        gap: 12px;

        :deep(.ant-btn) {
          border-radius: 8px;
          font-weight: 600;
          padding: 8px 20px;
          height: 40px;
          font-size: 14px;
          transition: all 0.2s;

          &.ant-btn-default {
            border: 1px solid var(--gray-300);
            color: var(--gray-700);
            background: var(--gray-0);

            &:hover {
              border-color: var(--gray-400);
              color: var(--gray-900);
              background: var(--gray-50);
            }
          }

          &.ant-btn-primary {
            background: var(--main-500);
            border: none;
            color: var(--gray-0);
            box-shadow: 0 2px 4px rgba(6, 182, 212, 0.2);

            &:hover {
              background: var(--main-600);
              transform: translateY(-1px);
              box-shadow: 0 4px 8px rgba(6, 182, 212, 0.3);
            }

            &:active {
              transform: translateY(0);
            }
          }
        }
      }
    }
  }
}

// 多选卡片样式
.multi-select-cards {
  .multi-select-label {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    font-size: 13px;
    color: var(--gray-500);
    height: 24px;
    font-weight: 500;
  }

  .options-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
  }

  .option-card {
    border: 1px solid var(--gray-200);
    border-radius: 10px;
    padding: 12px;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    background: var(--gray-0);
    user-select: none;
    position: relative;

    &:hover {
      border-color: var(--main-300);
      transform: translateY(-2px);
      box-shadow: var(--shadow-sm);
    }

    &.selected {
      border-color: var(--main-500);
      background: var(--main-50);
      box-shadow: 0 0 0 1px var(--main-500);

      .option-indicator {
        color: var(--main-500);
        opacity: 1;
      }

      .option-text {
        color: var(--main-700);
        font-weight: 600;
      }
    }

    &.unselected {
      .option-indicator {
        color: var(--gray-300);
        opacity: 0;
      }

      .option-text {
        color: var(--gray-700);
      }

      &:hover .option-indicator {
        opacity: 0.5;
      }
    }

    .option-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }

    .option-text {
      flex: 1;
      font-size: 14px;
      line-height: 1.4;
      word-break: break-word;
      transition: color 0.2s;
    }

    .option-indicator {
      flex-shrink: 0;
      font-size: 18px;
      transition: all 0.2s ease;
    }
  }
}

// 响应式适配
@media (max-width: 768px) {
  .multi-select-cards {
    .options-grid {
      grid-template-columns: 1fr;
    }
  }

  .conf-content {
    max-height: 60vh;
  }
}

// 智能体选择器样式
.agent-selector {
  border: 1px solid var(--gray-300);
  border-radius: 8px;
  padding: 8px 12px;
  background: var(--gray-0);
  transition: border-color 0.2s ease;

  &:hover {
    border-color: var(--main-color);
  }

  .selected-agent-display {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .agent-name {
      font-size: 14px;
      color: var(--gray-900);
      font-weight: 500;
    }
  }
}

// 智能体选择弹窗样式
.agent-modal {
  :deep(.ant-modal-content) {
    border-radius: 16px;
    overflow: hidden;
    box-shadow: var(--shadow-4);
    padding: 0;
  }

  :deep(.ant-modal-header) {
    background: var(--gray-0);
    border-bottom: 1px solid var(--gray-100);
    padding: 20px 24px;
    margin-bottom: 0;

    .ant-modal-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--gray-900);
      letter-spacing: -0.01em;
    }
  }

  :deep(.ant-modal-body) {
    padding: 24px;
    background: var(--gray-50);
  }

  .agent-modal-content {
    .agents-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 16px;
      max-height: 550px;
      overflow-y: auto;
      padding: 4px; // Prevent shadow clipping
    }

    .agent-card {
      border: 1px solid var(--gray-200);
      border-radius: 12px;
      padding: 20px;
      cursor: pointer;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      background: var(--gray-0);
      box-shadow: var(--shadow-sm);
      height: 100%;
      display: flex;
      flex-direction: column;

      &:hover {
        border-color: var(--main-300);
        transform: translateY(-4px);
        box-shadow: var(--shadow-2);

        .agent-card-header .agent-card-title .agent-card-name {
          color: var(--main-600);
        }
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
            font-weight: 700;
            color: var(--gray-900);
            line-height: 1.4;
            transition: color 0.2s;
          }
        }

        .default-icon {
          color: var(--gray-300);
          font-size: 18px;
          flex-shrink: 0;
          margin-left: 12px;
          cursor: pointer;
          transition: all 0.2s;

          &:hover {
            color: var(--color-warning-500);
            transform: scale(1.1);
          }

          &.anticon-star-filled {
            color: var(--color-warning-500);
          }
        }
      }

      .agent-card-description {
        font-size: 14px;
        color: var(--gray-500);
        line-height: 1.6;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 1;
      }

      &.selected {
        border-color: var(--main-500);
        background: var(--main-50);
        box-shadow: 0 0 0 1px var(--main-500);

        .agent-card-header .agent-card-title .agent-card-name {
          color: var(--main-700);
        }

        .agent-card-description {
          color: var(--gray-700);
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

// 自定义更多菜单样式
.more-popup-menu {
  position: fixed;
  min-width: 140px;
  background: var(--gray-0);
  border-radius: 12px;
  box-shadow: var(--shadow-3);
  border: 1px solid var(--gray-100);
  padding: 6px;
  z-index: 9999;

  .menu-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 14px;
    color: var(--gray-700);
    position: relative;
    user-select: none;

    .menu-icon {
      font-size: 16px;
      color: var(--gray-500);
      transition: color 0.2s ease;
      flex-shrink: 0;
    }

    .menu-text {
      font-weight: 500;
      letter-spacing: 0.01em;
    }

    &:hover {
      background: var(--main-50);
      color: var(--main-700);

      .menu-icon {
        color: var(--main-500);
      }
    }

    &:active {
      background: var(--main-100);
    }
  }

  .menu-divider {
    height: 1px;
    background: var(--gray-100);
    margin: 4px 8px;
  }
}

// 菜单淡入淡出动画
.menu-fade-enter-active {
  animation: menuSlideIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.menu-fade-leave-active {
  animation: menuSlideOut 0.15s cubic-bezier(0.4, 0, 1, 1);
}

@keyframes menuSlideIn {
  from {
    opacity: 0;
    transform: translateY(-8px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes menuSlideOut {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
  }
}

// 响应式优化
@media (max-width: 520px) {
  .more-popup-menu {
    box-shadow: var(--shadow-4);
  }
}
</style>

<style lang="less">
.toggle-conf {
  cursor: pointer;

  &.nav-btn {
    height: 2.5rem;
    display: flex;
    justify-content: center;
    align-items: center;
    border-radius: 8px;
    color: var(--gray-900);
    cursor: pointer;
    font-size: 15px;
    width: auto;
    padding: 0.5rem 1rem;
    transition: background-color 0.3s;
    overflow: hidden;

    .text {
      margin-left: 10px;
    }

    &:hover {
      background-color: var(--main-20);
    }

    .nav-btn-icon {
      width: 1.5rem;
      height: 1.5rem;
    }
  }
}

// 针对 Ant Design Select 组件的深度样式修复
:deep(.ant-select-item-option-content) {
  .agent-option-name {
    color: var(--main-color);
    font-size: 14px;
    font-weight: 500;
  }
}

// 菜单项布局样式
.menu-item-layout {
  display: flex;
  align-items: center;
  gap: 8px;
}

.menu-item-full {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

@media (max-width: 768px) {
  .hide-text {
    display: none;
  }
}
</style>
