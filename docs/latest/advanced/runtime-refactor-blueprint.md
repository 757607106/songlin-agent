# 多 Agent 运行时重构蓝图（可执行版）

> 注：这是一份重构蓝图存档文档。当前实现已经落地到 `AgentPlatformAgent + agent-design` 方案；文中出现的旧 `DynamicAgent`、旧运行时字段和迁移步骤，主要用于说明历史设计与迁移背景。最新使用方式请以 [智能体配置](/latest/advanced/agents-config) 和 [多 Agent 编排](/latest/advanced/team-orchestration) 为准。

## 1. 文档目标

本蓝图用于将当前平台升级为面向生产的「Supervisor 治理 + Deep Agents 执行」架构，覆盖以下交付物：

- 数据库 DDL 草案
- Event Schema（运行事件标准）
- API 契约（新增/改造）
- 前端页面信息架构
- 迁移清单
- 按当前目录结构拆解的逐文件实现任务列表

## 2. 目标架构（最终态）

### 2.1 分层

- 编排治理层：LangGraph Supervisor（路由、依赖、重试、熔断、审计）
- 执行引擎层：Deep Agents（task 委派、文件系统、并行执行）
- 能力生态层：LangChain 工具、MCP、Skill、KB 检索
- 平台支撑层：Task Queue、Run Store、Event Store、Artifact Store、Policy Engine

### 2.2 关键原则

- 默认有监督：复杂任务必须经过 Supervisor 规划与治理
- 强一致控制：spawn/send/retry/cancel/resume 全链路幂等
- 事件优先：状态由 Event 驱动，避免仅靠内存态
- 最小权限：子 Agent 的 Tool/MCP/Skill/KB 均执行白名单
- 可恢复运行：worker 进程重启后可从 lease + checkpoint 恢复

## 3. 数据模型与 DDL 草案

以下为 PostgreSQL 草案，保留现有 `tasks`、`conversations`、`messages`、`tool_calls`，新增运行时与治理表。

### 3.1 枚举类型

```sql
create type run_status as enum (
  'queued','dispatching','running','pausing','paused','resuming','completed','failed','cancelled'
);

create type run_event_type as enum (
  'run.created','run.dispatched','run.started','run.paused','run.resumed',
  'run.completed','run.failed','run.cancelled',
  'supervisor.route','supervisor.gate.blocked','supervisor.retry',
  'agent.spawned','agent.finished',
  'tool.called','tool.succeeded','tool.failed',
  'mcp.called','skill.loaded',
  'artifact.created','artifact.updated'
);

create type decision_type as enum ('approve','reject','edit');
```

### 3.2 运行主表

```sql
create table if not exists agent_runs (
  run_id            varchar(64) primary key,
  parent_run_id     varchar(64) references agent_runs(run_id),
  thread_id         varchar(64) not null,
  conversation_id   integer,
  request_id        varchar(64),
  idempotency_key   varchar(128) not null,
  mode              varchar(32) not null,
  agent_id          varchar(128) not null,
  status            run_status not null default 'queued',
  input_payload     jsonb not null default '{}'::jsonb,
  output_payload    jsonb,
  error_payload     jsonb,
  attempt           integer not null default 0,
  max_attempts      integer not null default 1,
  lease_owner       varchar(128),
  lease_until       timestamptz,
  cancel_requested  boolean not null default false,
  paused_reason     text,
  created_by        varchar(64),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  started_at        timestamptz,
  finished_at       timestamptz,
  unique (thread_id, idempotency_key)
);

create index if not exists idx_agent_runs_thread on agent_runs(thread_id);
create index if not exists idx_agent_runs_status on agent_runs(status);
create index if not exists idx_agent_runs_parent on agent_runs(parent_run_id);
create index if not exists idx_agent_runs_lease on agent_runs(lease_until);
```

### 3.3 运行事件表

```sql
create table if not exists run_events (
  event_id          bigserial primary key,
  run_id            varchar(64) not null references agent_runs(run_id) on delete cascade,
  seq               bigint not null,
  event_type        run_event_type not null,
  actor_type        varchar(32) not null,
  actor_name        varchar(128),
  span_id           varchar(64),
  parent_span_id    varchar(64),
  event_ts          timestamptz not null default now(),
  event_payload     jsonb not null default '{}'::jsonb,
  unique (run_id, seq)
);

create index if not exists idx_run_events_run_ts on run_events(run_id, event_ts);
create index if not exists idx_run_events_type on run_events(event_type);
```

### 3.4 产物索引表

```sql
create table if not exists run_artifacts (
  artifact_id       varchar(64) primary key,
  run_id            varchar(64) not null references agent_runs(run_id) on delete cascade,
  thread_id         varchar(64) not null,
  path              text not null,
  storage_backend   varchar(32) not null,
  object_key        text not null,
  mime_type         varchar(128),
  size_bytes        bigint,
  checksum          varchar(128),
  created_by_agent  varchar(128),
  created_at        timestamptz not null default now(),
  unique (run_id, path)
);

create index if not exists idx_run_artifacts_thread on run_artifacts(thread_id);
```

### 3.5 幂等键表

```sql
create table if not exists idempotency_records (
  scope             varchar(64) not null,
  idem_key          varchar(128) not null,
  request_hash      varchar(128) not null,
  run_id            varchar(64),
  response_payload  jsonb,
  created_at        timestamptz not null default now(),
  expires_at        timestamptz,
  primary key (scope, idem_key)
);
```

### 3.6 权限策略表

```sql
create table if not exists runtime_policy_bindings (
  id                bigserial primary key,
  subject_type      varchar(32) not null,
  subject_id        varchar(128) not null,
  resource_type     varchar(32) not null,
  resource_id       varchar(256) not null,
  action            varchar(32) not null,
  effect            varchar(16) not null check (effect in ('allow','deny')),
  condition_expr    text,
  priority          integer not null default 100,
  enabled           boolean not null default true,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_runtime_policy_subject on runtime_policy_bindings(subject_type, subject_id);
create index if not exists idx_runtime_policy_resource on runtime_policy_bindings(resource_type, resource_id);
```

### 3.7 人工审批记录

```sql
create table if not exists run_approvals (
  approval_id       varchar(64) primary key,
  run_id            varchar(64) not null references agent_runs(run_id) on delete cascade,
  decision          decision_type not null,
  requested_action  text not null,
  requested_args    jsonb,
  edited_args       jsonb,
  approver_id       varchar(64) not null,
  reason            text,
  decided_at        timestamptz not null default now()
);

create index if not exists idx_run_approvals_run on run_approvals(run_id);
```

## 4. Event Schema（运行事件标准）

### 4.1 标准结构

```json
{
  "run_id": "run_xxx",
  "seq": 42,
  "event_type": "supervisor.route",
  "actor": {
    "type": "supervisor",
    "name": "DynamicAgent.supervisor"
  },
  "span": {
    "span_id": "sp_abc",
    "parent_span_id": "sp_root"
  },
  "ts": "2026-03-08T10:00:00Z",
  "payload": {
    "from": "planner",
    "to": "coder",
    "reason": "needs implementation",
    "retry_count": 0
  }
}
```

### 4.2 事件分类

- 生命周期：run.created / run.started / run.completed / run.failed / run.cancelled
- 调度治理：supervisor.route / supervisor.gate.blocked / supervisor.retry
- 能力调用：tool.called / tool.succeeded / tool.failed / mcp.called / skill.loaded
- 产物操作：artifact.created / artifact.updated
- 审批流程：run.paused / run.resumed

### 4.3 事件校验规则

- `seq` 在同一 `run_id` 下必须单调递增
- `event_type` 必须为白名单枚举
- `payload` 必须包含最小字段集（按事件类型定义）
- `tool.failed`、`run.failed` 必须包含 `error_code` 与 `error_message`

## 5. API 契约（新增与改造）

统一前缀建议：`/api/runtime`

### 5.1 创建运行

- `POST /api/runtime/runs`
- Headers：`X-Idempotency-Key: <key>`
- Request

```json
{
  "agent_id": "DynamicAgent",
  "thread_id": "thread_xxx",
  "mode": "hybrid",
  "input": {
    "query": "请完成需求开发",
    "context": {}
  },
  "runtime_options": {
    "max_attempts": 2,
    "timeout_seconds": 900
  }
}
```

- Response `202`

```json
{
  "run_id": "run_xxx",
  "status": "queued"
}
```

### 5.2 查询运行详情

- `GET /api/runtime/runs/{run_id}`
- Response `200`

```json
{
  "run_id": "run_xxx",
  "status": "running",
  "mode": "hybrid",
  "attempt": 1,
  "cancel_requested": false,
  "timeline_summary": {
    "total_events": 128,
    "last_event_type": "tool.succeeded"
  }
}
```

### 5.3 拉取事件流

- `GET /api/runtime/runs/{run_id}/events?cursor=120&limit=200`
- Response `200`

```json
{
  "items": [],
  "next_cursor": 200
}
```

### 5.4 控制运行

- `POST /api/runtime/runs/{run_id}/cancel`
- `POST /api/runtime/runs/{run_id}/resume`
- `POST /api/runtime/runs/{run_id}/retry`

`retry` Request:

```json
{
  "from_step": "supervisor",
  "reason": "transient tool timeout"
}
```

### 5.5 审批决策

- `POST /api/runtime/runs/{run_id}/approvals`
- Request

```json
{
  "decision": "edit",
  "reason": "调整收件人与附件",
  "edited_args": {
    "to": "ops@example.com"
  }
}
```

### 5.6 产物索引

- `GET /api/runtime/runs/{run_id}/artifacts`
- `GET /api/runtime/artifacts/{artifact_id}/download`

## 6. 前端页面信息架构（IA）

### 6.1 新增页面与模块

- 运行中心 `/runtime`
  - 运行列表（状态、模式、耗时、失败原因）
  - 过滤器（agent/mode/status/time）
- 运行详情 `/runtime/:runId`
  - 时间线（Event Timeline）
  - 调度图（Route DAG）
  - 产物面板（Artifact Tree）
  - 控制台（Cancel/Resume/Retry）
  - 审批面板（Approve/Reject/Edit）

### 6.2 Chat 页面改造

- 将现有消息流与运行态解耦
- 消息区仅做对话展示
- 运行状态与事件下沉到 `RuntimePanel` 组件

### 6.3 Team Builder 改造

- 在右侧草稿区新增「治理预览」：
  - 依赖拓扑预检
  - 通信矩阵冲突提示
  - 权限矩阵预览（tools/mcps/skills/knowledges）
- 增加「按复杂度推荐模式」提示：disabled / supervisor / hybrid

## 7. 迁移清单（分阶段）

### 阶段 A：底座（必须先做）

- 新增 `agent_runs` / `run_events` / `idempotency_records`
- Tasker 接入 lease 与幂等键
- 运行控制 API（create/detail/cancel/retry/resume）

### 阶段 B：可观测

- 全链路事件落库
- 运行详情页与时间线
- 失败分层错误码与告警

### 阶段 C：权限边界

- 新增 `runtime_policy_bindings`
- Tool/MCP/Skill 调用前强制策略校验
- 审计事件补全（谁在何时调用了什么）

### 阶段 D：产物统一管理

- 建立 `run_artifacts`
- DeepAgents 文件路径标准化
- 下载、权限与清理策略

### 阶段 E：Hybrid 默认化

- 复杂任务默认 supervisor 规划 + 并行执行
- 轻任务走简化路径
- 完成性能基准回归

## 8. 逐文件实现任务列表（按当前目录）

### 8.1 后端路由层

- `server/routers/task_router.py`
  - 迁移任务查询到 run 语义（兼容旧 tasks）
  - 增加 cancel/retry/resume 透传
- `server/routers/chat_router.py`
  - chat 发起时返回 `run_id`
  - team 会话输出 run 控制入口
- `server/routers/system_router.py`
  - 增加 runtime 健康与队列状态探针
- 新增 `server/routers/runtime_router.py`
  - 实现 `/api/runtime/*` 契约

### 8.2 服务层

- `src/services/chat_stream_service.py`
  - 统一 run 生命周期事件写入
  - 将 `agent_state` 与 `run_events` 对齐
- `src/services/task_service.py`
  - 引入 lease、心跳、重试退避、幂等检查
  - 补齐 coroutine registry 与恢复路径
- `src/agent_platform/runtime/runtime_context_service.py`
  - 输出 runtime context、通信矩阵与治理策略草案
- 新增 `src/services/runtime_service.py`
  - run 创建、状态迁移、事件写入、控制命令
- 新增 `src/services/policy_service.py`
  - 权限策略匹配与 deny explain

### 8.3 Agent 与编排层

- `src/agents/dynamic_agent/context.py`
  - 增加 runtime_policy_profile、idempotency_scope、risk_level
- `src/agents/dynamic_agent/supervisor.py`
  - 路由决策写标准事件
  - 增加 ping-pong 熔断与全局轮次预算
- `src/agents/dynamic_agent/factory.py`
  - 引入 hybrid 入口（supervisor plan + deep execute）
- `src/agents/common/subagents/registry.py`
  - 移除默认自动注入工具，改显式策略放行
- `src/agents/common/deepagent_runtime.py`
  - 标准化 artifacts 路径与持久化路由

### 8.4 数据与存储层

- `src/storage/postgres/models_business.py`
  - 新增 AgentRun、RunEvent、RunArtifact、IdempotencyRecord、RuntimePolicyBinding、RunApproval
- 新增 `src/repositories/runtime_repository.py`
  - run + event + artifact 原子操作
- `src/repositories/task_repository.py`
  - 兼容 run_id 关联
- `src/storage/postgres/manager.py`
  - 启动时确保新表创建
- 新增迁移脚本 `scripts/migrate_runtime_tables.py`
  - 建表与索引回填

### 8.5 前端 API 与状态管理

- 新增 `web/src/apis/runtime_api.js`
  - 对应 `/api/runtime/*`
- `web/src/apis/tasker.js`
  - 兼容 run 模型字段
- 新增 `web/src/stores/runtime.js`
  - 运行列表、详情、时间线、控制动作
- `web/src/stores/tasker.js`
  - 从任务视图升级到 run/task 统一视图

### 8.6 前端页面与组件

- 新增 `web/src/views/RuntimeCenterView.vue`
- 新增 `web/src/views/RuntimeDetailView.vue`
- 新增 `web/src/components/runtime/RunTimeline.vue`
- 新增 `web/src/components/runtime/RunControls.vue`
- 新增 `web/src/components/runtime/ArtifactPanel.vue`
- `web/src/views/TeamBuilderView.vue`
  - 增加治理预览与模式推荐
- `web/src/components/AgentChatComponent.vue`
  - 去 prompt 式审批，改结构化审批交互

### 8.7 测试

- 新增 `test/test_runtime_service.py`
- 新增 `test/test_run_event_schema.py`
- 新增 `test/test_runtime_router.py`
- 新增 `test/test_idempotency.py`
- 扩展 `test/test_agent_manager_discovery.py` 与 runtime context 相关测试
- 扩展 `test/test_tool_resolver_mcp_scope.py`

## 9. 验收指标（上线门槛）

- 稳定性：运行恢复成功率 ≥ 99%
- 一致性：重复执行率 < 0.1%，取消后继续执行率 = 0
- 可观测：关键运行全链路事件覆盖率 = 100%
- 安全：越权调用拦截率 = 100%
- 体验：复杂任务失败可解释率 ≥ 95%

## 10. 实施顺序建议（两周一个里程碑）

- M1：A 阶段 + 最小 API + 最小运行详情页
- M2：B 阶段 + 时间线 + 告警
- M3：C 阶段 + 权限策略引擎
- M4：D/E 阶段 + Hybrid 默认化 + 性能回归

---

本蓝图默认保持现有 `create_deep_agent` 为复杂任务执行核心，新增运行时治理能力，不做推倒重写。
