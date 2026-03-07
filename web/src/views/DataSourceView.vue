<template>
  <div class="datasource-container layout-container">
    <div class="glass-panel">
      <HeaderComponent title="数据源管理" :loading="state.loading">
        <template #actions>
          <a-button type="primary" @click="openCreateModal">
            <template #icon><PlusOutlined /></template>
            新建连接
          </a-button>
        </template>
      </HeaderComponent>

      <!-- 连接创建/编辑模态框 -->
      <a-modal
        :open="state.modalVisible"
        :title="state.editingId ? '编辑连接' : '新建连接'"
        :confirm-loading="state.submitting"
        @ok="handleSubmit"
        @cancel="closeModal"
        width="600px"
        destroyOnClose
        class="custom-modal"
        :maskClosable="false"
      >
        <a-form :model="formData" layout="vertical" class="custom-form">
          <a-form-item label="连接名称" required>
            <a-input v-model:value="formData.name" placeholder="请输入连接名称" size="large" />
          </a-form-item>

          <a-form-item label="数据库类型" required>
            <a-select v-model:value="formData.db_type" placeholder="请选择数据库类型" size="large">
              <a-select-option value="mysql">MySQL</a-select-option>
              <a-select-option value="postgresql">PostgreSQL</a-select-option>
              <a-select-option value="sqlite">SQLite</a-select-option>
            </a-select>
          </a-form-item>

          <template v-if="formData.db_type !== 'sqlite'">
            <a-row :gutter="16">
              <a-col :span="16">
                <a-form-item label="主机地址">
                  <a-input v-model:value="formData.host" placeholder="localhost" size="large" />
                </a-form-item>
              </a-col>
              <a-col :span="8">
                <a-form-item label="端口">
                  <a-input-number
                    v-model:value="formData.port"
                    :placeholder="formData.db_type === 'mysql' ? '3306' : '5432'"
                    style="width: 100%"
                    size="large"
                  />
                </a-form-item>
              </a-col>
            </a-row>

            <a-row :gutter="16">
              <a-col :span="12">
                <a-form-item label="用户名">
                  <a-input v-model:value="formData.username" placeholder="请输入用户名" size="large" />
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item label="密码">
                  <a-input-password v-model:value="formData.password" placeholder="请输入密码" size="large" />
                </a-form-item>
              </a-col>
            </a-row>
          </template>

          <a-form-item label="数据库名" required>
            <a-input
              v-model:value="formData.database"
              :placeholder="formData.db_type === 'sqlite' ? '数据库文件路径' : '请输入数据库名'"
              size="large"
            />
          </a-form-item>
        </a-form>
      </a-modal>

      <!-- Schema 查看模态框 -->
      <a-modal
        :open="state.schemaModalVisible"
        :title="null"
        @cancel="closeSchemaModal"
        width="95vw"
        :style="{ maxWidth: '1600px', top: '20px' }"
        :body-style="{ height: 'calc(100vh - 40px)', padding: '0', overflow: 'hidden', display: 'flex', flexDirection: 'column' }"
        :footer="null"
        class="full-screen-modal"
        wrapClassName="full-screen-modal-wrap"
      >
        <div class="schema-modal-header">
          <div class="header-title">
            <DatabaseOutlined class="icon" />
            <span>数据源详情 - {{ state.currentConnection?.name || '' }}</span>
          </div>
          <a-button type="text" class="close-btn" @click="closeSchemaModal">
            <CloseOutlined />
          </a-button>
        </div>

        <div v-if="state.schemaLoading" class="schema-loading">
          <a-spin size="large" />
          <p>正在加载 Schema 信息...</p>
        </div>
        
        <div v-else-if="state.schema" class="schema-content">
          <a-tabs v-model:activeKey="state.activeTab" class="schema-tabs" type="card">
            <a-tab-pane key="diagram" tab="ER 关系图">
              <div class="diagram-container">
                <SchemaFlow
                  :connection-id="state.currentConnection?.id"
                  :schema="state.schema"
                  @refresh="refreshSchema"
                />
              </div>
            </a-tab-pane>
            <a-tab-pane key="tables" tab="表结构列表">
              <div class="tab-content">
                <a-collapse accordion ghost class="custom-collapse">
                  <a-collapse-panel
                    v-for="table in state.schema.tables"
                    :key="table.id"
                    :header="table.table_name"
                  >
                    <template #extra>
                      <span class="table-comment-preview">{{ table.table_comment || '无注释' }}</span>
                    </template>
                    <div class="table-detail-wrapper">
                      <p v-if="table.table_comment" class="table-comment-full">
                        <InfoCircleOutlined /> {{ table.table_comment }}
                      </p>
                      <a-table
                        :columns="columnTableColumns"
                        :data-source="table.columns"
                        :pagination="false"
                        size="small"
                        rowKey="id"
                        bordered
                        class="custom-table"
                      />
                    </div>
                  </a-collapse-panel>
                </a-collapse>
              </div>
            </a-tab-pane>
            <a-tab-pane key="relationships" tab="关联关系">
              <div class="tab-content">
                <a-table
                  :columns="relationshipColumns"
                  :data-source="state.schema.relationships"
                  :pagination="false"
                  size="middle"
                  rowKey="id"
                  class="custom-table"
                />
              </div>
            </a-tab-pane>
            <a-tab-pane key="mappings" tab="值映射管理">
              <div class="tab-content">
                <div class="mappings-header">
                  <div class="info-box">
                    <InfoCircleOutlined class="icon" />
                    <p class="mappings-desc">
                      值映射用于将自然语言表达转换为数据库中的实际值，提高 SQL 生成准确性。例如将 "男" 映射为 "1"。
                    </p>
                  </div>
                  <a-button type="primary" @click="openMappingModal">
                    <template #icon><PlusOutlined /></template>
                    添加映射
                  </a-button>
                </div>
                <a-table
                  :columns="mappingColumns"
                  :data-source="state.valueMappings"
                  :pagination="false"
                  size="middle"
                  rowKey="id"
                  class="custom-table"
                >
                  <template #bodyCell="{ column, record }">
                    <template v-if="column.key === 'action'">
                      <a-popconfirm
                        title="确定删除此映射？"
                        @confirm="handleDeleteMapping(record.id)"
                        placement="topRight"
                      >
                        <a-button type="text" size="small" danger>
                          <template #icon><DeleteOutlined /></template>
                        </a-button>
                      </a-popconfirm>
                    </template>
                  </template>
                </a-table>
              </div>
            </a-tab-pane>
            <a-tab-pane key="skills" tab="业务技能">
              <div class="tab-content">
                <div class="mappings-header">
                  <div class="info-box">
                    <BulbOutlined class="icon" />
                    <p class="mappings-desc">按业务场景和指标生成 Skills，可供报表助手直接调用。</p>
                  </div>
                  <div class="action-group">
                    <a-button @click="refreshSkills">
                      <template #icon><ReloadOutlined /></template>
                      刷新
                    </a-button>
                    <a-button type="primary" @click="openSkillModal">
                      <template #icon><PlusOutlined /></template>
                      生成技能
                    </a-button>
                  </div>
                </div>
                <a-table
                  :columns="[
                    { title: '技能ID', dataIndex: 'id', key: 'id', width: 100, ellipsis: true },
                    { title: '业务场景', dataIndex: 'business_scenario', key: 'business_scenario' },
                    { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
                    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 180 },
                    { title: '操作', key: 'action', width: 120, align: 'center' }
                  ]"
                  :data-source="state.skills"
                  :loading="state.skillsLoading"
                  :pagination="false"
                  size="middle"
                  rowKey="id"
                  class="custom-table"
                >
                  <template #bodyCell="{ column, record }">
                    <template v-if="column.key === 'status'">
                      <a-tag :color="record.status === 'published' ? 'success' : 'warning'">
                        {{ record.status === 'published' ? '已发布' : '草稿' }}
                      </a-tag>
                    </template>
                    <template v-if="column.key === 'action'">
                      <a-button
                        v-if="record.status !== 'published'"
                        type="primary"
                        ghost
                        size="small"
                        @click="handlePublishSkill(record.id)"
                      >
                        发布
                      </a-button>
                      <span v-else class="text-secondary">无需操作</span>
                    </template>
                  </template>
                </a-table>
              </div>
            </a-tab-pane>
          </a-tabs>
        </div>
      </a-modal>

      <a-modal
        :open="state.skillModalVisible"
        title="生成业务技能"
        :confirm-loading="state.skillSubmitting"
        @ok="handleGenerateSkill"
        @cancel="state.skillModalVisible = false"
        width="560px"
        class="custom-modal"
      >
        <a-form :model="skillForm" layout="vertical" class="custom-form">
          <a-form-item label="业务场景" required>
            <a-input
              v-model:value="skillForm.business_scenario"
              placeholder="例如：销售漏斗转化分析、门店经营分析"
              size="large"
            />
          </a-form-item>
          <a-form-item label="目标指标">
            <a-textarea
              v-model:value="skillForm.target_metrics"
              :rows="3"
              placeholder="多个指标用逗号分隔，例如：成交额, 转化率, 客单价"
            />
          </a-form-item>
          <a-form-item label="约束条件">
            <a-textarea
              v-model:value="skillForm.constraints"
              :rows="3"
              placeholder="多个约束用分号分隔，例如：仅看华东区域;按月统计;排除退款单"
            />
          </a-form-item>
        </a-form>
      </a-modal>

      <!-- 值映射添加模态框 -->
      <a-modal
        :open="state.mappingModalVisible"
        title="添加值映射"
        :confirm-loading="state.mappingSubmitting"
        @ok="handleAddMapping"
        @cancel="state.mappingModalVisible = false"
        width="500px"
        class="custom-modal"
      >
        <a-form :model="mappingForm" layout="vertical" class="custom-form">
          <a-form-item label="表名" required>
            <a-select v-model:value="mappingForm.table_name" placeholder="请选择表" show-search size="large">
              <a-select-option
                v-for="table in state.schema?.tables || []"
                :key="table.table_name"
                :value="table.table_name"
              >
                {{ table.table_name }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="列名" required>
            <a-select
              v-model:value="mappingForm.column_name"
              placeholder="请选择列"
              show-search
              :disabled="!mappingForm.table_name"
              size="large"
            >
              <a-select-option
                v-for="col in getTableColumns(mappingForm.table_name)"
                :key="col.column_name"
                :value="col.column_name"
              >
                {{ col.column_name }} ({{ col.column_type }})
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="自然语言值" required>
            <a-input
              v-model:value="mappingForm.natural_value"
              placeholder="如：已完成、进行中、男、女"
              size="large"
            />
          </a-form-item>
          <a-form-item label="数据库值" required>
            <a-input
              v-model:value="mappingForm.db_value"
              placeholder="如：completed、in_progress、1、0"
              size="large"
            />
          </a-form-item>
          <a-form-item label="描述">
            <a-input v-model:value="mappingForm.description" placeholder="可选说明" size="large" />
          </a-form-item>
        </a-form>
      </a-modal>

      <!-- 加载状态 -->
      <div v-if="state.loading" class="loading-container">
        <a-spin size="large" />
        <p>正在加载数据源...</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="!state.connections || state.connections.length === 0" class="empty-state">
        <div class="empty-icon-wrapper">
          <DatabaseOutlined class="empty-icon" />
        </div>
        <h3 class="empty-title">暂无数据源</h3>
        <p class="empty-description">创建数据库连接，开始使用 Text2SQL 功能</p>
        <a-button type="primary" size="large" @click="openCreateModal">
          <template #icon>
            <PlusOutlined />
          </template>
          创建连接
        </a-button>
      </div>

      <!-- 连接列表 -->
      <div v-else class="connections-grid">
        <div
          v-for="conn in state.connections"
          :key="conn.id"
          class="connection-card"
          :class="{ inactive: !conn.is_active }"
        >
          <div class="card-status-bar" :class="getDbTypeColor(conn.db_type)"></div>
          <div class="card-header">
            <div class="card-title">
              <div class="db-icon-wrapper" :class="getDbTypeColor(conn.db_type)">
                <DatabaseOutlined />
              </div>
              <span class="name" :title="conn.name">{{ conn.name }}</span>
            </div>
            <a-tag :color="getDbTypeColor(conn.db_type)" class="db-type-tag">{{ conn.db_type.toUpperCase() }}</a-tag>
          </div>

          <div class="card-body">
            <div class="info-row">
              <span class="label">主机</span>
              <span class="value" :title="conn.host || 'localhost'"
                >{{ conn.host || 'localhost' }}:{{ conn.port || getDefaultPort(conn.db_type) }}</span
              >
            </div>
            <div class="info-row">
              <span class="label">数据库</span>
              <span class="value" :title="conn.database">{{ conn.database }}</span>
            </div>
            <div class="info-row">
              <span class="label">用户</span>
              <span class="value" :title="conn.username || '-'">{{ conn.username || '-' }}</span>
            </div>
          </div>

          <div class="card-footer">
            <a-tooltip title="测试连接">
              <a-button type="text" size="small" class="action-btn" @click="testConnection(conn)">
                <template #icon><ApiOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-tooltip title="查看 Schema">
              <a-button type="text" size="small" class="action-btn" @click="viewSchema(conn)">
                <template #icon><TableOutlined /></template>
              </a-button>
            </a-tooltip>
            <div class="divider"></div>
            <a-dropdown :trigger="['click']">
              <a-button type="text" size="small" class="action-btn">
                <template #icon><MoreOutlined /></template>
              </a-button>
              <template #overlay>
                <a-menu class="custom-dropdown-menu">
                  <a-menu-item @click="editConnection(conn)"> <EditOutlined /> 编辑连接 </a-menu-item>
                  <a-menu-item @click="discoverSchema(conn)">
                    <SyncOutlined /> 同步 Schema
                  </a-menu-item>
                  <a-menu-divider />
                  <a-menu-item @click="deleteConnection(conn)" danger>
                    <DeleteOutlined /> 删除连接
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  PlusOutlined,
  PlayCircleOutlined,
  TableOutlined,
  MoreOutlined,
  EditOutlined,
  SyncOutlined,
  DeleteOutlined,
  DatabaseOutlined,
  ApiOutlined,
  CloseOutlined,
  InfoCircleOutlined,
  BulbOutlined,
  ReloadOutlined
} from '@ant-design/icons-vue'
import { Database } from 'lucide-vue-next'
import HeaderComponent from '@/components/HeaderComponent.vue'
import SchemaFlow from '@/components/schema/SchemaFlow.vue'
import {
  getConnections,
  createConnection,
  updateConnection,
  deleteConnection as apiDeleteConnection,
  testConnection as apiTestConnection,
  getSchema,
  discoverSchema as apiDiscoverSchema,
  getValueMappings,
  createValueMapping,
  deleteValueMapping,
  generateReporterSkill,
  listReporterSkills,
  publishReporterSkill
} from '@/apis/text2sql_api'

const state = reactive({
  loading: false,
  connections: [],
  modalVisible: false,
  submitting: false,
  editingId: null,
  schemaModalVisible: false,
  schemaLoading: false,
  schema: null,
  currentConnection: null,
  activeTab: 'diagram',
  valueMappings: [],
  mappingModalVisible: false,
  mappingSubmitting: false,
  skills: [],
  skillsLoading: false,
  skillModalVisible: false,
  skillSubmitting: false
})

const formData = reactive({
  name: '',
  db_type: 'mysql',
  host: '',
  port: null,
  database: '',
  username: '',
  password: ''
})

const mappingForm = reactive({
  table_name: '',
  column_name: '',
  natural_value: '',
  db_value: '',
  description: ''
})

const skillForm = reactive({
  business_scenario: '',
  target_metrics: '',
  constraints: ''
})

const columnTableColumns = [
  { title: '列名', dataIndex: 'column_name', key: 'column_name', width: '20%' },
  { title: '类型', dataIndex: 'column_type', key: 'column_type', width: '15%' },
  {
    title: '主键',
    dataIndex: 'is_primary_key',
    key: 'is_primary_key',
    width: '10%',
    customRender: ({ text }) => (text ? '是' : '-')
  },
  {
    title: '可空',
    dataIndex: 'is_nullable',
    key: 'is_nullable',
    width: '10%',
    customRender: ({ text }) => (text ? '是' : '否')
  },
  { title: '注释', dataIndex: 'column_comment', key: 'column_comment', ellipsis: true }
]

const relationshipColumns = [
  { title: '源表', dataIndex: 'source_table', key: 'source_table' },
  { title: '源列', dataIndex: 'source_column', key: 'source_column' },
  { title: '目标表', dataIndex: 'target_table', key: 'target_table' },
  { title: '目标列', dataIndex: 'target_column', key: 'target_column' },
  { title: '关系类型', dataIndex: 'relationship_type', key: 'relationship_type' }
]

const mappingColumns = [
  { title: '表名', dataIndex: 'table_name', key: 'table_name' },
  { title: '列名', dataIndex: 'column_name', key: 'column_name' },
  { title: '自然语言值', dataIndex: 'natural_value', key: 'natural_value' },
  { title: '数据库值', dataIndex: 'db_value', key: 'db_value' },
  { title: '描述', dataIndex: 'description', key: 'description' },
  { title: '操作', key: 'action', width: 80, align: 'center' }
]

onMounted(() => {
  loadConnections()
})

async function loadConnections() {
  state.loading = true
  try {
    const res = await getConnections()
    state.connections = res.data || []
  } catch (error) {
    message.error('加载数据源失败: ' + error.message)
  } finally {
    state.loading = false
  }
}

function openCreateModal() {
  state.editingId = null
  resetForm()
  state.modalVisible = true
}

function editConnection(conn) {
  state.editingId = conn.id
  formData.name = conn.name
  formData.db_type = conn.db_type
  formData.host = conn.host
  formData.port = conn.port
  formData.database = conn.database
  formData.username = conn.username
  formData.password = ''
  state.modalVisible = true
}

function resetForm() {
  formData.name = ''
  formData.db_type = 'mysql'
  formData.host = ''
  formData.port = null
  formData.database = ''
  formData.username = ''
  formData.password = ''
}

function closeModal() {
  state.modalVisible = false
  resetForm()
}

async function handleSubmit() {
  if (!formData.name || !formData.database) {
    message.warning('请填写必填字段')
    return
  }

  state.submitting = true
  try {
    const data = { ...formData }
    if (!data.password) {
      delete data.password
    }

    if (state.editingId) {
      await updateConnection(state.editingId, data)
      message.success('更新成功')
    } else {
      await createConnection(data)
      message.success('创建成功')
    }
    closeModal()
    loadConnections()
  } catch (error) {
    message.error('操作失败: ' + error.message)
  } finally {
    state.submitting = false
  }
}

async function testConnection(conn) {
  try {
    const res = await apiTestConnection(conn.id)
    if (res.success) {
      message.success('连接成功')
    } else {
      message.error('连接失败: ' + res.message)
    }
  } catch (error) {
    message.error('测试失败: ' + error.message)
  }
}

async function viewSchema(conn) {
  state.currentConnection = conn
  state.schemaModalVisible = true
  state.schemaLoading = true
  state.activeTab = 'diagram'
  try {
    const [schemaRes, mappingsRes, skillsRes] = await Promise.all([
      getSchema(conn.id),
      getValueMappings(conn.id),
      listReporterSkills(conn.id)
    ])
    state.schema = schemaRes.data
    state.valueMappings = mappingsRes.data || []
    state.skills = skillsRes.data || []
  } catch (error) {
    message.error('加载数据失败: ' + error.message)
  } finally {
    state.schemaLoading = false
  }
}

function closeSchemaModal() {
  state.schemaModalVisible = false
  state.schema = null
  state.valueMappings = []
  state.skills = []
  state.currentConnection = null
}

async function refreshSchema() {
  if (!state.currentConnection) return
  try {
    const [schemaRes, mappingsRes, skillsRes] = await Promise.all([
      getSchema(state.currentConnection.id),
      getValueMappings(state.currentConnection.id),
      listReporterSkills(state.currentConnection.id)
    ])
    state.schema = schemaRes.data
    state.valueMappings = mappingsRes.data || []
    state.skills = skillsRes.data || []
  } catch (error) {
    message.error('刷新失败: ' + error.message)
  }
}

function openSkillModal() {
  skillForm.business_scenario = ''
  skillForm.target_metrics = ''
  skillForm.constraints = ''
  state.skillModalVisible = true
}

async function handleGenerateSkill() {
  if (!state.currentConnection?.id) return
  if (!skillForm.business_scenario.trim()) {
    message.warning('请填写业务场景')
    return
  }
  state.skillSubmitting = true
  try {
    const targetMetrics = skillForm.target_metrics
      .split(/[，,\n]/)
      .map((v) => v.trim())
      .filter(Boolean)
    const constraints = skillForm.constraints
      .split(/[；;\n]/)
      .map((v) => v.trim())
      .filter(Boolean)
    await generateReporterSkill(state.currentConnection.id, {
      business_scenario: skillForm.business_scenario.trim(),
      target_metrics: targetMetrics,
      constraints
    })
    message.success('技能草稿生成成功')
    state.skillModalVisible = false
    await refreshSkills()
  } catch (error) {
    message.error('生成失败: ' + error.message)
  } finally {
    state.skillSubmitting = false
  }
}

async function refreshSkills() {
  if (!state.currentConnection?.id) return
  state.skillsLoading = true
  try {
    const res = await listReporterSkills(state.currentConnection.id)
    state.skills = res.data || []
  } catch (error) {
    message.error('加载技能失败: ' + error.message)
  } finally {
    state.skillsLoading = false
  }
}

async function handlePublishSkill(skillId) {
  if (!state.currentConnection?.id) return
  try {
    await publishReporterSkill(state.currentConnection.id, skillId)
    message.success('发布成功')
    await refreshSkills()
  } catch (error) {
    message.error('发布失败: ' + error.message)
  }
}

function getTableColumns(tableName) {
  if (!tableName || !state.schema?.tables) return []
  const table = state.schema.tables.find((t) => t.table_name === tableName)
  return table?.columns || []
}

function openMappingModal() {
  mappingForm.table_name = ''
  mappingForm.column_name = ''
  mappingForm.natural_value = ''
  mappingForm.db_value = ''
  mappingForm.description = ''
  state.mappingModalVisible = true
}

async function handleAddMapping() {
  if (
    !mappingForm.table_name ||
    !mappingForm.column_name ||
    !mappingForm.natural_value ||
    !mappingForm.db_value
  ) {
    message.warning('请填写必填字段')
    return
  }

  state.mappingSubmitting = true
  try {
    await createValueMapping(state.currentConnection.id, {
      table_name: mappingForm.table_name,
      column_name: mappingForm.column_name,
      natural_value: mappingForm.natural_value,
      db_value: mappingForm.db_value,
      description: mappingForm.description
    })
    message.success('添加成功')
    state.mappingModalVisible = false
    // 刷新值映射列表
    const res = await getValueMappings(state.currentConnection.id)
    state.valueMappings = res.data || []
  } catch (error) {
    message.error('添加失败: ' + error.message)
  } finally {
    state.mappingSubmitting = false
  }
}

async function handleDeleteMapping(mappingId) {
  try {
    await deleteValueMapping(mappingId)
    message.success('删除成功')
    state.valueMappings = state.valueMappings.filter((m) => m.id !== mappingId)
  } catch (error) {
    message.error('删除失败: ' + error.message)
  }
}

async function discoverSchema(conn) {
  Modal.confirm({
    title: '同步 Schema',
    content: '这将从数据库重新获取表结构，现有的 Schema 数据会被覆盖。确定继续吗？',
    okText: '确定',
    cancelText: '取消',
    async onOk() {
      try {
        await apiDiscoverSchema(conn.id)
        message.success('Schema 同步成功')
      } catch (error) {
        message.error('同步失败: ' + error.message)
      }
    }
  })
}

function deleteConnection(conn) {
  Modal.confirm({
    title: '删除连接',
    content: `确定要删除连接 "${conn.name}" 吗？相关的 Schema 和值映射数据也会被删除。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await apiDeleteConnection(conn.id)
        message.success('删除成功')
        loadConnections()
      } catch (error) {
        message.error('删除失败: ' + error.message)
      }
    }
  })
}

function getDbTypeColor(dbType) {
  const colors = {
    mysql: 'blue',
    postgresql: 'green',
    sqlite: 'orange'
  }
  return colors[dbType] || 'default'
}

function getDefaultPort(dbType) {
  const ports = {
    mysql: 3306,
    postgresql: 5432
  }
  return ports[dbType] || ''
}
</script>

<style scoped lang="less">
.datasource-container {
  padding: 24px;
  height: 100%;
  overflow: hidden;
  
  .glass-panel {
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 24px;
  }
}

.loading-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: var(--gray-500);
  gap: 16px;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;
  
  .empty-icon-wrapper {
    width: 80px;
    height: 80px;
    background: var(--gray-50);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 24px;
    
    .empty-icon {
      font-size: 40px;
      color: var(--gray-400);
    }
  }
  
  .empty-title {
    font-size: 20px;
    font-weight: 600;
    color: var(--gray-900);
    margin: 0 0 12px 0;
  }
  
  .empty-description {
    font-size: 14px;
    color: var(--gray-500);
    margin: 0 0 32px 0;
    max-width: 400px;
  }
}

.connections-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
  padding: 4px;
  overflow-y: auto;
  padding-bottom: 24px;
}

.connection-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 16px;
  overflow: hidden;
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  position: relative;
  
  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 24px -8px var(--shadow-color-lg);
    border-color: var(--primary-200);
    
    .card-footer {
      background: var(--gray-50);
      opacity: 1;
    }
  }
  
  &.inactive {
    opacity: 0.7;
    filter: grayscale(0.8);
  }
  
  .card-status-bar {
    height: 4px;
    width: 100%;
    
    &.blue { background: #1677ff; }
    &.green { background: #52c41a; }
    &.orange { background: #fa8c16; }
    &.default { background: var(--gray-400); }
  }
  
  .card-header {
    padding: 20px 20px 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    
    .card-title {
      display: flex;
      align-items: center;
      gap: 12px;
      
      .db-icon-wrapper {
        width: 36px;
        height: 36px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        
        &.blue { background: #e6f4ff; color: #1677ff; }
        &.green { background: #f6ffed; color: #52c41a; }
        &.orange { background: #fff7e6; color: #fa8c16; }
        &.default { background: var(--gray-100); color: var(--gray-600); }
      }
      
      .name {
        font-size: 16px;
        font-weight: 600;
        color: var(--gray-900);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 140px;
      }
    }
    
    .db-type-tag {
      margin: 0;
      border: none;
      font-weight: 600;
      font-size: 12px;
    }
  }
  
  .card-body {
    padding: 0 20px 20px;
    flex: 1;
    
    .info-row {
      display: flex;
      margin-bottom: 8px;
      font-size: 13px;
      line-height: 1.6;
      
      &:last-child {
        margin-bottom: 0;
      }
      
      .label {
        color: var(--gray-500);
        width: 60px;
        flex-shrink: 0;
      }
      
      .value {
        color: var(--gray-700);
        font-family: var(--font-family-mono);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
    }
  }
  
  .card-footer {
    padding: 12px 20px;
    border-top: 1px solid var(--gray-100);
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: var(--gray-0);
    transition: background 0.3s;
    
    .action-btn {
      color: var(--gray-600);
      
      &:hover {
        color: var(--primary-600);
        background: var(--primary-50);
      }
    }
    
    .divider {
      width: 1px;
      height: 16px;
      background: var(--gray-200);
    }
  }
}

// Modal & Schema Styles
.schema-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--gray-200);
  background: var(--gray-0);
  
  .header-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 18px;
    font-weight: 600;
    color: var(--gray-900);
    
    .icon {
      color: var(--primary-500);
    }
  }
  
  .close-btn {
    color: var(--gray-500);
    &:hover {
      color: var(--gray-800);
      background: var(--gray-100);
    }
  }
}

.schema-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.schema-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  
  :deep(.ant-tabs-nav) {
    margin: 0;
    padding: 12px 24px 0;
    background: var(--gray-50);
    border-bottom: 1px solid var(--gray-200);
  }
  
  :deep(.ant-tabs-content) {
    flex: 1;
    overflow: hidden;
    height: 100%;
  }
}

.tab-content {
  height: 100%;
  overflow-y: auto;
  padding: 24px;
  background: var(--gray-50);
}

.diagram-container {
  height: 100%;
  background: var(--gray-50);
}

.custom-collapse {
  background: transparent;
  
  :deep(.ant-collapse-item) {
    background: var(--gray-0);
    border: 1px solid var(--gray-200);
    border-radius: 8px !important;
    margin-bottom: 12px;
    overflow: hidden;
  }
  
  :deep(.ant-collapse-header) {
    padding: 12px 16px !important;
    background: var(--gray-0);
    font-weight: 600;
  }
  
  .table-comment-preview {
    color: var(--gray-500);
    font-size: 13px;
    font-weight: 400;
  }
}

.table-detail-wrapper {
  .table-comment-full {
    margin-bottom: 16px;
    padding: 10px 16px;
    background: var(--primary-50);
    border: 1px solid var(--primary-100);
    border-radius: 6px;
    color: var(--primary-700);
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
}

.mappings-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  background: var(--gray-0);
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--gray-200);
  
  .info-box {
    display: flex;
    gap: 12px;
    
    .icon {
      font-size: 20px;
      color: var(--primary-500);
      margin-top: 2px;
    }
    
    .mappings-desc {
      margin: 0;
      color: var(--gray-600);
      font-size: 14px;
      line-height: 1.5;
      max-width: 600px;
    }
  }
  
  .action-group {
    display: flex;
    gap: 12px;
  }
}

:deep(.custom-table) {
  .ant-table-thead > tr > th {
    background: var(--gray-100);
    font-weight: 600;
  }
}

.text-secondary {
  color: var(--gray-400);
  font-size: 12px;
}
</style>
