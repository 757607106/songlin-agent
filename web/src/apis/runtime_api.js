import { apiGet, apiPost } from './base'

const BASE_URL = '/api/runtime'
const toQueryString = (params = {}) => {
  const normalized = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '')
  )
  return new URLSearchParams(normalized).toString()
}

export const runtimeApi = {
  createRun: async (payload = {}, idempotencyKey) => {
    const headers = idempotencyKey ? { 'X-Idempotency-Key': idempotencyKey } : {}
    return apiPost(`${BASE_URL}/runs`, payload, { headers })
  },

  fetchRuns: async (params = {}) => {
    const query = toQueryString(params)
    const url = query ? `${BASE_URL}/runs?${query}` : `${BASE_URL}/runs`
    return apiGet(url)
  },

  fetchRunDetail: async (runId) => {
    return apiGet(`${BASE_URL}/runs/${runId}`)
  },

  fetchRunEvents: async (runId, params = {}) => {
    const query = toQueryString(params)
    const url = query ? `${BASE_URL}/runs/${runId}/events?${query}` : `${BASE_URL}/runs/${runId}/events`
    return apiGet(url)
  },

  cancelRun: async (runId) => {
    return apiPost(`${BASE_URL}/runs/${runId}/cancel`, {})
  },

  resumeRun: async (runId, payload = {}) => {
    return apiPost(`${BASE_URL}/runs/${runId}/resume`, payload)
  },

  retryRun: async (runId, payload = {}) => {
    return apiPost(`${BASE_URL}/runs/${runId}/retry`, payload)
  }
}
