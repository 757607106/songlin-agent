<template>
  <div class="dashboard-container layout-container">
    <!-- 顶部状态条 -->

    <!-- 现代化顶部统计栏 -->
    <div class="modern-stats-header">
      <StatusBar />
      <StatsOverviewComponent :basic-stats="basicStats" />
    </div>

    <!-- Grid布局的主要内容区域 -->
    <div class="dashboard-grid">
      <!-- 调用统计模块 - 占据2x1网格 -->
      <div class="grid-item call-stats">
        <CallStatsComponent :loading="loading" ref="callStatsRef" />
      </div>

      <!-- 用户活跃度分析 - 占据1x1网格 -->
      <div class="grid-item user-stats">
        <UserStatsComponent
          :user-stats="allStatsData?.users"
          :loading="loading"
          ref="userStatsRef"
        />
      </div>

      <!-- AI智能体分析 - 占据1x1网格 -->
      <div class="grid-item agent-stats">
        <AgentStatsComponent
          :agent-stats="allStatsData?.agents"
          :loading="loading"
          ref="agentStatsRef"
        />
      </div>

      <!-- 工具调用监控 - 占据1x1网格 -->
      <div class="grid-item tool-stats">
        <ToolStatsComponent
          :tool-stats="allStatsData?.tools"
          :loading="loading"
          ref="toolStatsRef"
        />
      </div>

      <!-- 知识库使用情况 - 占据1x1网格 -->
      <div class="grid-item knowledge-stats">
        <KnowledgeStatsComponent
          :knowledge-stats="allStatsData?.knowledge"
          :loading="loading"
          ref="knowledgeStatsRef"
        />
      </div>

      <!-- 对话记录 - 占据1x1网格 -->
      <div class="grid-item conversations">
        <div class="glass-panel conversations-panel">
          <div class="panel-header">
            <h3 class="title">对话记录</h3>
            <div class="actions">
              <a-space>
                <a-input
                  v-model:value="filters.user_id"
                  placeholder="用户ID"
                  size="small"
                  style="width: 120px"
                  @change="handleFilterChange"
                  class="custom-input"
                />
                <a-select
                  v-model:value="filters.status"
                  placeholder="状态"
                  size="small"
                  style="width: 100px"
                  @change="handleFilterChange"
                  class="custom-select"
                >
                  <a-select-option value="active">活跃</a-select-option>
                  <a-select-option value="deleted">已删除</a-select-option>
                  <a-select-option value="all">全部</a-select-option>
                </a-select>
                <a-button size="small" @click="loadConversations" :loading="loading">
                  刷新
                </a-button>
                <a-button size="small" @click="feedbackModal.show()"> 反馈详情 </a-button>
              </a-space>
            </div>
          </div>

          <div class="panel-body">
            <a-table
              :columns="conversationColumns"
              :data-source="conversations"
              :loading="loading"
              :pagination="conversationPagination"
              @change="handleTableChange"
              row-key="thread_id"
              size="small"
              class="custom-table"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'title'">
                  <a
                    @click="handleViewDetail(record)"
                    class="conversation-title"
                    :class="{ loading: loadingDetail }"
                    >{{ record.title || '未命名对话' }}</a
                  >
                </template>
                <template v-if="column.key === 'status'">
                  <a-tag :color="record.status === 'active' ? 'success' : 'error'" size="small">
                    {{ record.status === 'active' ? '活跃' : '已删除' }}
                  </a-tag>
                </template>
                <template v-if="column.key === 'updated_at'">
                  <span class="time-text">{{ formatDate(record.updated_at) }}</span>
                </template>
                <template v-if="column.key === 'actions'">
                  <a-button
                    type="link"
                    size="small"
                    @click="handleViewDetail(record)"
                    :loading="loadingDetail"
                  >
                    详情
                  </a-button>
                </template>
              </template>
            </a-table>
          </div>
        </div>
      </div>
    </div>

    <!-- 反馈模态框 -->
    <FeedbackModalComponent ref="feedbackModal" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'
import { dashboardApi } from '@/apis/dashboard_api'
import dayjs, { parseToShanghai } from '@/utils/time'

// 导入子组件
import StatusBar from '@/components/StatusBar.vue'
import UserStatsComponent from '@/components/dashboard/UserStatsComponent.vue'
import ToolStatsComponent from '@/components/dashboard/ToolStatsComponent.vue'
import KnowledgeStatsComponent from '@/components/dashboard/KnowledgeStatsComponent.vue'
import AgentStatsComponent from '@/components/dashboard/AgentStatsComponent.vue'
import CallStatsComponent from '@/components/dashboard/CallStatsComponent.vue'
import StatsOverviewComponent from '@/components/dashboard/StatsOverviewComponent.vue'
import FeedbackModalComponent from '@/components/dashboard/FeedbackModalComponent.vue'

// 组件引用
const feedbackModal = ref(null)

// 统计数据 - 使用新的响应式结构
const basicStats = ref({})
const allStatsData = ref({
  users: null,
  tools: null,
  knowledge: null,
  agents: null
})

// 过滤器
const filters = reactive({
  user_id: '',
  agent_id: '',
  status: 'active'
})

// 对话列表
const conversations = ref([])
const loading = ref(false)
const loadingDetail = ref(false)

// 调用统计子组件引用
const callStatsRef = ref(null)

// 分页
const conversationPagination = reactive({
  current: 1,
  pageSize: 8,
  total: 0,
  showSizeChanger: false,
  showQuickJumper: false,
  showTotal: (total, range) => `${range[0]}-${range[1]} / ${total}`
})

// 表格列定义
const conversationColumns = [
  {
    title: '对话标题',
    dataIndex: 'title',
    key: 'title',
    ellipsis: true
  },
  {
    title: '用户',
    dataIndex: 'user_id',
    key: 'user_id',
    width: '100px',
    ellipsis: true
  },
  {
    title: '消息数',
    dataIndex: 'message_count',
    key: 'message_count',
    width: '80px',
    align: 'center'
  },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    width: '80px',
    align: 'center'
  },
  {
    title: '更新时间',
    dataIndex: 'updated_at',
    key: 'updated_at',
    width: '140px'
  },
  {
    title: '操作',
    key: 'actions',
    width: '80px',
    align: 'center'
  }
]

// 子组件引用
const userStatsRef = ref(null)
const toolStatsRef = ref(null)
const knowledgeStatsRef = ref(null)
const agentStatsRef = ref(null)

// 加载统计数据 - 使用并行API调用
const loadAllStats = async () => {
  loading.value = true
  try {
    // 使用并行API调用获取所有统计数据
    const response = await dashboardApi.getAllStats()

    // 更新基础统计数据
    basicStats.value = response.basic

    // 更新详细统计数据
    allStatsData.value = {
      users: response.users,
      tools: response.tools,
      knowledge: response.knowledge,
      agents: response.agents
    }

    console.log('Dashboard 数据加载完成:', response)
    message.success('数据加载成功')
  } catch (error) {
    console.error('加载统计数据失败:', error)
    message.error('加载统计数据失败')

    // 如果并行请求失败，尝试单独加载基础数据
    try {
      const basicResponse = await dashboardApi.getStats()
      basicStats.value = basicResponse
      message.warning('详细数据加载失败，仅显示基础统计')
    } catch (basicError) {
      console.error('加载基础统计数据也失败:', basicError)
      message.error('无法加载任何统计数据')
    }
  } finally {
    loading.value = false
  }
}

// 保留原有的loadStats函数以兼容旧代码
const loadStats = loadAllStats

// 加载对话列表
const loadConversations = async () => {
  try {
    const params = {
      user_id: filters.user_id || undefined,
      agent_id: filters.agent_id || undefined,
      status: filters.status,
      limit: conversationPagination.pageSize,
      offset: (conversationPagination.current - 1) * conversationPagination.pageSize
    }

    const response = await dashboardApi.getConversations(params)
    conversations.value = response
    // Note: 由于后端没有返回总数，这里暂时设置为当前数据长度
    conversationPagination.total = response.length
  } catch (error) {
    console.error('加载对话列表失败:', error)
    message.error('加载对话列表失败')
  }
}

// 日期格式化
const formatDate = (dateString) => {
  if (!dateString) return '-'
  const parsed = parseToShanghai(dateString)
  if (!parsed) return '-'
  const now = dayjs().tz('Asia/Shanghai')
  const diffDays = now.startOf('day').diff(parsed.startOf('day'), 'day')

  if (diffDays === 0) {
    return parsed.format('HH:mm')
  }
  if (diffDays === 1) {
    return '昨天'
  }
  if (diffDays < 7) {
    return `${diffDays}天前`
  }
  return parsed.format('MM-DD')
}

// 查看对话详情
const handleViewDetail = async (record) => {
  try {
    loadingDetail.value = true
    const detail = await dashboardApi.getConversationDetail(record.thread_id)
    console.log(detail)
  } catch (error) {
    console.error('获取对话详情失败:', error)
    message.error('获取对话详情失败')
  } finally {
    loadingDetail.value = false
  }
}

// 处理过滤器变化
const handleFilterChange = () => {
  conversationPagination.current = 1
  loadConversations()
}

// 处理表格变化
const handleTableChange = (pag) => {
  conversationPagination.current = pag.current
  conversationPagination.pageSize = pag.pageSize
  loadConversations()
}

// 清理函数 - 清理所有子组件的图表实例
const cleanupCharts = () => {
  if (userStatsRef.value?.cleanup) userStatsRef.value.cleanup()
  if (toolStatsRef.value?.cleanup) userStatsRef.value.cleanup()
  if (knowledgeStatsRef.value?.cleanup) knowledgeStatsRef.value.cleanup()
  if (agentStatsRef.value?.cleanup) agentStatsRef.value.cleanup()
  if (callStatsRef.value?.cleanup) callStatsRef.value.cleanup()
}

// 初始化
onMounted(() => {
  loadAllStats()
  loadConversations()
})

// 组件卸载时清理图表
onUnmounted(() => {
  cleanupCharts()
})
</script>

<style scoped lang="less">
.dashboard-container {
  background-color: var(--gray-50);
  padding: 24px;
  overflow-x: hidden;
}

.modern-stats-header {
  margin-bottom: 24px;
}

// Dashboard 特有的网格布局
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: auto auto auto;
  gap: 20px;
  margin-bottom: 24px;

  .grid-item {
    border-radius: 16px;
    // overflow: hidden; // Removed to allow shadows/popups
    display: flex;
    flex-direction: column;
    min-height: 320px;

    // 子组件应该自己包含 glass-panel 类或者类似样式
    :deep(.glass-panel),
    :deep(.ant-card) {
      height: 100%;
      border-radius: 16px;
      border: 1px solid var(--gray-200);
      background: var(--gray-0);
      box-shadow: 0 4px 6px -1px var(--shadow-color);
      transition: all 0.3s ease;

      &:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px var(--shadow-color-lg);
      }
    }

    // 大页面布局
    &.call-stats {
      grid-column: 1 / 3;
      grid-row: 1 / 2;
    }

    &.user-stats {
      grid-column: 3 / 4;
      grid-row: 1 / 2;
    }

    &.agent-stats {
      grid-column: 1 / 2;
      grid-row: 2 / 3;
    }

    &.tool-stats {
      grid-column: 2 / 3;
      grid-row: 2 / 3;
    }

    &.knowledge-stats {
      grid-column: 3 / 4;
      grid-row: 2 / 3;
    }

    &.conversations {
      grid-column: 1 / 4;
      grid-row: 3 / 4;
      min-height: 400px;
    }
  }
}

// 对话记录面板样式
.conversations-panel {
  display: flex;
  flex-direction: column;
  padding: 0;
  height: 100%;

  .panel-header {
    padding: 16px 24px;
    border-bottom: 1px solid var(--gray-200);
    display: flex;
    justify-content: space-between;
    align-items: center;

    .title {
      font-size: 16px;
      font-weight: 600;
      color: var(--gray-900);
      margin: 0;
    }
  }

  .panel-body {
    padding: 16px 24px;
    flex: 1;
    overflow: hidden;
  }
}

.conversation-title {
  color: var(--primary-600);
  font-weight: 500;
  transition: color 0.2s;

  &:hover {
    color: var(--primary-700);
    text-decoration: underline;
  }
}

.time-text {
  color: var(--gray-500);
  font-size: 13px;
}

:deep(.custom-input),
:deep(.custom-select .ant-select-selector) {
  border-radius: 6px !important;
}

:deep(.custom-table) {
  .ant-table-thead > tr > th {
    background: var(--gray-50);
    color: var(--gray-700);
    font-weight: 600;
  }
}

// 响应式设计
@media (max-width: 1200px) {
  .dashboard-grid {
    grid-template-columns: 1fr 1fr;

    .grid-item {
      &.call-stats {
        grid-column: 1 / 3;
      }
      &.user-stats {
        grid-column: 1 / 2;
        grid-row: 2 / 3;
      }
      &.agent-stats {
        grid-column: 2 / 3;
        grid-row: 2 / 3;
      }
      &.tool-stats {
        grid-column: 1 / 2;
        grid-row: 3 / 4;
      }
      &.knowledge-stats {
        grid-column: 2 / 3;
        grid-row: 3 / 4;
      }
      &.conversations {
        grid-column: 1 / 3;
        grid-row: 4 / 5;
      }
    }
  }
}

@media (max-width: 768px) {
  .dashboard-container {
    padding: 16px;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
    gap: 16px;

    .grid-item {
      grid-column: 1 / 2 !important;
      grid-row: auto !important;
    }
  }
}
</style>
