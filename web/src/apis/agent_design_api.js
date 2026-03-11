import { apiGet, apiPost } from './base'

export const agentDesignApi = {
  examples: () => apiGet('/api/agent-design/examples'),
  templates: () => apiGet('/api/agent-design/templates'),
  draftTemplate: (templateId, payload) => apiPost(`/api/agent-design/templates/${templateId}/draft`, payload),
  draft: (payload) => apiPost('/api/agent-design/draft', payload),
  validate: (payload) => apiPost('/api/agent-design/validate', payload),
  compile: (payload) => apiPost('/api/agent-design/compile', payload),
  deploy: (payload) => apiPost('/api/agent-design/deploy', payload)
}
