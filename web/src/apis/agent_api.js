import {
  apiGet,
  apiPost,
  apiDelete,
  apiPut,
  apiAdminGet,
  apiAdminPost,
  apiRequest
} from './base'
import { useUserStore } from '@/stores/user'

/**
 * 智能体API模块
 * 包含智能体管理、聊天、配置等功能
 * 权限要求: 任何已登录用户（普通用户、管理员、超级管理员）
 */

// =============================================================================
// === 智能体聊天分组 ===
// =============================================================================

export const agentApi = {
  /**
   * 发送聊天消息到指定智能体（流式响应）
   * @param {string} agentId - 智能体ID
   * @param {Object} data - 聊天数据
   * @returns {Promise} - 聊天响应流
   */
  sendAgentMessage: (agentId, data, options = {}) => {
    const { signal, headers: extraHeaders, ...restOptions } = options || {}
    const baseHeaders = {
      'Content-Type': 'application/json',
      ...useUserStore().getAuthHeaders()
    }

    return fetch(`/api/chat/agent/${agentId}`, {
      method: 'POST',
      body: JSON.stringify(data),
      signal,
      headers: {
        ...baseHeaders,
        ...(extraHeaders || {})
      },
      ...restOptions
    })
  },

  /**
   * 简单聊天调用（非流式）
   * @param {string} query - 查询内容
   * @returns {Promise} - 聊天响应
   */
  simpleCall: (query) => apiPost('/api/chat/call', { query }),

  /**
   * 获取默认智能体
   * @returns {Promise} - 默认智能体信息
   */
  getDefaultAgent: () => apiGet('/api/chat/default_agent'),

  /**
   * 获取智能体列表
   * @returns {Promise} - 智能体列表
   */
  getAgents: () => apiGet('/api/chat/agent'),

  /**
   * 获取单个智能体详情
   * @param {string} agentId - 智能体ID
   * @returns {Promise} - 智能体详情
   */
  getAgentDetail: (agentId) => apiGet(`/api/chat/agent/${agentId}`),

  /**
   * 重新发现并加载 Agent 插件
   */
  reloadAgents: () => apiAdminPost('/api/chat/agent/reload', {}),

  /**
   * 获取智能体历史消息
   * @param {string} agentId - 智能体ID
   * @param {string} threadId - 会话ID
   * @returns {Promise} - 历史消息
   */
  getAgentHistory: (agentId, threadId) =>
    apiGet(`/api/chat/agent/${agentId}/history?thread_id=${threadId}`),

  /**
   * 获取指定会话的 AgentState
   * @param {string} agentId - 智能体ID
   * @param {string} threadId - 会话ID
   * @returns {Promise} - AgentState
   */
  getAgentState: (agentId, threadId) =>
    apiGet(`/api/chat/agent/${agentId}/state?thread_id=${threadId}`),

  /**
   * Submit feedback for a message
   * @param {number} messageId - Message ID
   * @param {string} rating - 'like' or 'dislike'
   * @param {string|null} reason - Optional reason for dislike
   * @returns {Promise} - Feedback response
   */
  submitMessageFeedback: (messageId, rating, reason = null) =>
    apiPost(`/api/chat/message/${messageId}/feedback`, { rating, reason }),

  /**
   * Get feedback status for a message
   * @param {number} messageId - Message ID
   * @returns {Promise} - Feedback status
   */
  getMessageFeedback: (messageId) => apiGet(`/api/chat/message/${messageId}/feedback`),

  /**
   * 获取模型提供商的模型列表
   * @param {string} provider - 模型提供商
   * @returns {Promise} - 模型列表
   */
  getProviderModels: (provider) => apiGet(`/api/chat/models?model_provider=${provider}`),

  /**
   * 更新模型提供商的模型列表
   * @param {string} provider - 模型提供商
   * @param {Array} models - 选中的模型列表
   * @returns {Promise} - 更新结果
   */
  updateProviderModels: (provider, models) =>
    apiPost(`/api/chat/models/update?model_provider=${provider}`, models),

  /**
   * 获取智能体配置
   * @param {string} agentName - 智能体名称
   * @returns {Promise} - 智能体配置
   */
  getAgentConfig: async (agentName) => {
    return apiAdminGet(`/api/chat/agent/${agentName}/config`)
  },

  /**
   * 保存智能体配置
   * @param {string} agentName - 智能体名称
   * @param {Object} config - 配置对象
   * @param {Object} options - 额外参数 (e.g., { reload_graph: true })
   * @returns {Promise} - 保存结果
   */
  saveAgentConfig: async (agentName, config, options = {}) => {
    const queryParams = new URLSearchParams(options).toString()
    const url = `/api/chat/agent/${agentName}/config` + (queryParams ? `?${queryParams}` : '')
    return apiAdminPost(url, config)
  },

  getAgentConfigs: (agentId) => apiGet(`/api/chat/agent/${agentId}/configs`),

  getAgentConfigProfile: (agentId, configId) =>
    apiGet(`/api/chat/agent/${agentId}/configs/${configId}`),

  createAgentConfigProfile: (agentId, payload) =>
    apiPost(`/api/chat/agent/${agentId}/configs`, payload),

  updateAgentConfigProfile: (agentId, configId, payload) =>
    apiPut(`/api/chat/agent/${agentId}/configs/${configId}`, payload),

  setAgentConfigDefault: (agentId, configId) =>
    apiPost(`/api/chat/agent/${agentId}/configs/${configId}/set_default`, {}),

  deleteAgentConfigProfile: (agentId, configId) =>
    apiDelete(`/api/chat/agent/${agentId}/configs/${configId}`),

  /**
   * 团队创建向导：根据自然语言输入增量构建团队草稿
   */
  teamWizardStep: (agentId, message, draft = null, autoComplete = true) =>
    apiPost(`/api/chat/agent/${agentId}/team/wizard`, {
      message,
      draft,
      auto_complete: autoComplete
    }),

  /**
   * 校验团队定义（职责边界/依赖/通信）
   */
  validateTeamConfig: (agentId, team, strict = true) =>
    apiPost(`/api/chat/agent/${agentId}/team/validate`, { team, strict }),

  /**
   * 将团队定义落库为 Agent 配置
   */
  createTeamProfile: (agentId, payload) => apiPost(`/api/chat/agent/${agentId}/team/create`, payload),

  /**
   * 一句话自动组建并保存团队配置
   */
  autoCreateTeamProfile: (agentId, payload) =>
    apiPost(`/api/chat/agent/${agentId}/team/auto-create`, payload),

  /**
   * 创建团队组建会话
   */
  createTeamSession: (agentId, payload) =>
    apiPost(`/api/chat/agent/${agentId}/team/session`, payload),

  /**
   * 获取团队组建会话列表
   */
  listTeamSessions: (agentId, params = {}) => {
    const query = new URLSearchParams()
    if (Number.isFinite(params.limit) && params.limit > 0) {
      query.append('limit', String(params.limit))
    }
    if (Number.isFinite(params.offset) && params.offset >= 0) {
      query.append('offset', String(params.offset))
    }
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiGet(`/api/chat/agent/${agentId}/team/sessions${suffix}`)
  },

  /**
   * 获取单个团队组建会话
   */
  getTeamSession: (agentId, threadId) =>
    apiGet(`/api/chat/agent/${agentId}/team/session/${threadId}`),

  /**
   * 发送团队组建会话消息
   */
  sendTeamSessionMessage: (agentId, threadId, payload) =>
    apiPost(`/api/chat/agent/${agentId}/team/session/${threadId}/message`, payload),

  /**
   * 发送团队组建会话消息（流式响应）
   */
  sendTeamSessionMessageStream: (agentId, threadId, payload, options = {}) => {
    const { signal, headers: extraHeaders, ...restOptions } = options || {}
    const baseHeaders = {
      'Content-Type': 'application/json',
      ...useUserStore().getAuthHeaders()
    }
    return fetch(`/api/chat/agent/${agentId}/team/session/${threadId}/message/stream`, {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
      headers: {
        ...baseHeaders,
        ...(extraHeaders || {})
      },
      ...restOptions
    })
  },

  /**
   * 更新团队组建草稿
   */
  updateTeamSessionDraft: (agentId, threadId, payload) =>
    apiPut(`/api/chat/agent/${agentId}/team/session/${threadId}/draft`, payload),

  /**
   * 从团队组建会话创建配置
   */
  createTeamProfileFromSession: (agentId, threadId, payload) =>
    apiPost(`/api/chat/agent/${agentId}/team/session/${threadId}/create`, payload),

  /**
   * 通过 MCP langchain-docs 查询官方文档
   */
  queryTeamLangchainDocs: (agentId, query, serverName = 'langchain-docs') =>
    apiPost(`/api/chat/agent/${agentId}/team/langchain-docs`, { query, server_name: serverName }),

  /**
   * 三模式执行基准对比
   */
  benchmarkTeamModes: (agentId, team, iterations = 8, asyncTask = false) =>
    apiAdminPost(`/api/chat/agent/${agentId}/team/benchmark`, {
      team,
      iterations,
      async_task: asyncTask
    }),

  /**
   * 优化智能体系统提示词
   * @param {string} prompt - 待优化的提示词
   * @param {string} agentType - 智能体类型（可选）
   * @returns {Promise} - 优化结果 { optimized_prompt, status }
   */
  optimizePrompt: (prompt, agentType = '') =>
    apiPost('/api/chat/optimize-prompt', { prompt, agent_type: agentType }),

  /**
   * 设置默认智能体
   * @param {string} agentId - 智能体ID
   * @returns {Promise} - 设置结果
   */
  setDefaultAgent: async (agentId) => {
    return apiAdminPost('/api/chat/set_default_agent', { agent_id: agentId })
  },

  /**
   * 恢复被人工审批中断的对话（流式响应）
   * @param {string} agentId - 智能体ID
   * @param {Object} data - 恢复数据 { thread_id, approved }
   * @param {Object} options - 可选参数（signal, headers等）
   * @returns {Promise} - 恢复响应流
   */
  resumeAgentChat: (agentId, data, options = {}) => {
    const { signal, headers: extraHeaders, ...restOptions } = options || {}
    const baseHeaders = {
      'Content-Type': 'application/json',
      ...useUserStore().getAuthHeaders()
    }

    return fetch(`/api/chat/agent/${agentId}/resume`, {
      method: 'POST',
      body: JSON.stringify(data),
      signal,
      headers: {
        ...baseHeaders,
        ...(extraHeaders || {})
      },
      ...restOptions
    })
  }
}

// =============================================================================
// === 多模态图片支持分组 ===
// =============================================================================

export const multimodalApi = {
  /**
   * 上传图片并获取base64编码
   * @param {File} file - 图片文件
   * @returns {Promise} - 上传结果
   */
  uploadImage: (file) => {
    const formData = new FormData()
    formData.append('file', file)

    return apiRequest(
      '/api/chat/image/upload',
      {
        method: 'POST',
        body: formData
      },
      true
    )
  }
}

// =============================================================================
// === 对话线程分组 ===
// =============================================================================

export const threadApi = {
  /**
   * 获取对话线程列表
   * @param {string} agentId - 智能体ID
   * @returns {Promise} - 对话线程列表
   */
  getThreads: (agentId, params = {}) => {
    const query = new URLSearchParams()
    query.append('agent_id', agentId)
    if (params.runtimeStatus && params.runtimeStatus !== 'all') {
      query.append('runtime_status', params.runtimeStatus)
    }
    if (Number.isFinite(params.limit) && params.limit > 0) {
      query.append('limit', String(params.limit))
    }
    if (Number.isFinite(params.offset) && params.offset >= 0) {
      query.append('offset', String(params.offset))
    }
    const url = `/api/chat/threads?${query.toString()}`
    return apiGet(url)
  },

  /**
   * 创建新对话线程
   * @param {string} agentId - 智能体ID
   * @param {string} title - 对话标题
   * @param {Object} metadata - 元数据
   * @returns {Promise} - 创建结果
   */
  createThread: (agentId, title, metadata) =>
    apiPost('/api/chat/thread', {
      agent_id: agentId,
      title: title || '新的对话',
      metadata: metadata || {}
    }),

  /**
   * 更新对话线程
   * @param {string} threadId - 对话线程ID
   * @param {string} title - 对话标题
   * @param {string} description - 对话描述
   * @returns {Promise} - 更新结果
   */
  updateThread: (threadId, title, description) =>
    apiPut(`/api/chat/thread/${threadId}`, {
      title,
      description
    }),

  /**
   * 删除对话线程
   * @param {string} threadId - 对话线程ID
   * @returns {Promise} - 删除结果
   */
  deleteThread: (threadId) => apiDelete(`/api/chat/thread/${threadId}`),

  /**
   * 获取线程附件列表
   * @param {string} threadId - 对话线程ID
   * @returns {Promise}
   */
  getThreadAttachments: (threadId) => apiGet(`/api/chat/thread/${threadId}/attachments`),

  /**
   * 上传附件
   * @param {string} threadId
   * @param {File} file
   * @returns {Promise}
   */
  uploadThreadAttachment: (threadId, file) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiRequest(`/api/chat/thread/${threadId}/attachments`, {
      method: 'POST',
      body: formData
    })
  },

  /**
   * 删除附件
   * @param {string} threadId
   * @param {string} fileId
   * @returns {Promise}
   */
  deleteThreadAttachment: (threadId, fileId) =>
    apiDelete(`/api/chat/thread/${threadId}/attachments/${fileId}`)
}
