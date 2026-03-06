# 本地启动指南

本文档用于在本机直接运行前后端进程（不使用前后端容器），数据库等基础服务使用 Docker 启动。

---

## 前置条件

- Docker Desktop 已安装并**正在运行**
- [uv](https://docs.astral.sh/uv/) 已安装（Python 包管理工具）
- [pnpm](https://pnpm.io/) 已安装（前端包管理工具）
- Git 已安装

---

## 架构说明

```
本地运行（直接在操作系统上运行）：
  ├── 前端（localhost:5173）- pnpm dev 启动
  └── 后端（localhost:5050）- uvicorn 启动

Docker 容器运行（基础服务）：
  ├── PostgreSQL（localhost:5432）
  ├── Neo4j（localhost:7687）
  ├── Etcd（localhost:2379）
  ├── MinIO（localhost:9000）
  └── Milvus（localhost:19530）
```

---

## 🐳 第 1 步：启动 Docker 基础服务

Docker 基础服务提供数据库和缓存支持。这一步必须首先完成。

### 1.1 启动所有基础服务（推荐）

```bash
make local-deps
```

或手动执行：

```bash
docker compose up -d postgres graph etcd minio milvus
```

### 1.2 验证服务启动

```bash
docker compose ps
```

**预期输出**：5 个容器处于 `running` 状态

```
NAME               IMAGE                          PORTS              STATUS
postgres           postgres:15                    0.0.0.0:5432       Up
graph              neo4j:5.16                     0.0.0.0:7474       Up
milvus-etcd-dev    quay.io/coreos/etcd            0.0.0.0:2379       Up
milvus-minio       minio/minio                    0.0.0.0:9000       Up
milvus             milvusdb/milvus                0.0.0.0:19530      Up
```

### 1.3 各基础服务说明

| 服务 | 容器名 | 用途 | 端口 | 访问地址 |
|------|--------|------|------|---------|
| PostgreSQL | postgres | 关系数据库 | 5432 | - |
| Neo4j | graph | 知识图数据库 | 7687 | http://localhost:7474 |
| Etcd | milvus-etcd-dev | 分布式配置 | 2379 | - |
| MinIO | milvus-minio | 对象存储 | 9000, 9001 | http://localhost:9001 |
| Milvus | milvus | 向量数据库 | 19530 | - |

### 1.4 查看服务日志

```bash
# 查看所有服务日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f postgres
docker compose logs -f graph
```

### 1.5 等待服务就绪

```bash
# PostgreSQL 就绪信号
docker compose logs postgres | grep "ready to accept"

# Neo4j 就绪信号
docker compose logs graph | grep "started"

# Milvus 就绪信号
docker compose logs milvus | grep "successfully"
```

---

## 🖥️ 第 2 步：启动后端服务（本地）

**前置条件**：确保 Docker 基础服务已启动（第 1 步）

在新的终端窗口中运行。

### 2.1 快速启动（推荐）

```bash
make local-api
```

### 2.2 手动启动

```bash
POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know \
CHECKPOINTER_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/yuxi_know \
NEO4J_URI=bolt://localhost:7687 \
MILVUS_URI=http://localhost:19530 \
MINIO_URI=http://localhost:9000 \
uv run uvicorn server.main:app --host 0.0.0.0 --port 5050 --reload
```

### 2.3 验证后端启动

查看终端输出，应该看到：

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete
INFO:     Uvicorn running on http://0.0.0.0:5050
```

### 2.4 检查后端健康状态

```bash
# 健康检查 API
curl http://localhost:5050/health

# 或在浏览器访问 API 文档
http://localhost:5050/docs
```

### 2.5 后端代码自动重载

后端已配置 `--reload` 模式，修改代码后会自动重载。

---

## 🎨 第 3 步：启动前端服务（本地）

**前置条件**：确保后端已启动（第 2 步）

在第三个终端窗口中运行。

### 3.1 快速启动（推荐）

```bash
make local-web
```

### 3.2 手动启动

```bash
cd web
VITE_API_URL=http://localhost:5050 pnpm run dev
```

### 3.3 验证前端启动

查看终端输出，应该看到：

```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
  ➜  press h + enter to show help
```

### 3.4 访问前端

在浏览器打开：http://localhost:5173

### 3.5 前端代码自动重载

修改前端代码后，浏览器会自动刷新。

---

## 📍 完整启动流程

### 开发者推荐流程

开发时建议使用 **3 个独立的终端窗口**，分别运行三个服务。

```bash
# ===== 终端 1 =====
# 启动 Docker 基础服务
make local-deps

# 等待服务启动完成，看到所有容器 running 状态

# ===== 终端 2 =====
# 启动后端
make local-api

# 等待后端启动完成，看到 "Application startup complete"

# ===== 终端 3 =====
# 启动前端
make local-web

# 等待前端启动完成，看到 "ready in xxx ms"
```

### 访问应用

所有服务启动后，在浏览器中访问：

- **前端应用**: http://localhost:5173
- **API 文档**: http://localhost:5050/docs
- **Neo4j 图数据库**: http://localhost:7474
- **MinIO 对象存储**: http://localhost:9001

---

## 🔗 服务地址总览

### 应用服务（本地运行）

| 服务 | URL | 描述 |
|------|-----|------|
| 前端应用 | http://localhost:5173 | 主应用界面 |
| 后端 API | http://localhost:5050 | REST API 服务 |
| Swagger 文档 | http://localhost:5050/docs | API 文档界面 |
| 健康检查 | http://localhost:5050/health | 后端健康状态 |

### 管理界面（Docker 基础服务）

| 服务 | URL | 功能 |
|------|-----|------|
| Neo4j 浏览器 | http://localhost:7474 | 知识图数据库管理 |
| MinIO 控制台 | http://localhost:9001 | 对象存储管理 |

### 数据库连接信息（Docker 基础服务）

| 数据库 | 连接 | 用户 | 密码 | 数据库 |
|--------|------|------|------|--------|
| PostgreSQL | localhost:5432 | postgres | postgres | yuxi_know |
| Neo4j | bolt://localhost:7687 | neo4j | (见初始密码) | - |

---

## ⚙️ 环境变量配置

### 后端环境变量

使用 `make local-api` 启动时，这些环境变量会自动设置：

```bash
POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/yuxi_know
CHECKPOINTER_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/yuxi_know
NEO4J_URI=bolt://localhost:7687
MILVUS_URI=http://localhost:19530
MINIO_URI=http://localhost:9000
```

### 前端环境变量

使用 `make local-web` 启动时，这些环境变量会自动设置：

```bash
VITE_API_URL=http://localhost:5050
VITE_WS_URL=ws://localhost:5050
```

---

## 🔍 故障排查

### 问题 1: 后端无法连接 Docker 基础服务

**现象**：
```
ConnectionRefusedError: [Errno 111] Connection refused
```

**解决**：

```bash
# 1. 检查 Docker 基础服务
docker compose ps

# 2. 启动服务
docker compose up -d postgres graph etcd minio milvus

# 3. 等待就绪
sleep 20

# 4. 重启后端
make local-api
```

### 问题 2: 后端端口 5050 被占用

**现象**：
```
Address already in use: ('0.0.0.0', 5050)
```

**解决**：

```bash
# 查找占用进程
lsof -i :5050

# 终止进程
kill -9 <PID>

# 重启后端
make local-api
```

### 问题 3: 前端无法连接后端

**现象**：API 连接失败，CORS 错误

**解决**：

```bash
# 1. 检查后端运行状态
curl http://localhost:5050/health

# 2. 检查前端环境变量
echo $VITE_API_URL

# 3. 重启前端并刷新浏览器
cd web && VITE_API_URL=http://localhost:5050 pnpm run dev
```

### 问题 4: PostgreSQL 初始化失败

**现象**：
```
could not connect to server
```

**解决**：

```bash
# 完全重置 PostgreSQL
docker compose down -v postgres
docker compose up -d postgres

# 等待初始化
sleep 30

# 验证
docker compose logs postgres | grep "ready"

# 重启后端
make local-api
```

### 问题 5: 看不到智能体

**现象**：智能体列表为空或不完整

**解决**：

```bash
# 验证智能体注册
uv run python scripts/check_agents.py

# 重启后端
make local-api

# 刷新浏览器
# Ctrl+Shift+R 或 Cmd+Shift+R
```

更多问题排查，参考：[FIX_AGENT_NOT_SHOWING.md](./docs/FIX_AGENT_NOT_SHOWING.md)

---

## 🛑 停止和清理

### 停止所有服务（保留数据）

```bash
# 停止本地应用（在各终端按 Ctrl+C）
# 停止 Docker 服务
docker compose stop
```

### 完全停止并清空数据

```bash
docker compose down -v
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete
```

---

## 📚 相关文档

- [Docker Compose 配置](./docker-compose.yml)
- [项目架构](./docs/ARCHITECTURE_AND_TECH_STACK.md)
- [智能体配置](./docs/AGENTS.md)
- [智能体问题排查](./docs/FIX_AGENT_NOT_SHOWING.md)
- [后端 API 文档](http://localhost:5050/docs)（启动后运行访问）
