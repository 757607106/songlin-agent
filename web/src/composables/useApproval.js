import { reactive } from 'vue'
import { message } from 'ant-design-vue'
import { handleChatError } from '@/utils/errorHandler'
import { agentApi } from '@/apis'

export function useApproval({ getThreadState, resetOnGoingConv, fetchThreadMessages }) {
  const approvalState = reactive({
    showModal: false,
    question: '',
    operation: '',
    threadId: null,
    interruptInfo: null,
    allowedDecisions: ['approve', 'reject']
  })

  const handleApproval = async (
    decision,
    currentAgentId,
    agentConfigId = null,
    editedText = ''
  ) => {
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

    approvalState.showModal = false
    if (threadState.streamAbortController) {
      threadState.streamAbortController.abort()
      threadState.streamAbortController = null
    }

    threadState.isStreaming = true
    resetOnGoingConv(threadId)
    threadState.streamAbortController = new AbortController()

    console.log('🔄 [APPROVAL] Starting resume process:', { decision, threadId, currentAgentId })

    try {
      const response = await agentApi.resumeAgentChat(
        currentAgentId,
        {
          thread_id: threadId,
          decision,
          approved: decision === 'approve',
          edited_text: decision === 'edit' ? editedText : undefined,
          config: agentConfigId ? { agent_config_id: agentConfigId } : {}
        },
        {
          signal: threadState.streamAbortController?.signal
        }
      )

      console.log('🔄 [APPROVAL] Resume API response received')

      if (!response.ok) {
        const errorText = await response.text()
        console.error('Resume API error:', response.status, errorText)
        throw new Error(`HTTP error! status: ${response.status}, details: ${errorText}`)
      }

      console.log('🔄 [APPROVAL] Resume API successful, returning response for stream processing')
      return response
    } catch (error) {
      console.error('❌ [APPROVAL] Resume failed:', error)
      if (error.name !== 'AbortError') {
        handleChatError(error, 'resume')
        message.error(`恢复对话失败: ${error.message || '未知错误'}`)
      }
      threadState.isStreaming = false
      threadState.streamAbortController = null
      throw error
    }
  }

  const processApprovalInStream = (chunk, threadId, currentAgentId) => {
    if (chunk.status !== 'human_approval_required') {
      return false
    }

    const { interrupt_info } = chunk
    const threadState = getThreadState(threadId)

    if (!threadState) return false

    threadState.isStreaming = false

    approvalState.showModal = true
    approvalState.question = interrupt_info?.question || '是否批准以下操作？'
    approvalState.operation = interrupt_info?.operation || '未知操作'
    approvalState.threadId = chunk.thread_id || threadId
    approvalState.interruptInfo = interrupt_info
    approvalState.allowedDecisions = Array.isArray(interrupt_info?.allowed_decisions)
      ? interrupt_info.allowed_decisions
      : ['approve', 'reject', 'edit']

    fetchThreadMessages({ agentId: currentAgentId, threadId: threadId })

    return true
  }

  const resetApprovalState = () => {
    approvalState.showModal = false
    approvalState.question = ''
    approvalState.operation = ''
    approvalState.threadId = null
    approvalState.interruptInfo = null
    approvalState.allowedDecisions = ['approve', 'reject']
  }

  return {
    approvalState,
    handleApproval,
    processApprovalInStream,
    resetApprovalState
  }
}
