# 多 Agent 编排

当前版本已经不再暴露 `DynamicAgent` 团队编排接口，而是统一收敛到新的 `AgentPlatformAgent + agent-design` 方案。

整体分为两层：

- 设计期：用 `AgentBlueprint -> Validate -> AgentSpec -> Deploy` 创建自定义 Agent
- 运行期：由 `AgentPlatformAgent` 作为统一运行时入口执行，数据库报表助手仍保留为独立内置 Agent

## 当前公开入口

当前 `src/agents/__init__.py` 只自动注册两个运行时入口：

- `SqlReporterAgent`：产品内置的数据库报表助手
- `AgentPlatformAgent`：新平台自定义 Agent 的统一运行时入口

其中产品默认可见的内置 Agent 只有 `SqlReporterAgent`。`AgentPlatformAgent` 是内部运行时入口，用于承载用户创建的 blueprint/spec 配置。

## 设计期 API

一句话创建 Agent、模板起步、开发示例起步，统一走下面这组 API：

- `POST /api/agent-design/draft`
- `GET /api/agent-design/templates`
- `GET /api/agent-design/examples`
- `POST /api/agent-design/templates/{template_id}/draft`
- `POST /api/agent-design/validate`
- `POST /api/agent-design/compile`
- `POST /api/agent-design/deploy`

对应能力：

- 一句话草拟 `AgentBlueprint`
- 从 legacy template 直接起步
- 从 development example 直接起步
- 编译为可执行 `AgentSpec`
- 部署到部门配置表，交由 `AgentPlatformAgent` 运行

## 运行期能力

当前自定义 Agent 的运行时能力包括：

- `single`
- `supervisor`
- `deep_agents`
- `swarm_handoff`

worker 统一收敛为以下职责类型：

- `reasoning`
- `tool`
- `retrieval`

同时支持：

- 工具、MCP、RAG 检索绑定
- 强类型审批中断与恢复
- `execution_audit` 执行轨迹
- `active_worker / route_log / stage_outputs` 状态查看
- 动态 `spawn_worker / send_to_worker`

## 推荐使用流程

1. 在 `/team-builder` 或创建弹窗里输入一句话需求，或者直接选择 template / example
2. 调用 `draft -> validate -> compile -> deploy`
3. 部署后通过 `AgentPlatformAgent` 配置运行自定义 Agent
4. 运行中通过流式事件和 `agent_state` 查看 active worker、执行轨迹和恢复点
5. 如遇审批中断，使用 `resume` 接口继续执行

## 常用运行期接口

设计期完成后，运行期仍走统一聊天接口：

- `GET /api/chat/agent`
- `GET /api/chat/agent/{agent_id}`
- `GET /api/chat/agent/{agent_id}/configs`
- `POST /api/chat/agent/{agent_id}`
- `POST /api/chat/agent/{agent_id}/resume`
- `GET /api/chat/agent/{agent_id}/state`

对于自定义 Agent：

- `agent_id` 固定为 `AgentPlatformAgent`
- 具体执行哪个自定义 Agent，由配置记录里的 `blueprint/spec` 决定

## 数据库报表助手

数据库报表助手保留原有业务流程，但底层已经迁移到 `Supervisor + Worker` 的受控架构。当前阶段流包括：

- `schema`
- `clarification`
- `sample_retrieval`
- `sql_generation`
- `sql_validation`
- `sql_execution`
- `analysis`
- `chart`
- `error_recovery`

同时已经支持：

- SQL 审批中断与恢复
- worker 超时回退
- `CHART_SKIPPED`
- skills 直达路径
- 错误恢复重试

## 相关文档

- [智能体配置](/latest/advanced/agents-config)
- [多 Agent 运行时重构蓝图](/latest/advanced/runtime-refactor-blueprint)
- [重构任务清单（开发文档）](../../vibe/agent-refactor-v2/architecture.md)
