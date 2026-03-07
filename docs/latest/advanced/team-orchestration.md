# 多 Agent 团队编排

`DynamicAgent` 现支持基于对话的团队创建、职责边界校验和三模式协作执行（`disabled / supervisor / deep_agents`）。

## 核心能力

- 对话式团队创建（自然语言增量补全）
- 职责重叠检测与依赖拓扑校验
- 循环调用检测与重试上限保护
- 通信矩阵强约束（越界路由自动拦截）
- 资源权限矩阵（tools/knowledges/mcps）
- Supervisor 可观测执行日志（route/retry/completed）

## 主要 API

- `POST /api/chat/agent/DynamicAgent/team/wizard`
- `POST /api/chat/agent/DynamicAgent/team/validate`
- `POST /api/chat/agent/DynamicAgent/team/create`
- `POST /api/chat/agent/DynamicAgent/team/langchain-docs`
- `POST /api/chat/agent/DynamicAgent/team/benchmark`

## 推荐流程

1. 先用 `team/wizard` 补全草稿
2. 用 `team/validate` 修正职责和依赖问题
3. 用 `team/create` 落库成配置并设为默认
4. 正式发起对话任务

## 模式选择

- `disabled`: 简单任务，单智能体即可
- `supervisor`: 需要强治理与可观测过程
- `deep_agents`: 任务可并行，关注吞吐效率

## 参考文档

- 架构说明：`docs/vibe/multi-agent-team-system/architecture.md`
- 用户手册：`docs/vibe/multi-agent-team-system/user-manual.md`
- 性能报告：`docs/vibe/multi-agent-team-system/performance-benchmark.md`
