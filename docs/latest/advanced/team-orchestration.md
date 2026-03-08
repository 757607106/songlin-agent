# 多 Agent 团队编排

`DynamicAgent` 现支持基于对话的团队创建、职责边界校验和三模式协作执行（`disabled / supervisor / deep_agents`）。
最新版本支持「一句话自动组队」与「一键落库创建配置」。
同时新增「聊天式团队组建会话」能力，可在多轮问答中持续完善草稿并恢复历史会话。

## 核心能力

- 对话式团队创建（自然语言增量补全）
- 一句话自动组队（AI 自动补全团队目标、角色分工、依赖关系）
- 职责重叠检测与依赖拓扑校验
- 循环调用检测与重试上限保护
- 通信矩阵强约束（越界路由自动拦截）
- 资源权限矩阵（tools/knowledges/mcps/skills）
- Supervisor 可观测执行日志（route/retry/completed）

## 主要 API

- `POST /api/chat/agent/DynamicAgent/team/wizard`
- `POST /api/chat/agent/DynamicAgent/team/validate`
- `POST /api/chat/agent/DynamicAgent/team/create`
- `POST /api/chat/agent/DynamicAgent/team/auto-create`
- `POST /api/chat/agent/DynamicAgent/team/langchain-docs`
- `POST /api/chat/agent/DynamicAgent/team/benchmark`
- `POST /api/chat/agent/DynamicAgent/team/session`
- `GET /api/chat/agent/DynamicAgent/team/sessions`
- `GET /api/chat/agent/DynamicAgent/team/session/{thread_id}`
- `POST /api/chat/agent/DynamicAgent/team/session/{thread_id}/message`
- `POST /api/chat/agent/DynamicAgent/team/session/{thread_id}/message/stream`
- `PUT /api/chat/agent/DynamicAgent/team/session/{thread_id}/draft`
- `POST /api/chat/agent/DynamicAgent/team/session/{thread_id}/create`

## 推荐流程

1. 直接调用 `team/auto-create`，一句话完成组队并保存
2. 或先用 `team/wizard` 补全草稿
3. 用 `team/validate` 修正职责和依赖问题
4. 用 `team/create` 落库成配置并设为默认
5. 正式发起对话任务

## 聊天式组队页面

前端新增独立的「聊天式团队组建」页面（`/team-builder`）：

- 左侧：会话列表 + 多轮问答
- 右侧：实时草稿 + 严格校验 + 一键创建配置
- 支持主智能体与子智能体 tools/knowledges/mcps/skills 的可视化选择与校验
- 子智能体依赖（depends_on）与允许通信目标（allowed_targets）支持基于当前角色名称的下拉选择
- 子智能体通信模式（communication_mode）与重试上限（max_retries）支持可视化配置
- 草稿会话复用 `conversations.extra_metadata` 存储，`session_type=team_builder`

## 模式选择

- `disabled`: 简单任务，单智能体即可
- `supervisor`: 需要强治理与可观测过程
- `deep_agents`: 任务可并行，关注吞吐效率（默认强调 `write_todos + task + filesystem`）

## 参考文档

- 架构说明：`docs/vibe/multi-agent-team-system/architecture.md`
- 用户手册：`docs/vibe/multi-agent-team-system/user-manual.md`
- 性能报告：`docs/vibe/multi-agent-team-system/performance-benchmark.md`
