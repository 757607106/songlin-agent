<template>
  <div class="team-builder">
    <!-- 左侧会话列表 -->
    <aside class="sessions-sidebar">
      <div class="sidebar-header">
        <h2>聊天组队</h2>
        <a-button type="primary" size="small" @click="createEmptySession" :loading="creatingSession">
          <Plus :size="14" />
        </a-button>
      </div>

      <div class="sessions-list">
        <a-spin :spinning="loadingSessions">
          <div v-if="sessions.length === 0" class="empty-sessions">
            <MessageSquare :size="24" />
            <span>暂无会话</span>
          </div>
          <div
            v-else
            v-for="item in sessions"
            :key="item.thread_id"
            class="session-item"
            :class="{ active: item.thread_id === currentThreadId }"
            @click="openSession(item.thread_id)"
          >
            <div class="session-icon">
              <Users :size="14" />
            </div>
            <div class="session-info">
              <span class="session-title">{{ item.title || '团队组建会话' }}</span>
              <span class="session-time">{{ formatTime(item.updated_at || item.created_at) }}</span>
            </div>
          </div>
        </a-spin>
      </div>

      <div class="sidebar-footer">
        <a-button block @click="goAgentSquare">
          <ArrowLeft :size="14" />
          返回广场
        </a-button>
      </div>
    </aside>

    <!-- 中间聊天主区 -->
    <main class="chat-main">
      <!-- 聊天头部 -->
      <div class="chat-header">
        <div class="header-title">
          <Sparkles :size="20" />
          <span>AI 团队组建助手</span>
        </div>
        <div class="header-actions">
          <a-button
            type="text"
            :class="{ active: showConfigDrawer }"
            @click="showConfigDrawer = !showConfigDrawer"
          >
            <Settings :size="18" />
            配置详情
          </a-button>
        </div>
      </div>

      <!-- 聊天消息区 -->
      <div ref="chatContainerRef" class="chat-messages">
        <!-- 欢迎消息 -->
        <div v-if="sessionHistory.length === 0" class="welcome-message">
          <div class="welcome-icon">
            <Sparkles :size="32" />
          </div>
          <h3>欢迎使用 AI 团队组建助手</h3>
          <p>描述你需要的团队，我会帮你自动生成智能体配置</p>
          <div class="welcome-examples">
            <div
              v-for="(example, idx) in examplePrompts"
              :key="idx"
              class="example-card"
              @click="useExample(example)"
            >
              <span>{{ example }}</span>
              <ArrowRight :size="14" />
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <template v-else>
          <div
            v-for="(msg, idx) in sessionHistory"
            :key="`${msg.created_at || idx}-${idx}`"
            class="message-item"
            :class="msg.role"
          >
            <div class="message-avatar">
              <User v-if="msg.role === 'user'" :size="18" />
              <Bot v-else :size="18" />
            </div>
            <div class="message-content">
              <div class="message-text">{{ msg.content }}</div>

              <!-- AI 生成的草稿卡片 -->
              <TeamDraftCard
                v-if="msg.role === 'assistant' && idx === sessionHistory.length - 1 && hasDraft"
                :draft="draft"
                class="draft-in-message"
                @create="createProfileFromSession"
                @view-detail="showConfigDrawer = true"
              />
            </div>
          </div>

          <!-- 流式输出中 -->
          <div v-if="isStreaming" class="message-item assistant streaming">
            <div class="message-avatar">
              <Bot :size="18" />
            </div>
            <div class="message-content">
              <div class="message-text">{{ streamingContent || '思考中...' }}</div>
              <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 输入区 -->
      <div class="chat-input-area">
        <div class="input-container">
          <a-textarea
            ref="inputRef"
            v-model:value="chatInput"
            :rows="1"
            :auto-size="{ minRows: 1, maxRows: 4 }"
            placeholder="描述你需要的团队，例如：我需要一个研发协作团队..."
            @keydown.enter.exact="handleEnterKey"
          />
          <a-button
            type="primary"
            class="send-btn"
            :disabled="!canSend"
            @click="handleSendOrStop"
          >
            <template v-if="isStreaming">
              <Square :size="16" />
            </template>
            <template v-else>
              <Send :size="16" />
            </template>
          </a-button>
        </div>
        <div class="input-hint">
          按 Enter 发送，Shift + Enter 换行
        </div>
      </div>
    </main>

    <!-- 右侧配置抽屉 -->
    <TeamConfigDrawer
      :open="showConfigDrawer"
      :draft="draft"
      :toolOptions="toolOptions"
      :knowledgeOptions="knowledgeOptions"
      :skillOptions="skillOptions"
      :mcpOptions="mcpOptions"
      :saving="savingDraft"
      @close="showConfigDrawer = false"
      @save="handleSaveDraft"
    />

    <!-- 创建成功提示 Modal -->
    <a-modal
      v-model:open="showCreateModal"
      title="保存团队配置"
      :confirmLoading="creatingProfile"
      @ok="confirmCreate"
      @cancel="showCreateModal = false"
    >
      <a-form layout="vertical">
        <a-form-item label="配置名称">
          <a-input v-model:value="profileName" placeholder="留空将自动生成" />
        </a-form-item>
        <a-form-item label="配置描述">
          <a-input v-model:value="profileDescription" placeholder="可选" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  Plus,
  Users,
  MessageSquare,
  ArrowLeft,
  Sparkles,
  Settings,
  User,
  Bot,
  Send,
  Square,
  ArrowRight
} from 'lucide-vue-next'
import { agentApi } from '@/apis/agent_api'
import TeamDraftCard from '@/components/TeamDraftCard.vue'
import TeamConfigDrawer from '@/components/TeamConfigDrawer.vue'

const DYNAMIC_AGENT_ID = 'DynamicAgent'
const router = useRouter()

// Refs
const chatContainerRef = ref(null)
const inputRef = ref(null)

// 状态
const sessions = ref([])
const loadingSessions = ref(false)
const creatingSession = ref(false)
const isStreaming = ref(false)
const streamingContent = ref('')
const savingDraft = ref(false)
const creatingProfile = ref(false)
const showConfigDrawer = ref(false)
const showCreateModal = ref(false)

const currentThreadId = ref('')
const chatInput = ref('')
const sessionHistory = ref([])
const profileName = ref('')
const profileDescription = ref('')

// 草稿数据
const draft = ref(getDefaultDraft())
const streamAbortController = ref(null)

// 选项数据
const toolOptions = ref([])
const knowledgeOptions = ref([])
const mcpOptions = ref([])
const skillOptions = ref([])

// 示例提示词
const examplePrompts = [
  '帮我组建一个需求开发团队，包含前端、后端、测试角色',
  '创建一个数据分析团队，需要数据工程师和分析师',
  '我需要一个客服支持团队，能处理用户咨询',
  '组建一个内容创作团队，包含编辑和设计'
]

// 计算属性
const canSend = computed(() => {
  return isStreaming.value || chatInput.value.trim().length > 0
})

const hasDraft = computed(() => {
  return draft.value.team_goal || (draft.value.subagents?.length > 0)
})

// 方法
function getDefaultDraft() {
  return {
    team_goal: '',
    task_scope: '',
    multi_agent_mode: 'deep_agents',
    system_prompt: '',
    supervisor_system_prompt: '',
    communication_protocol: 'hybrid',
    max_parallel_tasks: 4,
    allow_cross_agent_comm: false,
    tools: [],
    knowledges: [],
    mcps: [],
    skills: [],
    subagents: []
  }
}

function formatTime(raw) {
  if (!raw) return ''
  const dt = new Date(raw)
  if (Number.isNaN(dt.getTime())) return raw
  const now = new Date()
  const diff = now - dt
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return dt.toLocaleDateString()
}

function scrollToBottom() {
  nextTick(() => {
    const el = chatContainerRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const res = await agentApi.listTeamSessions(DYNAMIC_AGENT_ID, { limit: 100 })
    sessions.value = (res.sessions || []).sort((a, b) => {
      const ta = new Date(a.updated_at || a.created_at || 0).getTime()
      const tb = new Date(b.updated_at || b.created_at || 0).getTime()
      return tb - ta
    })
  } catch (err) {
    console.error('加载会话失败:', err)
  } finally {
    loadingSessions.value = false
  }
}

async function openSession(threadId) {
  if (!threadId || isStreaming.value) return
  currentThreadId.value = threadId
  try {
    const res = await agentApi.getTeamSession(DYNAMIC_AGENT_ID, threadId)
    applyTeamBuilder(res.team_builder || {})
    sessionHistory.value = res.history || []
    scrollToBottom()
  } catch (err) {
    console.error('读取会话失败:', err)
    message.error('读取会话失败')
  }
}

async function createEmptySession() {
  if (isStreaming.value) return
  creatingSession.value = true
  try {
    const res = await agentApi.createTeamSession(DYNAMIC_AGENT_ID, {})
    currentThreadId.value = res.thread_id
    applyTeamBuilder(res.team_builder || {})
    sessionHistory.value = res.history || []
    await loadSessions()
    scrollToBottom()
  } catch (err) {
    console.error('创建会话失败:', err)
    message.error('创建会话失败')
  } finally {
    creatingSession.value = false
  }
}

function applyTeamBuilder(state) {
  const payload = state || {}
  draft.value = {
    ...getDefaultDraft(),
    ...payload.draft,
    tools: payload.draft?.tools || [],
    knowledges: payload.draft?.knowledges || [],
    mcps: payload.draft?.mcps || [],
    skills: payload.draft?.skills || [],
    subagents: payload.draft?.subagents || []
  }
}

async function fetchOptions() {
  try {
    const detail = await agentApi.getAgentDetail(DYNAMIC_AGENT_ID)
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

function useExample(example) {
  chatInput.value = example
  inputRef.value?.focus()
}

function handleEnterKey(e) {
  if (e.shiftKey) return
  e.preventDefault()
  handleSendOrStop()
}

async function handleSendOrStop() {
  if (isStreaming.value && streamAbortController.value) {
    streamAbortController.value.abort()
    return
  }
  await sendMessage()
}

async function sendMessage() {
  const text = chatInput.value.trim()
  if (!text) return

  chatInput.value = ''
  isStreaming.value = true
  streamingContent.value = ''

  // 确保有会话
  if (!currentThreadId.value) {
    const res = await agentApi.createTeamSession(DYNAMIC_AGENT_ID, {})
    currentThreadId.value = res.thread_id
    await loadSessions()
  }

  // 添加用户消息
  sessionHistory.value.push({
    role: 'user',
    content: text,
    created_at: new Date().toISOString()
  })
  scrollToBottom()

  try {
    streamAbortController.value = new AbortController()
    const response = await agentApi.sendTeamSessionMessageStream(
      DYNAMIC_AGENT_ID,
      currentThreadId.value,
      { message: text, auto_complete: true },
      { signal: streamAbortController.value.signal }
    )

    if (!response.ok) {
      throw new Error('请求失败')
    }

    await processStreamResponse(response)
  } catch (err) {
    if (err?.name === 'AbortError') {
      message.info('已停止')
    } else {
      console.error('发送失败:', err)
      message.error(err.message || '发送失败')
    }
  } finally {
    isStreaming.value = false
    streamAbortController.value = null

    // 刷新会话
    if (currentThreadId.value) {
      await openSession(currentThreadId.value)
      await loadSessions()
    }
  }
}

async function processStreamResponse(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue

        try {
          const chunk = JSON.parse(trimmed)
          if (chunk.status === 'loading' && chunk.msg?.content) {
            const content = typeof chunk.msg.content === 'string'
              ? chunk.msg.content
              : Array.isArray(chunk.msg.content)
                ? chunk.msg.content.map(c => c.text || c.content || '').join('')
                : ''
            streamingContent.value += content
            scrollToBottom()
          } else if (chunk.status === 'finished') {
            applyTeamBuilder(chunk.team_builder || {})
            return
          }
        } catch {
          // 忽略解析错误
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

async function handleSaveDraft(newDraft) {
  if (!currentThreadId.value) {
    message.warning('请先创建会话')
    return
  }
  savingDraft.value = true
  try {
    const res = await agentApi.updateTeamSessionDraft(DYNAMIC_AGENT_ID, currentThreadId.value, {
      draft: newDraft,
      strict: false
    })
    applyTeamBuilder(res.team_builder || {})
    message.success('草稿已保存')
    showConfigDrawer.value = false
  } catch (err) {
    console.error('保存失败:', err)
    message.error('保存失败')
  } finally {
    savingDraft.value = false
  }
}

function createProfileFromSession() {
  profileName.value = ''
  profileDescription.value = ''
  showCreateModal.value = true
}

async function confirmCreate() {
  if (!currentThreadId.value) return
  creatingProfile.value = true
  try {
    // 先保存草稿
    await agentApi.updateTeamSessionDraft(DYNAMIC_AGENT_ID, currentThreadId.value, {
      draft: draft.value,
      strict: false
    })

    const res = await agentApi.createTeamProfileFromSession(DYNAMIC_AGENT_ID, currentThreadId.value, {
      name: profileName.value || undefined,
      description: profileDescription.value || undefined,
      set_default: true
    })

    message.success('团队配置创建成功')
    showCreateModal.value = false

    const configId = res?.config?.id
    if (configId) {
      router.push({
        path: `/agent/${DYNAMIC_AGENT_ID}`,
        query: { config_id: configId }
      })
    } else {
      router.push('/agent-square')
    }
  } catch (err) {
    console.error('创建失败:', err)
    message.error('创建失败')
  } finally {
    creatingProfile.value = false
  }
}

function goAgentSquare() {
  router.push('/agent-square')
}

// 生命周期
onMounted(async () => {
  await loadSessions()
  await fetchOptions()
  if (sessions.value.length > 0) {
    await openSession(sessions.value[0].thread_id)
  }
})
</script>

<style scoped lang="less">
.team-builder {
  display: flex;
  height: 100%;
  background: var(--gray-100);
  overflow: hidden;
}

/* 左侧会话列表 */
.sessions-sidebar {
  width: 260px;
  background: var(--gray-0);
  border-right: 1px solid var(--gray-200);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--gray-100);

  h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: var(--gray-900);
  }

  .ant-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border-radius: 8px;
  }
}

.sessions-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.empty-sessions {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--gray-400);
  gap: 8px;
  font-size: 13px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 4px;

  &:hover {
    background: var(--gray-100);
  }

  &.active {
    background: var(--main-50);

    .session-icon {
      background: var(--main-500);
      color: white;
    }

    .session-title {
      color: var(--main-700);
      font-weight: 500;
    }
  }
}

.session-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--gray-200);
  color: var(--gray-500);
  flex-shrink: 0;
}

.session-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-title {
  font-size: 13px;
  color: var(--gray-800);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-time {
  font-size: 11px;
  color: var(--gray-400);
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--gray-100);

  .ant-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    border-radius: 8px;
  }
}

/* 中间聊天主区 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--gray-50);
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--gray-0);
  border-bottom: 1px solid var(--gray-200);
}

.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-900);

  .lucide {
    color: var(--main-500);
  }
}

.header-actions {
  .ant-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--gray-600);
    border-radius: 8px;

    &:hover,
    &.active {
      color: var(--main-600);
      background: var(--main-50);
    }
  }
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

/* 欢迎消息 */
.welcome-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.welcome-icon {
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px;
  background: var(--main-100);
  color: var(--main-600);
  margin-bottom: 20px;
}

.welcome-message h3 {
  margin: 0 0 8px 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--gray-900);
}

.welcome-message p {
  margin: 0 0 24px 0;
  font-size: 14px;
  color: var(--gray-500);
}

.welcome-examples {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  max-width: 600px;
}

.example-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 13px;
  color: var(--gray-700);
  text-align: left;

  &:hover {
    border-color: var(--main-300);
    background: var(--main-50);
    color: var(--main-700);
  }

  .lucide {
    flex-shrink: 0;
    color: var(--gray-400);
  }

  &:hover .lucide {
    color: var(--main-500);
  }
}

/* 消息项 */
.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;

  &.user {
    flex-direction: row-reverse;

    .message-avatar {
      background: var(--main-500);
      color: white;
    }

    .message-content {
      align-items: flex-end;
    }

    .message-text {
      background: var(--main-500);
      color: white;
      border-radius: 16px 16px 4px 16px;
    }
  }

  &.assistant {
    .message-avatar {
      background: var(--gray-200);
      color: var(--gray-600);
    }

    .message-text {
      background: var(--gray-0);
      border: 1px solid var(--gray-200);
      border-radius: 16px 16px 16px 4px;
    }
  }

  &.streaming {
    .message-text {
      min-height: 40px;
    }
  }
}

.message-avatar {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  flex-shrink: 0;
}

.message-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 70%;
}

.message-text {
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.draft-in-message {
  margin-top: 4px;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;

  span {
    width: 6px;
    height: 6px;
    background: var(--gray-400);
    border-radius: 50%;
    animation: typing 1.2s ease-in-out infinite;

    &:nth-child(2) {
      animation-delay: 0.2s;
    }

    &:nth-child(3) {
      animation-delay: 0.4s;
    }
  }
}

@keyframes typing {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

/* 输入区 */
.chat-input-area {
  padding: 16px 24px 20px;
  background: var(--gray-0);
  border-top: 1px solid var(--gray-200);
}

.input-container {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 8px 8px 8px 14px;
  transition: all 0.2s;

  &:focus-within {
    border-color: var(--main-400);
    box-shadow: 0 0 0 2px var(--main-100);
  }

  :deep(.ant-input) {
    border: none;
    background: transparent;
    padding: 6px 0;
    font-size: 14px;
    resize: none;
    box-shadow: none !important;

    &:focus {
      box-shadow: none !important;
    }
  }
}

.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border-radius: 10px;
  flex-shrink: 0;
}

.input-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--gray-400);
  text-align: center;
}

/* 响应式 */
@media (max-width: 900px) {
  .sessions-sidebar {
    width: 200px;
  }

  .welcome-examples {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .sessions-sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.3s;

    &.open {
      transform: translateX(0);
    }
  }

  .message-content {
    max-width: 85%;
  }
}
</style>
