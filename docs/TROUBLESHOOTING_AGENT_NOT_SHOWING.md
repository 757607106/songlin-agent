# 智能体未显示问题排查

截至 2026 年 3 月 11 日，当前项目的 Agent 暴露策略已经变化：

- 自动注册的运行时入口只有 `SqlReporterAgent` 和 `AgentPlatformAgent`
- 产品默认可见的内置 Agent 只有 `SqlReporterAgent`
- 旧的 `ChatbotAgent / DeepAgent / DocOrganizerAgent / ArchitectAgent / DynamicAgent` 已经移除，不再显示属于正常行为

如果你看到的结果和旧文档不一样，先以当前规则为准。

## 先判断是不是“预期行为”

### 情况 1：智能体广场只看到“数据库报表助手”

这是预期行为。当前产品内置默认只保留：

- `数据库报表助手`

`AgentPlatformAgent` 是内部运行时入口，不作为产品内置卡片直接展示。

### 情况 2：我创建的自定义 Agent 没看到

这时要查的是自定义配置，而不是旧 built-in Agent。

请确认：

1. 是否已经通过 `/api/agent-design/deploy` 成功部署
2. 是否存在 `AgentPlatformAgent` 对应的配置记录
3. 当前部门下是否能查到该配置

相关接口：

- `GET /api/chat/agent`
- `GET /api/chat/agent/AgentPlatformAgent/configs`

### 情况 3：期望看到旧的聊天助手、深度分析助手

这不是故障。它们已经不再作为公开 Agent 注册，能力已迁移为：

- templates
- examples
- worker/runtime 组件

## 当前注册机制

系统会在 `src/agents/__init__.py` 中自动发现允许暴露的模块。当前只会注册：

- `src/agents/reporter`
- `src/agents/agent_platform`

你可以用下面的命令核对当前注册状态：

```bash
docker compose exec api uv run python scripts/check_agents.py
```

预期输出应至少包含：

- `SqlReporterAgent`
- `AgentPlatformAgent`

并明确说明：

- `SqlReporterAgent` 是产品内置 Agent
- `AgentPlatformAgent` 是内部运行时入口

## 推荐排查步骤

### 1. 检查容器是否正常运行

```bash
docker compose ps
```

重点看：

- `api`
- `web`

### 2. 查看后端热重载日志

```bash
docker compose logs api --tail 100
```

启动或热重载后，应该能看到类似日志：

```text
自动发现智能体: AgentPlatformAgent 来自 agent_platform
自动发现智能体: SqlReporterAgent 来自 reporter
```

如果这里缺项，说明模块导入或初始化失败。

### 3. 检查公开 Agent 列表

```bash
curl -H "Authorization: Bearer <your_token>" \
  http://localhost:5050/api/chat/agent
```

当前返回里通常会包含两个运行时入口：

- `SqlReporterAgent`
- `AgentPlatformAgent`

但只有 `SqlReporterAgent` 会带 `product_visible=true`。

### 4. 检查自定义 Agent 配置

如果问题是“自定义 Agent 没显示”，继续检查：

```bash
curl -H "Authorization: Bearer <your_token>" \
  http://localhost:5050/api/chat/agent/AgentPlatformAgent/configs
```

如果这里为空，说明不是显示问题，而是还没有部署成功。

### 5. 检查一句话创建链路

确认设计期链路正常：

- `POST /api/agent-design/draft`
- `POST /api/agent-design/validate`
- `POST /api/agent-design/compile`
- `POST /api/agent-design/deploy`

如果 `deploy` 没成功，自定义 Agent 不会出现在配置列表里。

## 常见原因

### 原因 1：把“旧 built-in 不显示”误判成故障

这是最常见情况。旧 built-in 已移除，不需要修复。

### 原因 2：后端没热重载成功

表现：

- 新代码已经改了
- `/api/chat/agent` 结果还是旧的

先看：

```bash
docker compose logs api --tail 100
```

### 原因 3：自定义 Agent 只 draft/compile 了，没有 deploy

这种情况下 `AgentPlatformAgent` 运行时入口存在，但配置列表为空。

### 原因 4：当前用户没有部门

设计期部署和配置列表都依赖部门；用户未绑定部门时，自定义 Agent 无法正常落库。

## 快速检查命令

```bash
docker compose exec api uv run python scripts/check_agents.py
docker compose logs api --tail 100
```

## 总结

如果你只看到“数据库报表助手”，通常是正常行为，不是故障。

真正需要排查的是两类问题：

1. `SqlReporterAgent` 本身没有被自动发现
2. 自定义 Agent 的 `AgentPlatformAgent` 配置没有成功部署
