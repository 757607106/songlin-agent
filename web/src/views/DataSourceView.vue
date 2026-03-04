<template>
  <div class="datasource-container layout-container">
    <HeaderComponent title="数据源管理" :loading="state.loading">
      <template #actions>
        <a-button type="primary" @click="openCreateModal">新建连接</a-button>
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
    >
      <a-form :model="formData" layout="vertical">
        <a-form-item label="连接名称" required>
          <a-input v-model:value="formData.name" placeholder="请输入连接名称" />
        </a-form-item>

        <a-form-item label="数据库类型" required>
          <a-select v-model:value="formData.db_type" placeholder="请选择数据库类型">
            <a-select-option value="mysql">MySQL</a-select-option>
            <a-select-option value="postgresql">PostgreSQL</a-select-option>
            <a-select-option value="sqlite">SQLite</a-select-option>
          </a-select>
        </a-form-item>

        <template v-if="formData.db_type !== 'sqlite'">
          <a-row :gutter="16">
            <a-col :span="16">
              <a-form-item label="主机地址">
                <a-input v-model:value="formData.host" placeholder="localhost" />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="端口">
                <a-input-number
                  v-model:value="formData.port"
                  :placeholder="formData.db_type === 'mysql' ? '3306' : '5432'"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
          </a-row>

          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item label="用户名">
                <a-input v-model:value="formData.username" placeholder="请输入用户名" />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item label="密码">
                <a-input-password v-model:value="formData.password" placeholder="请输入密码" />
              </a-form-item>
            </a-col>
          </a-row>
        </template>

        <a-form-item label="数据库名" required>
          <a-input
            v-model:value="formData.database"
            :placeholder="formData.db_type === 'sqlite' ? '数据库文件路径' : '请输入数据库名'"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Schema 查看模态框 -->
    <a-modal
      :open="state.schemaModalVisible"
      :title="`数据源详情 - ${state.currentConnection?.name || ''}`"
      @cancel="closeSchemaModal"
      width="90vw"
      :style="{ maxWidth: '1400px' }"
      :body-style="{ height: '75vh', padding: '0', overflow: 'hidden' }"
      :footer="null"
    >
      <div v-if="state.schemaLoading" class="schema-loading">
        <a-spin size="large" />
        <p>正在加载...</p>
      </div>
      <div v-else-if="state.schema" class="schema-content">
        <a-tabs v-model:activeKey="state.activeTab" class="schema-tabs">
          <a-tab-pane key="diagram" tab="ER 图">
            <div class="diagram-container">
              <SchemaFlow
                :connection-id="state.currentConnection?.id"
                :schema="state.schema"
                @refresh="refreshSchema"
              />
            </div>
          </a-tab-pane>
          <a-tab-pane key="tables" tab="表结构">
            <div class="tab-content">
              <a-collapse accordion>
                <a-collapse-panel
                  v-for="table in state.schema.tables"
                  :key="table.id"
                  :header="table.table_name"
                >
                  <p v-if="table.table_comment" class="table-comment">
                    {{ table.table_comment }}
                  </p>
                  <a-table
                    :columns="columnTableColumns"
                    :data-source="table.columns"
                    :pagination="false"
                    size="small"
                    rowKey="id"
                  />
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
                size="small"
                rowKey="id"
              />
            </div>
          </a-tab-pane>
          <a-tab-pane key="mappings" tab="值映射">
            <div class="tab-content">
              <div class="mappings-header">
                <p class="mappings-desc">
                  值映射用于将自然语言表达转换为数据库中的实际值，提高 SQL 生成准确性。
                </p>
                <a-button type="primary" size="small" @click="openMappingModal">
                  <template #icon><PlusOutlined /></template>
                  添加映射
                </a-button>
              </div>
              <a-table
                :columns="mappingColumns"
                :data-source="state.valueMappings"
                :pagination="false"
                size="small"
                rowKey="id"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'action'">
                    <a-popconfirm
                      title="确定删除此映射？"
                      @confirm="handleDeleteMapping(record.id)"
                    >
                      <a-button type="link" size="small" danger>删除</a-button>
                    </a-popconfirm>
                  </template>
                </template>
              </a-table>
            </div>
          </a-tab-pane>
          <a-tab-pane key="skills" tab="业务技能">
            <div class="tab-content">
              <div class="mappings-header">
                <p class="mappings-desc">按业务场景和指标生成 Skills，可供报表助手直接调用。</p>
                <div style="display: flex; gap: 8px">
                  <a-button size="small" @click="refreshSkills">刷新</a-button>
                  <a-button type="primary" size="small" @click="openSkillModal">
                    <template #icon><PlusOutlined /></template>
                    生成技能
                  </a-button>
                </div>
              </div>
              <a-table
                :columns="[
                  { title: '技能ID', dataIndex: 'id', key: 'id' },
                  { title: '业务场景', dataIndex: 'business_scenario', key: 'business_scenario' },
                  { title: '状态', dataIndex: 'status', key: 'status' },
                  { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at' },
                  { title: '操作', key: 'action', width: 120 }
                ]"
                :data-source="state.skills"
                :loading="state.skillsLoading"
                :pagination="false"
                size="small"
                rowKey="id"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'status'">
                    <a-tag :color="record.status === 'published' ? 'green' : 'orange'">
                      {{ record.status }}
                    </a-tag>
                  </template>
                  <template v-if="column.key === 'action'">
                    <a-button
                      v-if="record.status !== 'published'"
                      type="link"
                      size="small"
                      @click="handlePublishSkill(record.id)"
                    >
                      发布
                    </a-button>
                    <span v-else style="color: var(--gray-500)">已发布</span>
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
    >
      <a-form :model="skillForm" layout="vertical">
        <a-form-item label="业务场景" required>
          <a-input
            v-model:value="skillForm.business_scenario"
            placeholder="例如：销售漏斗转化分析、门店经营分析"
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
    >
      <a-form :model="mappingForm" layout="vertical">
        <a-form-item label="表名" required>
          <a-select v-model:value="mappingForm.table_name" placeholder="请选择表" show-search>
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
          />
        </a-form-item>
        <a-form-item label="数据库值" required>
          <a-input
            v-model:value="mappingForm.db_value"
            placeholder="如：completed、in_progress、1、0"
          />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="mappingForm.description" placeholder="可选说明" />
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
        <div class="card-header">
          <div class="card-title">
            <Database class="db-icon" :size="18" />
            <span>{{ conn.name }}</span>
          </div>
          <a-tag :color="getDbTypeColor(conn.db_type)">{{ conn.db_type.toUpperCase() }}</a-tag>
        </div>

        <div class="card-body">
          <div class="info-row">
            <span class="label">主机:</span>
            <span class="value"
              >{{ conn.host || 'localhost' }}:{{ conn.port || getDefaultPort(conn.db_type) }}</span
            >
          </div>
          <div class="info-row">
            <span class="label">数据库:</span>
            <span class="value">{{ conn.database }}</span>
          </div>
          <div class="info-row">
            <span class="label">用户:</span>
            <span class="value">{{ conn.username || '-' }}</span>
          </div>
        </div>

        <div class="card-footer">
          <a-button size="small" @click="testConnection(conn)">
            <template #icon>
              <PlayCircleOutlined />
            </template>
            测试
          </a-button>
          <a-button size="small" @click="viewSchema(conn)">
            <template #icon>
              <TableOutlined />
            </template>
            Schema
          </a-button>
          <a-dropdown>
            <a-button size="small">
              <template #icon>
                <MoreOutlined />
              </template>
            </a-button>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="editConnection(conn)"> <EditOutlined /> 编辑 </a-menu-item>
                <a-menu-item @click="discoverSchema(conn)">
                  <SyncOutlined /> 同步 Schema
                </a-menu-item>
                <a-menu-divider />
                <a-menu-item @click="deleteConnection(conn)" danger>
                  <DeleteOutlined /> 删除
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
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
  DeleteOutlined
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
  { title: '列名', dataIndex: 'column_name', key: 'column_name' },
  { title: '类型', dataIndex: 'column_type', key: 'column_type' },
  {
    title: '主键',
    dataIndex: 'is_primary_key',
    key: 'is_primary_key',
    customRender: ({ text }) => (text ? 'Y' : '')
  },
  {
    title: '可空',
    dataIndex: 'is_nullable',
    key: 'is_nullable',
    customRender: ({ text }) => (text ? 'Y' : 'N')
  },
  { title: '注释', dataIndex: 'column_comment', key: 'column_comment' }
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
  { title: '操作', key: 'action', width: 80 }
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
  min-height: 100vh;
  background: var(--bg-container);
}

.loading-container,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;

  .empty-title {
    font-size: 18px;
    font-weight: 500;
    color: var(--gray-800);
    margin-bottom: 8px;
  }

  .empty-description {
    color: var(--gray-500);
    margin-bottom: 24px;
  }
}

.connections-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  padding: 24px;
}

.connection-card {
  background: var(--bg-card);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 16px;
  transition: all 0.2s;

  &:hover {
    border-color: var(--primary-color);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  }

  &.inactive {
    opacity: 0.6;
  }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;

  .card-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 500;
    color: var(--gray-900);

    .db-icon {
      color: var(--primary-color);
    }
  }
}

.card-body {
  margin-bottom: 16px;

  .info-row {
    display: flex;
    margin-bottom: 4px;
    font-size: 13px;

    .label {
      color: var(--gray-500);
      width: 60px;
      flex-shrink: 0;
    }

    .value {
      color: var(--gray-700);
      word-break: break-all;
    }
  }
}

.card-footer {
  display: flex;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-150);
}

.schema-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 40px;
}

.schema-content {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.schema-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;

  :deep(.ant-tabs-content) {
    flex: 1;
    overflow: hidden;
  }

  :deep(.ant-tabs-tabpane) {
    height: 100%;
  }
}

.diagram-container {
  height: 100%;
}

.tab-content {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}

.table-comment {
  color: var(--gray-600);
  font-size: 13px;
  margin-bottom: 12px;
}

.mappings-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  .mappings-desc {
    color: var(--gray-600);
    font-size: 13px;
    margin: 0;
  }
}
</style>
