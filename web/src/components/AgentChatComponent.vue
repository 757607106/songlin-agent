<template>
  <div class="chat-container">
    <ChatSidebarComponent
      :current-chat-id="currentChatId"
      :chats-list="chatsList"
      :is-sidebar-open="chatUIStore.isSidebarOpen"
      :is-initial-render="localUIState.isInitialRender"
      :single-mode="props.singleMode"
      :agents="agents"
      :selected-agent-id="currentAgentId"
      :runtime-status-filter="threadListRuntimeStatus"
      :is-creating-new-chat="chatUIStore.creatingNewChat"
      @create-chat="createNewChat"
      @select-chat="selectChat"
      @delete-chat="deleteChat"
      @rename-chat="renameChat"
      @runtime-status-change="handleRuntimeStatusChange"
      @toggle-sidebar="toggleSidebar"
      @open-agent-modal="openAgentModal"
      :class="{
        'sidebar-open': chatUIStore.isSidebarOpen,
        'no-transition': localUIState.isInitialRender
      }"
    />
    <div class="chat">
      <div class="chat-header">
        <div class="header__left">
          <slot name="header-left" class="nav-btn"></slot>
          <div
            type="button"
            class="agent-nav-btn"
            v-if="!chatUIStore.isSidebarOpen"
            @click="toggleSidebar"
          >
            <PanelLeftOpen class="nav-btn-icon" size="18" />
          </div>
          <div
            type="button"
            class="agent-nav-btn"
            v-if="!chatUIStore.isSidebarOpen"
            :class="{ 'is-disabled': chatUIStore.creatingNewChat }"
            @click="createNewChat"
          >
            <LoaderCircle
              v-if="chatUIStore.creatingNewChat"
              class="nav-btn-icon loading-icon"
              size="18"
            />
            <MessageCirclePlus v-else class="nav-btn-icon" size="16" />
            <span class="text">新对话</span>
          </div>
          <div v-if="!props.singleMode" class="agent-nav-btn" @click="openAgentModal">
            <LoaderCircle v-if="!currentAgent" class="nav-btn-icon loading-icon" size="18" />
            <Bot v-else :size="18" class="nav-btn-icon" />
            <span class="text hide-text">
              {{ currentAgentName || '选择智能体' }}
            </span>
            <ChevronDown size="16" class="switch-icon" />
          </div>
        </div>
        <div class="header__right">
          <RuntimePanel :run-id="currentRunId" @open-run="openRuntimeRun" />
          <!-- AgentState 显示按钮已移动到输入框底部 -->
          <slot name="header-right"></slot>
        </div>
      </div>

      <div class="chat-content-container">
        <!-- Main Chat Area -->
        <div class="chat-main" ref="chatMainContainer">
          <div class="chat-box" ref="messagesContainer">
            <div class="conv-box" v-for="(conv, index) in conversations" :key="index">
              <AgentMessageComponent
                v-for="(message, msgIndex) in conv.messages"
                :message="message"
                :key="msgIndex"
                :is-processing="
                  isProcessing &&
                  conv.status === 'streaming' &&
                  msgIndex === conv.messages.length - 1
                "
                :show-refs="showMsgRefs(message)"
                @retry="retryMessage(message)"
              >
              </AgentMessageComponent>
              <!-- 显示对话最后一个消息使用的模型 -->
              <RefsComponent
                v-if="shouldShowRefs(conv)"
                :message="getLastMessage(conv)"
                :show-refs="['model', 'copy']"
                :is-latest-message="false"
              />
            </div>

            <!-- 生成中的加载状态 - 增强条件支持主聊天和resume流程 -->
            <div class="generating-status" v-if="isProcessing && conversations.length > 0">
              <div class="generating-indicator">
                <div class="loading-dots">
                  <div></div>
                  <div></div>
                  <div></div>
                </div>
                <span class="generating-text">
                  <template v-if="activeSubagent">
                    <span class="subagent-badge">{{ activeSubagent }}</span>
                    正在执行...
                  </template>
                  <template v-else> 正在生成回复... </template>
                </span>
              </div>
            </div>
          </div>
          <div class="bottom" :class="{ 'start-screen': !conversations.length }">
            <!-- 人工审批弹窗 - 放在输入框上方 -->
            <HumanApprovalModal
              :visible="approvalState.showModal"
              :question="approvalState.question"
              :operation="approvalState.operation"
              :can-edit="approvalState.allowedDecisions.includes('edit')"
              @approve="handleApprove"
              @reject="handleReject"
              @edit="handleEdit"
            />

            <div class="message-input-wrapper">
              <!-- 加载状态：加载消息 -->
              <div v-if="isLoadingMessages" class="chat-loading">
                <div class="loading-spinner"></div>
                <span>正在加载消息...</span>
              </div>

              <!-- 打招呼区域 - 在输入框上方 -->
              <div v-if="!conversations.length" class="chat-examples-input">
                <h1>👋 您好，我是{{ currentAgentName }}！</h1>
              </div>

              <AgentInputArea
                ref="messageInputRef"
                v-model="userInput"
                :is-loading="isProcessing"
                :disabled="!currentAgent"
                :send-button-disabled="(!userInput || !currentAgent) && !isProcessing"
                placeholder="输入问题..."
                :supports-file-upload="supportsFileUpload"
                :agent-id="currentAgentId"
                :thread-id="currentChatId"
                :ensure-thread="ensureActiveThread"
                :has-state-content="hasAgentStateContent"
                :is-panel-open="isAgentPanelOpen"
                :mention="mentionConfig"
                @send="handleSendOrStop"
                @attachment-changed="handleAgentStateRefresh"
                @toggle-panel="toggleAgentPanel"
              />

              <!-- 示例问题 -->
              <div
                class="example-questions"
                v-if="!conversations.length && exampleQuestions.length > 0"
              >
                <div class="example-chips">
                  <div
                    v-for="question in exampleQuestions"
                    :key="question.id"
                    class="example-chip"
                    @click="handleExampleClick(question.text)"
                  >
                    {{ question.text }}
                  </div>
                </div>
              </div>

              <div class="bottom-actions" v-else>
                <p class="note">请注意辨别内容的可靠性</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Agent Panel Area -->

        <div
          class="agent-panel-wrapper"
          ref="panelWrapperRef"
          :class="{
            'is-visible': isAgentPanelOpen && hasAgentStateContent,
            'no-transition': isResizing
          }"
          :style="{
            flexBasis: isAgentPanelOpen && hasAgentStateContent ? `${panelRatio * 100}%` : '0px'
          }"
        >
          <AgentPanel
            v-if="isAgentPanelOpen && hasAgentStateContent"
            :agent-state="currentAgentState"
            :thread-id="currentChatId"
            :panel-ratio="panelRatio"
            @refresh="handleAgentStateRefresh"
            @close="toggleAgentPanel"
            @resize="handlePanelResize"
            @resizing="handleResizingChange"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch, nextTick, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import AgentInputArea from '@/components/AgentInputArea.vue'
import AgentMessageComponent from '@/components/AgentMessageComponent.vue'
import ChatSidebarComponent from '@/components/ChatSidebarComponent.vue'
import RefsComponent from '@/components/RefsComponent.vue'
import { PanelLeftOpen, MessageCirclePlus, LoaderCircle, ChevronDown, Bot } from 'lucide-vue-next'
import { handleChatError, handleValidationError } from '@/utils/errorHandler'
import { ScrollController } from '@/utils/scrollController'
import { AgentValidator } from '@/utils/agentValidator'
import { useAgentStore } from '@/stores/agent'
import { useChatUIStore } from '@/stores/chatUI'
import { storeToRefs } from 'pinia'
import { MessageProcessor } from '@/utils/messageProcessor'
import { agentApi, threadApi, databaseApi, mcpApi, runtimeApi } from '@/apis'
import HumanApprovalModal from '@/components/HumanApprovalModal.vue'
import { useApproval } from '@/composables/useApproval'
import { useAgentStreamHandler } from '@/composables/useAgentStreamHandler'
import AgentPanel from '@/components/AgentPanel.vue'
import RuntimePanel from '@/components/runtime/RuntimePanel.vue'

// ==================== PROPS & EMITS ====================
const props = defineProps({
  agentId: { type: String, default: '' },
  singleMode: { type: Boolean, default: true }
})
const emit = defineEmits(['open-config', 'open-agent-modal'])
const router = useRouter()

// ==================== STORE MANAGEMENT ====================
const agentStore = useAgentStore()
const chatUIStore = useChatUIStore()
const {
  agents,
  selectedAgentId,
  defaultAgentId,
  selectedAgentConfigId,
  agentConfig,
  configurableItems
} = storeToRefs(agentStore)

// ==================== LOCAL CHAT & UI STATE ====================
const userInput = ref('')

// 从智能体元数据获取示例问题
const exampleQuestions = computed(() => {
  const agentId = currentAgentId.value
  let examples = []
  if (agentId && agents.value && agents.value.length > 0) {
    const agent = agents.value.find((a) => a.id === agentId)
    examples = agent ? agent.examples || [] : []
  }
  return examples.map((item, index) => ({
    id: index + 1,
    text: typeof item === 'string' ? item : item.text || String(item)
  }))
})

// Keep per-thread streaming scratch data in a consistent shape.
const createOnGoingConvState = () => ({
  msgChunks: {},
  currentRequestKey: null,
  currentAssistantKey: null,
  toolCallBuffers: {}
})

// 业务状态（保留在组件本地）
const chatState = reactive({
  currentThreadId: null,
  // 以threadId为键的线程状态
  threadStates: {}
})

// 组件级别的线程和消息状态
const threads = ref([])
const threadMessages = ref({})
const threadListRuntimeStatus = ref('all')

// 本地 UI 状态（仅在本组件使用）
const localUIState = reactive({
  isInitialRender: true
})
let threadStatusSyncTimer = null
let lastThreadListFetchAt = 0
const THREAD_SYNC_ACTIVE_INTERVAL_MS = 3000
const THREAD_SYNC_IDLE_INTERVAL_MS = 10000

// Mention resources
const availableKnowledgeBases = ref([])
const availableMcps = ref([])

// Agent Panel State
const isAgentPanelOpen = ref(false)
const isResizing = ref(false)
const panelRatio = ref(0.4) // 面板宽度比例 (0-1)
const panelWrapperRef = ref(null) // 直接操作 DOM
const minPanelRatio = 0.3 // 最小比例 30%
const maxPanelRatio = 0.6 // 最大比例 60%
let panelContainerWidth = 0

// ==================== COMPUTED PROPERTIES ====================
const currentAgentId = computed(() => {
  if (props.singleMode) {
    return props.agentId || defaultAgentId.value
  } else {
    return selectedAgentId.value
  }
})

const currentAgentName = computed(() => {
  const agent = currentAgent.value
  return agent ? agent.name : '智能体'
})

const currentAgent = computed(() => {
  if (!currentAgentId.value || !agents.value || !agents.value.length) return null
  return agents.value.find((a) => a.id === currentAgentId.value) || null
})
const chatsList = computed(() => threads.value || [])
const currentChatId = computed(() => chatState.currentThreadId)
const currentThread = computed(() => {
  if (!currentChatId.value) return null
  return threads.value.find((thread) => thread.id === currentChatId.value) || null
})

// 检查当前智能体是否支持文件上传
const supportsFileUpload = computed(() => {
  if (!currentAgent.value) return false
  const capabilities = currentAgent.value.capabilities || []
  return capabilities.includes('file_upload')
})
const supportsTodo = computed(() => {
  if (!currentAgent.value) return false
  const capabilities = currentAgent.value.capabilities || []
  return capabilities.includes('todo')
})

const supportsFiles = computed(() => {
  if (!currentAgent.value) return false
  const capabilities = currentAgent.value.capabilities || []
  return capabilities.includes('files')
})

// AgentState 相关计算属性
const currentAgentState = computed(() => {
  return currentChatId.value ? getThreadState(currentChatId.value)?.agentState || null : null
})

const countFiles = (files) => {
  // 支持 dict 格式（StateBackend 格式）和 array 格式
  if (!files) return 0
  if (typeof files === 'object' && !Array.isArray(files)) {
    // dict 格式: {"/attachments/file.md": {...}, ...}
    return Object.keys(files).length
  }
  if (Array.isArray(files)) {
    // array 格式
    let c = 0
    for (const item of files) {
      if (item && typeof item === 'object') c += Object.keys(item).length
    }
    return c
  }
  return 0
}

const hasAgentStateContent = computed(() => {
  const s = currentAgentState.value
  if (!s) return false
  const todoCount = Array.isArray(s.todos) ? s.todos.length : 0
  const fileCount = countFiles(s.files)
  return todoCount > 0 || fileCount > 0
})

const mentionConfig = computed(() => {
  const rawFiles = currentAgentState.value?.files || {}
  const files = []

  // 处理 files - 兼容字典格式 {"/path/file": {content: [...]}} 和旧数组格式
  if (typeof rawFiles === 'object' && !Array.isArray(rawFiles) && rawFiles !== null) {
    // 新格式：字典格式 {"/attachments/xxx/file.md": {...}}
    Object.entries(rawFiles).forEach(([filePath, fileData]) => {
      files.push({
        path: filePath,
        ...fileData
      })
    })
  } else if (Array.isArray(rawFiles)) {
    // 旧格式：数组格式
    rawFiles.forEach((item) => {
      if (typeof item === 'object' && item !== null) {
        Object.entries(item).forEach(([filePath, fileData]) => {
          files.push({
            path: filePath,
            ...fileData
          })
        })
      }
    })
  }

  // Filter KBs and MCPs based on agent config
  const configItems = configurableItems.value || {}
  const currentConfig = agentConfig.value || {}
  const allowedKbNames = new Set()
  const allowedMcpNames = new Set()

  Object.entries(configItems).forEach(([key, item]) => {
    const kind = item?.template_metadata?.kind
    const val = currentConfig[key]

    if (Array.isArray(val)) {
      if (kind === 'knowledges') {
        val.forEach((v) => allowedKbNames.add(v))
      } else if (kind === 'mcps') {
        val.forEach((v) => allowedMcpNames.add(v))
      }
    }
  })

  const knowledgeBases = availableKnowledgeBases.value.filter((kb) => allowedKbNames.has(kb.name))
  const mcps = availableMcps.value.filter((mcp) => allowedMcpNames.has(mcp.name))

  if (!files.length && !knowledgeBases.length && !mcps.length) return null

  return {
    files,
    knowledgeBases,
    mcps
  }
})

const currentThreadMessages = computed(() => threadMessages.value[currentChatId.value] || [])

// 计算是否显示Refs组件的条件
const shouldShowRefs = computed(() => {
  return (conv) => {
    return (
      getLastMessage(conv) &&
      conv.status !== 'streaming' &&
      !approvalState.showModal &&
      !(
        approvalState.threadId &&
        chatState.currentThreadId === approvalState.threadId &&
        isProcessing.value
      )
    )
  }
})

// 当前线程状态的computed属性
const currentThreadState = computed(() => {
  return getThreadState(currentChatId.value)
})

const onGoingConvMessages = computed(() => {
  const threadState = currentThreadState.value
  if (!threadState || !threadState.onGoingConv) return []

  const msgs = Object.values(threadState.onGoingConv.msgChunks).map(
    MessageProcessor.mergeMessageChunk
  )
  return msgs.length > 0
    ? MessageProcessor.convertToolResultToMessages(msgs).filter((msg) => msg.type !== 'tool')
    : []
})

const historyConversations = computed(() => {
  return MessageProcessor.convertServerHistoryToMessages(currentThreadMessages.value)
})

const conversations = computed(() => {
  const historyConvs = historyConversations.value

  // 如果有进行中的消息且线程状态显示正在流式处理，添加进行中的对话
  if (onGoingConvMessages.value.length > 0) {
    const onGoingConv = {
      messages: onGoingConvMessages.value,
      status: 'streaming'
    }
    return [...historyConvs, onGoingConv]
  }
  return historyConvs
})

const isLoadingMessages = computed(() => chatUIStore.isLoadingMessages)
const isStreaming = computed(() => {
  const threadState = currentThreadState.value
  return threadState ? threadState.isStreaming : false
})
const isProcessing = computed(() => isStreaming.value)

// 获取当前活动的子 Agent 名称
const activeSubagent = computed(() => {
  const threadState = currentThreadState.value
  return threadState ? threadState.activeSubagent : null
})
const currentRunId = computed(() => {
  const threadState = currentThreadState.value
  return threadState?.currentRunId || ''
})

// ==================== SCROLL & RESIZE HANDLING ====================
// Update scroll controller to target .chat-main
const scrollController = new ScrollController('.chat-main')

onMounted(() => {
  nextTick(() => {
    // Update event listener to target .chat-main
    const chatMainContainer = document.querySelector('.chat-main')
    if (chatMainContainer) {
      chatMainContainer.addEventListener('scroll', scrollController.handleScroll, { passive: true })
    }
  })
  setTimeout(() => {
    localUIState.isInitialRender = false
  }, 300)
})

onUnmounted(() => {
  scrollController.cleanup()
  if (threadStatusSyncTimer) {
    clearInterval(threadStatusSyncTimer)
    threadStatusSyncTimer = null
  }
})

// ==================== THREAD STATE MANAGEMENT ====================
// 获取指定线程的状态，如果不存在则创建
const getThreadState = (threadId) => {
  if (!threadId) return null
  if (!chatState.threadStates[threadId]) {
    chatState.threadStates[threadId] = {
      isStreaming: false,
      streamAbortController: null,
      activeStreamSessionId: null,
      onGoingConv: createOnGoingConvState(),
      agentState: null, // 添加 agentState 字段
      activeSubagent: null, // 当前活动的子 Agent
      subagentSteps: [], // 子 Agent 执行步骤历史
      currentRunId: null
    }
  }
  return chatState.threadStates[threadId]
}

const normalizeRunId = (value) => {
  const text = String(value || '').trim()
  return text || null
}

const syncThreadRunIdFromThread = (thread) => {
  if (!thread?.id) return
  const runId = normalizeRunId(thread.current_run_id || thread.run_id)
  if (!runId) return
  const threadState = getThreadState(thread.id)
  if (!threadState) return
  threadState.currentRunId = runId
}

// 清理指定线程的状态
const cleanupThreadState = (threadId) => {
  if (!threadId) return
  const threadState = chatState.threadStates[threadId]
  if (threadState) {
    if (threadState.streamAbortController) {
      threadState.streamAbortController.abort()
    }
    delete chatState.threadStates[threadId]
  }
}

// ==================== STREAM HANDLING LOGIC ====================
const resetOnGoingConv = (threadId = null, options = {}) => {
  const { abortStream = true } = options
  console.log(
    `🔄 [RESET] Resetting on going conversation: ${new Date().toLocaleTimeString()}.${new Date().getMilliseconds()}`,
    threadId
  )

  const targetThreadId = threadId || currentChatId.value

  if (targetThreadId) {
    // 清理指定线程的状态
    const threadState = getThreadState(targetThreadId)
    if (threadState) {
      if (abortStream && threadState.streamAbortController) {
        threadState.streamAbortController.abort()
        threadState.streamAbortController = null
      }

      // 直接重置对话状态
      threadState.onGoingConv = createOnGoingConvState()
    }
  } else {
    // 如果没有当前线程，清理所有线程状态
    Object.keys(chatState.threadStates).forEach((tid) => {
      cleanupThreadState(tid)
    })
  }
}

// ==================== 线程管理方法 ====================
// 获取当前智能体的线程列表
const fetchThreads = async (agentId = null) => {
  const targetAgentId = agentId || currentAgentId.value
  if (!targetAgentId) return

  chatUIStore.isLoadingThreads = true
  try {
    const fetchedThreads = await threadApi.getThreads(targetAgentId, {
      runtimeStatus: threadListRuntimeStatus.value,
      limit: 100,
      offset: 0
    })
    threads.value = fetchedThreads || []
    threads.value.forEach((thread) => {
      syncThreadRunIdFromThread(thread)
    })
  } catch (error) {
    console.error('Failed to fetch threads:', error)
    handleChatError(error, 'fetch')
    throw error
  } finally {
    chatUIStore.isLoadingThreads = false
  }
}

// 创建新线程
const createThread = async (agentId, title = '新的对话') => {
  if (!agentId) return null

  chatState.isCreatingThread = true
  try {
    const thread = await threadApi.createThread(agentId, title)
    if (thread) {
      threads.value.unshift(thread)
      threadMessages.value[thread.id] = []
      syncThreadRunIdFromThread(thread)
    }
    return thread
  } catch (error) {
    console.error('Failed to create thread:', error)
    handleChatError(error, 'create')
    throw error
  } finally {
    chatState.isCreatingThread = false
  }
}

// 删除线程
const deleteThread = async (threadId) => {
  if (!threadId) return

  chatState.isDeletingThread = true
  try {
    await threadApi.deleteThread(threadId)
    threads.value = threads.value.filter((thread) => thread.id !== threadId)
    delete threadMessages.value[threadId]

    if (chatState.currentThreadId === threadId) {
      chatState.currentThreadId = null
    }
  } catch (error) {
    console.error('Failed to delete thread:', error)
    handleChatError(error, 'delete')
    throw error
  } finally {
    chatState.isDeletingThread = false
  }
}

// 更新线程标题
const updateThread = async (threadId, title) => {
  if (!threadId || !title) return

  const normalizedTitle = String(title).replace(/\s+/g, ' ').trim().slice(0, 255)
  if (!normalizedTitle) return

  chatState.isRenamingThread = true
  try {
    await threadApi.updateThread(threadId, normalizedTitle)
    const thread = threads.value.find((t) => t.id === threadId)
    if (thread) {
      thread.title = normalizedTitle
    }
  } catch (error) {
    console.error('Failed to update thread:', error)
    handleChatError(error, 'update')
    throw error
  } finally {
    chatState.isRenamingThread = false
  }
}

// 获取线程消息
const fetchThreadMessages = async ({ agentId, threadId, delay = 0 }) => {
  if (!threadId || !agentId) return

  // 如果指定了延迟，等待指定时间（用于确保后端数据库事务提交）
  if (delay > 0) {
    await new Promise((resolve) => setTimeout(resolve, delay))
  }

  try {
    const response = await agentApi.getAgentHistory(agentId, threadId)
    console.log(
      `🔄 [FETCH] Thread messages: ${new Date().toLocaleTimeString()}.${new Date().getMilliseconds()}`,
      response
    )
    threadMessages.value[threadId] = response.history || []
  } catch (error) {
    handleChatError(error, 'load')
    throw error
  }
}

const fetchAgentState = async (agentId, threadId) => {
  if (!agentId || !threadId) return
  try {
    const res = await agentApi.getAgentState(agentId, threadId)
    // 确保更新 currentChatId 对应的 state，因为 currentAgentState 依赖它
    // 如果 currentChatId 为 null，使用传入的 threadId
    const targetChatId = currentChatId.value || threadId
    console.log(
      '[fetchAgentState] agentId:',
      agentId,
      'threadId:',
      threadId,
      'targetChatId:',
      targetChatId,
      'agent_state:',
      JSON.stringify(res.agent_state || {})?.slice(0, 200)
    )
    const ts = getThreadState(targetChatId)
    if (ts) {
      ts.agentState = res.agent_state || null
    } else {
      // 如果 targetChatId 对应的 state 不存在，创建一个
      const newTs = getThreadState(threadId)
      if (newTs) newTs.agentState = res.agent_state || null
    }
  } catch {
    return
  }
}

const fetchMentionResources = async () => {
  try {
    const [dbsRes, mcpsRes] = await Promise.all([
      databaseApi.getAccessibleDatabases().catch(() => ({ databases: [] })),
      mcpApi.getMcpServers().catch(() => ({ data: [] }))
    ])
    availableKnowledgeBases.value = dbsRes.databases || []
    availableMcps.value = mcpsRes.data || []
  } catch (e) {
    console.warn('Failed to fetch mention resources', e)
  }
}

const ensureActiveThread = async (title = '新的对话') => {
  if (currentChatId.value) return currentChatId.value
  try {
    const newThread = await createThread(currentAgentId.value, title || '新的对话')
    if (newThread) {
      chatState.currentThreadId = newThread.id
      return newThread.id
    }
  } catch {
    return null
  }
  return null
}

// ==================== 审批功能管理 ====================
const { approvalState, handleApproval, processApprovalInStream } = useApproval({
  getThreadState,
  resetOnGoingConv,
  fetchThreadMessages
})

const { handleAgentResponse } = useAgentStreamHandler({
  getThreadState,
  processApprovalInStream,
  currentAgentId,
  supportsTodo,
  supportsFiles
})

const createClientUuid = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const createRuntimeRun = async ({ agentId, threadId, query, requestId }) => {
  const idemKey = createClientUuid()
  const payload = {
    agent_id: agentId,
    thread_id: threadId,
    mode: 'hybrid',
    input: { query },
    runtime_options: { max_attempts: 1 },
    request_id: requestId,
    scope: threadId
  }
  try {
    const res = await runtimeApi.createRun(payload, idemKey)
    return res?.run_id || null
  } catch (error) {
    console.warn('create runtime run failed, fallback to chat-only flow', error)
    return null
  }
}

// 发送消息并处理流式响应
const sendMessage = async ({
  agentId,
  threadId,
  text,
  signal = undefined,
  imageData = undefined
}) => {
  if (!agentId || !threadId || !text) {
    const error = new Error('Missing agent, thread, or message text')
    handleChatError(error, 'send')
    return Promise.reject(error)
  }

  // 如果是新对话，用消息内容作为标题
  if ((threadMessages.value[threadId] || []).length === 0) {
    const autoTitle = text.replace(/\s+/g, ' ').trim().slice(0, 255)
    if (autoTitle) {
      void updateThread(threadId, autoTitle).catch(() => {})
    }
  }

  const requestId = createClientUuid()
  const runId = await createRuntimeRun({ agentId, threadId, query: text, requestId })
  const threadState = getThreadState(threadId)
  if (threadState) {
    threadState.currentRunId = runId || threadState.currentRunId || null
  }
  const thread = threads.value.find((item) => item.id === threadId)
  if (thread && runId) {
    thread.current_run_id = runId
  }
  const requestData = {
    query: text,
    config: {
      thread_id: threadId,
      ...(selectedAgentConfigId.value ? { agent_config_id: selectedAgentConfigId.value } : {})
    },
    meta: {
      request_id: requestId,
      run_id: runId || undefined
    },
    run_id: runId || undefined
  }

  // 如果有图片，添加到请求中
  if (imageData && imageData.imageContent) {
    requestData.image_content = imageData.imageContent
  }

  try {
    return await agentApi.sendAgentMessage(agentId, requestData, signal ? { signal } : undefined)
  } catch (error) {
    handleChatError(error, 'send')
    throw error
  }
}

const openRuntimeRun = (runId) => {
  const normalized = String(runId || currentRunId.value || '').trim()
  if (!normalized) return
  router.push({ name: 'RuntimeComp', params: { runId: normalized } })
}

// ==================== CHAT ACTIONS ====================
// 检查第一个对话是否为空
const isFirstChatEmpty = () => {
  if (threads.value.length === 0) return false
  const firstThread = threads.value[0]
  const firstThreadMessages = threadMessages.value[firstThread.id] || []
  return firstThreadMessages.length === 0
}

// 如果第一个对话为空，直接切换到第一个对话
const switchToFirstChatIfEmpty = async () => {
  if (threads.value.length > 0 && isFirstChatEmpty()) {
    await selectChat(threads.value[0].id)
    return true
  }
  return false
}

const createNewChat = async () => {
  if (
    !AgentValidator.validateAgentId(currentAgentId.value, '创建对话') ||
    chatUIStore.creatingNewChat
  )
    return

  // 如果第一个对话为空，直接切换到第一个对话而不是创建新对话
  if (await switchToFirstChatIfEmpty()) return

  // 只有当当前对话是第一个对话且为空时，才阻止创建新对话
  const currentThreadIndex = threads.value.findIndex((thread) => thread.id === currentChatId.value)
  if (currentChatId.value && conversations.value.length === 0 && currentThreadIndex === 0) return

  chatUIStore.creatingNewChat = true
  try {
    const newThread = await createThread(currentAgentId.value, '新的对话')
    if (newThread) {
      chatState.currentThreadId = newThread.id
      void fetchThreads(currentAgentId.value).catch(() => {})
    }
  } catch (error) {
    handleChatError(error, 'create')
  } finally {
    chatUIStore.creatingNewChat = false
  }
}

const selectChat = async (chatId) => {
  if (
    !AgentValidator.validateAgentIdWithError(
      currentAgentId.value,
      '选择对话',
      handleValidationError
    )
  )
    return

  chatState.currentThreadId = chatId
  const selectedThread = threads.value.find((thread) => thread.id === chatId)
  if (selectedThread) {
    syncThreadRunIdFromThread(selectedThread)
  }
  chatUIStore.isLoadingMessages = true
  try {
    await fetchThreadMessages({ agentId: currentAgentId.value, threadId: chatId })
  } catch (error) {
    handleChatError(error, 'load')
  } finally {
    chatUIStore.isLoadingMessages = false
  }

  await nextTick()
  scrollController.scrollToBottomStaticForce()
  await fetchAgentState(currentAgentId.value, chatId)
}

const deleteChat = async (chatId) => {
  if (
    !AgentValidator.validateAgentIdWithError(
      currentAgentId.value,
      '删除对话',
      handleValidationError
    )
  )
    return
  try {
    await deleteThread(chatId)
    if (chatState.currentThreadId === chatId) {
      chatState.currentThreadId = null
      // 如果删除的是当前对话，自动创建新对话
      await createNewChat()
    } else if (chatsList.value.length > 0) {
      // 如果删除的不是当前对话，选择第一个可用对话
      await selectChat(chatsList.value[0].id)
    }
  } catch (error) {
    handleChatError(error, 'delete')
  }
}

const renameChat = async (data) => {
  let { chatId, title } = data
  if (
    !AgentValidator.validateRenameOperation(
      chatId,
      title,
      currentAgentId.value,
      handleValidationError
    )
  )
    return
  if (title.length > 30) title = title.slice(0, 30)
  try {
    await updateThread(chatId, title)
  } catch (error) {
    handleChatError(error, 'rename')
  }
}

const handleSendMessage = async ({ image } = {}) => {
  console.log('AgentChatComponent: handleSendMessage payload image:', image)
  const text = userInput.value.trim()
  if ((!text && !image) || !currentAgent.value || isProcessing.value) return

  let threadId = currentChatId.value
  if (!threadId) {
    threadId = await ensureActiveThread(text)
    if (!threadId) {
      message.error('创建对话失败，请重试')
      return
    }
  }

  userInput.value = ''

  await nextTick()
  scrollController.scrollToBottom(true)

  const threadState = getThreadState(threadId)
  if (!threadState) return
  const streamSessionId = createClientUuid()

  threadState.isStreaming = true
  threadState.activeStreamSessionId = streamSessionId
  resetOnGoingConv(threadId)
  threadState.streamAbortController = new AbortController()

  try {
    const response = await sendMessage({
      agentId: currentAgentId.value,
      threadId: threadId,
      text: text,
      signal: threadState.streamAbortController?.signal,
      imageData: image
    })

    await handleAgentResponse(response, threadId)
  } catch (error) {
    if (error.name !== 'AbortError') {
      console.error('Stream error:', error)
      handleChatError(error, 'send')
    } else {
      console.warn('[Interrupted] Catch')
    }
    if (threadState.activeStreamSessionId === streamSessionId) {
      threadState.isStreaming = false
    }
  } finally {
    const isCurrentSession = threadState.activeStreamSessionId === streamSessionId
    if (isCurrentSession) {
      threadState.streamAbortController = null
    }
    // 异步加载历史记录，保持当前消息显示直到历史记录加载完成
    fetchThreadMessages({ agentId: currentAgentId.value, threadId: threadId }).finally(() => {
      const latestThreadState = getThreadState(threadId)
      if (!latestThreadState || latestThreadState.activeStreamSessionId !== streamSessionId) {
        return
      }
      latestThreadState.activeStreamSessionId = null
      // 历史记录加载完成后，安全地清空当前进行中的对话
      resetOnGoingConv(threadId, { abortStream: false })
      scrollController.scrollToBottom()
      void fetchThreads(currentAgentId.value).catch(() => {})
    })
  }
}

// 发送或中断
const handleSendOrStop = async (payload) => {
  const threadId = currentChatId.value
  const threadState = getThreadState(threadId)
  if (isProcessing.value && threadState && threadState.streamAbortController) {
    const runId = normalizeRunId(threadState.currentRunId || currentRunId.value)
    let cancelRequested = false
    if (runId) {
      try {
        await runtimeApi.cancelRun(runId)
        cancelRequested = true
        message.info('已请求停止，等待当前步骤结束')
      } catch (error) {
        console.warn('Cancel run failed, fallback to local abort only:', error)
      }
    }
    if (cancelRequested) {
      return
    }
    // 中断生成
    threadState.streamAbortController.abort()

    // 中断后刷新消息历史，确保显示最新的状态
    try {
      await fetchThreadMessages({ agentId: currentAgentId.value, threadId: threadId })
      message.info('已中断对话生成')
      void fetchThreads(currentAgentId.value).catch(() => {})
    } catch (error) {
      console.error('刷新消息历史失败:', error)
      message.info('已中断对话生成')
    }
    return
  }
  await handleSendMessage(payload)
}

// ==================== 人工审批处理 ====================
const handleApprovalWithStream = async (decision, editedText = '') => {
  console.log('🔄 [STREAM] Starting resume stream processing')

  const threadId = approvalState.threadId
  if (!threadId) {
    message.error('无效的审批请求')
    approvalState.showModal = false
    return
  }

  const threadState = getThreadState(threadId)
  if (!threadState) {
    message.error('无法找到对应的对话线程')
    approvalState.showModal = false
    return
  }

  try {
    // 使用审批 composable 处理审批
    const response = await handleApproval(
      decision,
      currentAgentId.value,
      selectedAgentConfigId.value,
      editedText,
      threadState.currentRunId
    )

    if (!response) return // 如果 handleApproval 抛出错误，这里不会执行

    console.log('🔄 [STREAM] Processing resume streaming response')

    // 处理流式响应
    await handleAgentResponse(response, threadId, (chunk) => {
      console.log('🔄 [STREAM] Processing chunk:', chunk)
    })

    console.log('🔄 [STREAM] Resume stream processing completed')
  } catch (error) {
    console.error('❌ [STREAM] Resume stream failed:', error)
    if (error.name !== 'AbortError') {
      console.error('Resume approval error:', error)
      // handleChatError 已在 useApproval 中调用
    }
  } finally {
    console.log('🔄 [STREAM] Cleaning up streaming state')
    if (threadState) {
      threadState.isStreaming = false
      threadState.streamAbortController = null
    }

    // 异步加载历史记录，保持当前消息显示直到历史记录加载完成
    fetchThreadMessages({ agentId: currentAgentId.value, threadId: threadId }).finally(() => {
      // 历史记录加载完成后，安全地清空当前进行中的对话
      resetOnGoingConv(threadId)
      scrollController.scrollToBottom()
      void fetchThreads(currentAgentId.value).catch(() => {})
    })
  }
}

const handleApprove = () => {
  handleApprovalWithStream('approve')
}

const handleReject = () => {
  handleApprovalWithStream('reject')
}

const handleEdit = () => {
  const editedText = window.prompt('请输入编辑后的审批内容', approvalState.operation || '')
  if (editedText === null) {
    approvalState.showModal = true
    return
  }
  handleApprovalWithStream('edit', editedText)
}

// 处理示例问题点击
const handleExampleClick = (questionText) => {
  userInput.value = questionText
  nextTick(() => {
    handleSendMessage()
  })
}

const buildExportPayload = () => {
  const agentId = currentAgentId.value
  let agentDescription = ''
  if (agentId && agents.value && agents.value.length > 0) {
    const agent = agents.value.find((a) => a.id === agentId)
    agentDescription = agent ? agent.description || '' : ''
  }

  const payload = {
    chatTitle: currentThread.value?.title || '新对话',
    agentName: currentAgentName.value || currentAgent.value?.name || '智能助手',
    agentDescription: agentDescription || currentAgent.value?.description || '',
    messages: conversations.value ? JSON.parse(JSON.stringify(conversations.value)) : [],
    onGoingMessages: onGoingConvMessages.value
      ? JSON.parse(JSON.stringify(onGoingConvMessages.value))
      : []
  }

  return payload
}

defineExpose({
  getExportPayload: buildExportPayload
})

const toggleSidebar = () => {
  chatUIStore.toggleSidebar()
}
const openAgentModal = () => emit('open-agent-modal')

const handleRuntimeStatusChange = async (runtimeStatus) => {
  threadListRuntimeStatus.value = runtimeStatus || 'all'
  await loadChatsList()
}

const handleAgentStateRefresh = async (threadId = null) => {
  if (!currentAgentId.value) return
  // 优先使用传入的 threadId，否则使用当前的 currentChatId
  let chatId = threadId || currentChatId.value
  console.log(
    '[handleAgentStateRefresh] input threadId:',
    threadId,
    'currentChatId:',
    currentChatId.value,
    'final chatId:',
    chatId
  )
  if (!chatId) return
  await fetchAgentState(currentAgentId.value, chatId)
}

const toggleAgentPanel = () => {
  isAgentPanelOpen.value = !isAgentPanelOpen.value
}

// 处理面板宽度调整（使用比例）
// 向右拖动(deltaX > 0)让面板变窄，向左拖动(deltaX < 0)让面板变宽
const handlePanelResize = (deltaX) => {
  if (!panelWrapperRef.value) return

  // 初始化容器宽度
  if (!panelContainerWidth) {
    const container = document.querySelector('.chat-content-container')
    panelContainerWidth = container ? container.clientWidth : window.innerWidth
  }

  const currentWidth = panelWrapperRef.value.offsetWidth
  // 反转 deltaX：向右拖(deltaX > 0)让面板变窄
  const newWidth = currentWidth - deltaX
  const newRatio = newWidth / panelContainerWidth

  // 限制在合理范围内
  if (newRatio >= minPanelRatio && newRatio <= maxPanelRatio) {
    // 直接操作 DOM，不触发 Vue 响应式，使用 !important 确保不被覆盖
    panelWrapperRef.value.style.setProperty('flex', `0 0 ${newWidth}px`, 'important')
  }
}

// 拖拽状态变化时，同步最终状态到 Vue 响应式数据
const handleResizingChange = (isResizingState) => {
  isResizing.value = isResizingState

  // 拖拽结束时，同步 DOM 宽度到响应式数据
  if (!isResizingState && panelWrapperRef.value && panelContainerWidth) {
    const finalWidth = panelWrapperRef.value.offsetWidth
    panelRatio.value = finalWidth / panelContainerWidth
    panelContainerWidth = 0 // 重置，供下次使用
  }
}

// ==================== HELPER FUNCTIONS ====================
const getLastMessage = (conv) => {
  if (!conv?.messages?.length) return null
  for (let i = conv.messages.length - 1; i >= 0; i--) {
    if (conv.messages[i].type === 'ai') return conv.messages[i]
  }
  return null
}

const showMsgRefs = (msg) => {
  // 如果正在审批中，不显示 refs
  if (approvalState.showModal) {
    return false
  }

  // 如果当前线程ID与审批线程ID匹配，但审批框已关闭（说明刚刚处理完审批）
  // 且当前有新的流式处理正在进行，则不显示之前被中断的消息的 refs
  if (
    approvalState.threadId &&
    chatState.currentThreadId === approvalState.threadId &&
    !approvalState.showModal &&
    isProcessing
  ) {
    return false
  }

  // 只有真正完成的消息才显示 refs
  if (msg.isLast && msg.status === 'finished') {
    return ['copy']
  }
  return false
}

// ==================== LIFECYCLE & WATCHERS ====================
const loadChatsList = async () => {
  const agentId = currentAgentId.value
  if (!agentId) {
    console.warn('No agent selected, cannot load chats list')
    threads.value = []
    chatState.currentThreadId = null
    return
  }

  try {
    await fetchThreads(agentId)
    if (currentAgentId.value !== agentId) return

    // 如果当前线程不在线程列表中，清空当前线程
    if (
      chatState.currentThreadId &&
      !threads.value.find((t) => t.id === chatState.currentThreadId)
    ) {
      chatState.currentThreadId = null
    }

    // 如果有线程但没有选中任何线程，自动选择第一个
    if (threads.value.length > 0 && !chatState.currentThreadId) {
      await selectChat(threads.value[0].id)
    }
  } catch (error) {
    handleChatError(error, 'load')
  }
}

const initAll = async () => {
  try {
    if (!agentStore.isInitialized) {
      await agentStore.initialize()
    }
    await fetchMentionResources()
  } catch (error) {
    handleChatError(error, 'load')
  }
}

onMounted(async () => {
  await initAll()
  scrollController.enableAutoScroll()
  if (threadStatusSyncTimer) {
    clearInterval(threadStatusSyncTimer)
  }
  const isThreadRuntimeActive = (thread) => {
    const runtimeStatus =
      thread?.runtime_status ||
      thread?.extra_metadata?.runtime_status ||
      thread?.metadata?.runtime_status
    return runtimeStatus === 'running' || runtimeStatus === 'waiting_for_human'
  }
  threadStatusSyncTimer = setInterval(() => {
    if (!currentAgentId.value || chatUIStore.isLoadingThreads) return
    const now = Date.now()
    const hasActiveRuntime =
      isProcessing.value || threads.value.some((thread) => isThreadRuntimeActive(thread))
    const minInterval = hasActiveRuntime
      ? THREAD_SYNC_ACTIVE_INTERVAL_MS
      : THREAD_SYNC_IDLE_INTERVAL_MS
    if (now - lastThreadListFetchAt < minInterval) return
    lastThreadListFetchAt = now
    void fetchThreads(currentAgentId.value).catch(() => {})
  }, 3000)
})

watch(
  currentAgentId,
  async (newAgentId, oldAgentId) => {
    if (newAgentId !== oldAgentId) {
      // 清理当前线程状态
      chatState.currentThreadId = null
      threadMessages.value = {}

      if (newAgentId) {
        await loadChatsList()
      } else {
        threads.value = []
      }
    }
  },
  { immediate: true }
)

watch(
  conversations,
  () => {
    if (isProcessing.value) {
      scrollController.scrollToBottom()
    }
  },
  { deep: true, flush: 'post' }
)
</script>

<style lang="less" scoped>
@import '@/assets/css/main.css';
@import '@/assets/css/animations.less';

.chat-container {
  display: flex;
  width: 100%;
  height: 100%;
  position: relative;
}

.chat {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden; /* Changed from overflow-x: hidden to overflow: hidden */
  position: relative;
  box-sizing: border-box;
  transition: all 0.3s ease;

  .chat-header {
    user-select: none;
    z-index: 10;
    height: var(--header-height);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 1rem;
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.8);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--gray-100);

    .header__left,
    .header__right {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .switch-icon {
      color: var(--gray-400);
      transition: all 0.2s ease;
      margin-left: 4px;
    }

    .agent-nav-btn:hover .switch-icon {
      color: var(--main-500);
      transform: translateY(1px);
    }
  }
}

.chat-content-container {
  flex: 1;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  position: relative;
  width: 100%;
  contain: layout;
  background: var(--gray-50); /* Subtle background for chat area */
}

.chat-main {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  position: relative;
  transition:
    flex-basis 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  min-width: 0;

  /* Add a subtle pattern or gradient if desired, or keep clean */
  background: radial-gradient(circle at 50% 30%, var(--main-10) 0%, transparent 70%);

  scrollbar-width: thin;
  scrollbar-color: var(--gray-300) transparent;
}

.agent-panel-wrapper {
  flex: 0 0 auto;
  height: calc(100% - 56px);
  overflow: hidden;
  z-index: 20;
  margin: 28px 8px;
  margin-left: 0;
  background: var(--gray-0);
  border-radius: 12px;
  box-shadow: 0 4px 20px var(--shadow-1);
  border: 1px solid var(--gray-150);
  min-width: 0;
  will-change: flex-basis;
}

/* Workbench transition animations */
.agent-panel-wrapper {
  transition: flex-basis 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  opacity: 0;
  transform: translateX(10px);
  margin-left: -16px;
}

.agent-panel-wrapper.is-visible {
  opacity: 1;
  transform: translateX(0);
  margin-left: 0;
}

.agent-panel-wrapper.no-transition {
  transition: none !important;
}

.chat-examples-input {
  padding: 32px 0;
  text-align: center;

  h1 {
    font-size: 1.2rem;
    color: var(--gray-1000);
    margin: 0;
  }
}

.example-questions {
  margin-top: 16px;
  text-align: center;

  .example-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
  }

  .example-chip {
    padding: 6px 12px;
    background: var(--gray-25);
    // border: 1px solid var(--gray-100);
    border-radius: 16px;
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--gray-700);
    transition: all 0.15s ease;
    white-space: nowrap;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover {
      // background: var(--main-25);
      border-color: var(--main-200);
      color: var(--main-700);
      box-shadow: 0 0px 4px rgba(0, 0, 0, 0.03);
    }

    &:active {
      transform: translateY(0);
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
    }
  }
}

.chat-loading {
  padding: 0 50px;
  text-align: center;
  position: absolute;
  top: 20%;
  width: 100%;
  z-index: 9;
  animation: slideInUp 0.5s ease-out;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;

  span {
    color: var(--gray-700);
    font-size: 14px;
  }

  .loading-spinner {
    width: 20px;
    height: 20px;
    border: 2px solid var(--gray-200);
    border-top-color: var(--main-color);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
}

.chat-box {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  flex-grow: 1;
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
}

.conv-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.bottom {
  position: sticky;
  bottom: 0;
  width: 100%;
  margin: 0 auto;
  padding: 4px 1rem 0 1rem;
  background: var(--gray-0);
  z-index: 1000;

  .message-input-wrapper {
    width: 100%;
    max-width: 800px;
    margin: 0 auto;

    .bottom-actions {
      display: flex;
      justify-content: center;
      align-items: center;
    }

    .note {
      font-size: small;
      color: var(--gray-300);
      margin: 4px 0;
      user-select: none;
    }
  }

  &.start-screen {
    position: absolute;
    top: 45%;
    left: 50%;
    transform: translate(-50%, -50%);
    bottom: auto;
    max-width: 800px;
    width: 90%;
    background: transparent;
    padding: 0;
    border-top: none;
    z-index: 100; /* Ensure it's above other elements */
  }
}

.loading-dots {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
}

.loading-dots div {
  width: 6px;
  height: 6px;
  background: linear-gradient(135deg, var(--main-color), var(--main-700));
  border-radius: 50%;
  animation: dotPulse 1.4s infinite ease-in-out both;
}

.loading-dots div:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dots div:nth-child(2) {
  animation-delay: -0.16s;
}

.loading-dots div:nth-child(3) {
  animation-delay: 0s;
}

.generating-status {
  display: flex;
  justify-content: flex-start;
  padding: 1rem 0;
  animation: fadeInUp 0.4s ease-out;
  transition: all 0.2s;
}

.generating-indicator {
  display: flex;
  align-items: center;
  padding: 0.75rem 0rem;

  .generating-text {
    margin-left: 12px;
    font-size: 14px;
    font-weight: 500;
    letter-spacing: 0.025em;
    /* 恢复灰色调：深灰 -> 亮灰(高光) -> 深灰 */
    background: linear-gradient(
      90deg,
      var(--gray-700) 0%,
      var(--gray-700) 40%,
      var(--gray-300) 45%,
      var(--gray-200) 50%,
      var(--gray-300) 55%,
      var(--gray-700) 60%,
      var(--gray-700) 100%
    );
    background-size: 200% auto;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: waveFlash 2s linear infinite;

    .subagent-badge {
      display: inline-block;
      padding: 2px 8px;
      margin-right: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--primary-600);
      background: var(--primary-100);
      border-radius: 4px;
      -webkit-background-clip: unset;
      background-clip: unset;
    }
  }
}

@keyframes waveFlash {
  0% {
    background-position: 200% center;
  }
  100% {
    background-position: -200% center;
  }
}

@media (max-width: 1800px) {
  .chat-header {
    background-color: var(--gray-0);
    border-bottom: 1px solid var(--gray-100);
  }
}

@media (max-width: 768px) {
  .chat-header {
    .header__left {
      .text {
        display: none;
      }
    }
  }
}
</style>

<style lang="less">
.agent-nav-btn {
  display: flex;
  gap: 6px;
  padding: 6px 8px;
  height: 32px;
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

  &:hover:not(.is-disabled) {
    background-color: var(--gray-100);
  }

  &.is-disabled {
    cursor: not-allowed;
    opacity: 0.7;
    pointer-events: none;
  }

  .nav-btn-icon {
    height: 18px;
  }

  .loading-icon {
    animation: spin 1s linear infinite;
  }
}

.hide-text {
  display: none;
}

@media (min-width: 769px) {
  .hide-text {
    display: inline;
  }
}

/* AgentState 按钮有内容时的样式 */
.agent-nav-btn.agent-state-btn.has-content:hover:not(.is-disabled) {
  color: var(--main-700);
  background-color: var(--main-20);
}

.agent-nav-btn.agent-state-btn.active {
  color: var(--main-700);
  background-color: var(--main-20);
}
</style>
