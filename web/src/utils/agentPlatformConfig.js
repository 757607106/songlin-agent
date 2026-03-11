export const AGENT_PLATFORM_AGENT_ID = 'AgentPlatformAgent'
export const AGENT_PLATFORM_CONFIG_VERSION = 'agent_platform_v2'

export const isAgentPlatformConfig = (config) =>
  Boolean(
    config &&
      typeof config === 'object' &&
      config.version === AGENT_PLATFORM_CONFIG_VERSION &&
      config.spec &&
      typeof config.spec === 'object'
  )

export const normalizeAgentPlatformConfig = (config) => {
  if (!isAgentPlatformConfig(config)) return null

  const blueprint = config.blueprint || {}
  const spec = config.spec || {}
  const workers = Array.isArray(spec.workers) ? spec.workers : []
  const toolSet = new Set()
  const knowledgeSet = new Set()
  const mcpSet = new Set()
  const skillSet = new Set()

  workers.forEach((worker) => {
    ;(worker.tool_binding?.tool_ids || []).forEach((item) => toolSet.add(item))
    ;(worker.retrieval?.knowledge_ids || []).forEach((item) => knowledgeSet.add(item))
    ;(worker.mcp_binding?.server_names || []).forEach((item) => mcpSet.add(item))
    ;(worker.skills || []).forEach((item) => skillSet.add(item))
  })

  const executionMode = spec.execution_mode || blueprint.execution_mode || 'single'

  return {
    version: AGENT_PLATFORM_CONFIG_VERSION,
    execution_mode: executionMode,
    multi_agent_mode:
      executionMode === 'single'
        ? 'disabled'
        : executionMode === 'swarm_handoff'
          ? 'swarm'
          : executionMode,
    goal: spec.goal || blueprint.goal || '',
    team_goal: spec.goal || blueprint.goal || '',
    task_scope: spec.task_scope || blueprint.task_scope || '',
    system_prompt: spec.system_prompt || blueprint.system_prompt || '',
    supervisor_prompt: spec.supervisor_prompt || blueprint.supervisor_prompt || '',
    supervisor_system_prompt: spec.supervisor_prompt || blueprint.supervisor_prompt || '',
    default_model: blueprint.default_model || '',
    max_parallel_tasks: spec.max_parallel_workers || 1,
    max_dynamic_workers: spec.max_dynamic_workers || 0,
    tools: Array.from(toolSet),
    knowledges: Array.from(knowledgeSet),
    mcps: Array.from(mcpSet),
    skills: Array.from(skillSet),
    subagents:
      executionMode === 'single'
        ? []
        : workers.map((worker) => ({
            key: worker.key || null,
            name: worker.name,
            description: worker.description,
            objective: worker.objective || '',
            system_prompt: worker.system_prompt || '',
            kind: worker.kind || 'reasoning',
            model: worker.model || '',
            tools: worker.tool_binding?.tool_ids || [],
            knowledges: worker.retrieval?.knowledge_ids || [],
            mcps: worker.mcp_binding?.server_names || [],
            skills: worker.skills || [],
            depends_on: worker.dependencies || [],
            allowed_next: worker.allowed_next || []
          }))
  }
}
