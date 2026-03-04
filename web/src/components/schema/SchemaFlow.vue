<template>
  <div class="schema-editor">
    <!-- 工具栏 -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-title">Schema 编辑器</span>
        <span v-if="schema?.tables?.length" class="table-count">
          {{ nodesOnCanvas.length }} / {{ schema.tables.length }} 表
        </span>
      </div>
      <div class="toolbar-right">
        <a-button size="small" @click="handleAutoLayout">
          <template #icon><LayoutOutlined /></template>
          自动布局
        </a-button>
        <a-button size="small" :loading="saving" @click="handleSavePositions">
          <template #icon><SaveOutlined /></template>
          保存布局
        </a-button>
      </div>
    </div>

    <!-- 主体 -->
    <div class="editor-body">
      <!-- 左侧表列表 -->
      <div class="table-panel">
        <div class="panel-header">可用表</div>
        <div class="panel-content">
          <div
            v-for="table in availableTables"
            :key="table.id"
            class="table-item"
            @click="addTableToCanvas(table)"
          >
            <TableOutlined class="table-icon" />
            <span class="table-name">{{ table.table_name }}</span>
            <span class="column-count">{{ table.columns?.length || 0 }} 列</span>
          </div>
          <div v-if="!availableTables.length" class="empty-hint">所有表已添加到画布</div>
        </div>
      </div>

      <!-- 画布 -->
      <div class="canvas-container">
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          :node-types="nodeTypes"
          :edge-types="edgeTypes"
          :default-viewport="{ zoom: 0.8 }"
          fit-view-on-init
          @connect="onConnect"
          @node-drag-stop="onNodeDragStop"
        >
          <Background />
          <Controls />
        </VueFlow>
      </div>
    </div>

    <!-- 关系编辑弹窗 -->
    <RelationshipModal
      v-model:visible="relModalVisible"
      :mode="relModalMode"
      :source-table="pendingRelation.sourceTable"
      :source-column="pendingRelation.sourceColumn"
      :target-table="pendingRelation.targetTable"
      :target-column="pendingRelation.targetColumn"
      :relationship-id="pendingRelation.id"
      :relationship-type="pendingRelation.type"
      :loading="relLoading"
      :delete-loading="relDeleteLoading"
      @confirm="handleRelationConfirm"
      @delete="handleRelationDelete"
    />

    <!-- 表编辑弹窗 -->
    <TableEditModal
      v-model:visible="tableEditModalVisible"
      :table="editingTable"
      :loading="tableLoading"
      @save="handleTableSave"
      @update-column="handleColumnUpdate"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, markRaw } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { message } from 'ant-design-vue'
import { TableOutlined, LayoutOutlined, SaveOutlined } from '@ant-design/icons-vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'

import TableNode from './TableNode.vue'
import RelationshipEdge from './RelationshipEdge.vue'
import RelationshipModal from './RelationshipModal.vue'
import TableEditModal from './TableEditModal.vue'

import {
  updateTablePosition,
  updateTable,
  updateColumn,
  deleteSchemaTable,
  createRelationship,
  updateRelationship,
  deleteRelationship
} from '@/apis/text2sql_api'

const props = defineProps({
  connectionId: { type: Number, required: true },
  schema: { type: Object, default: () => ({ tables: [], relationships: [] }) }
})

const emit = defineEmits(['refresh'])

const nodeTypes = { tableNode: markRaw(TableNode) }
const edgeTypes = { relationshipEdge: markRaw(RelationshipEdge) }

const nodes = ref([])
const edges = ref([])
const saving = ref(false)

// 关系弹窗状态
const relModalVisible = ref(false)
const relModalMode = ref('create')
const relLoading = ref(false)
const relDeleteLoading = ref(false)
const pendingRelation = reactive({
  id: null,
  sourceTable: '',
  sourceColumn: '',
  targetTable: '',
  targetColumn: '',
  type: 'many_to_one'
})

// 表编辑弹窗状态
const tableEditModalVisible = ref(false)
const editingTable = ref(null)
const tableLoading = ref(false)

// 画布上的节点 ID 集合
const nodesOnCanvas = computed(() => nodes.value.map((n) => n.data.id))

// 可添加到画布的表
const availableTables = computed(() => {
  if (!props.schema?.tables) return []
  return props.schema.tables.filter((t) => !nodesOnCanvas.value.includes(t.id))
})

// 构建节点
function buildNode(table) {
  const hasPosition = table.position_x !== 0 || table.position_y !== 0
  return {
    id: `table-${table.id}`,
    type: 'tableNode',
    position: {
      x: hasPosition ? table.position_x : 50,
      y: hasPosition ? table.position_y : 50
    },
    data: {
      id: table.id,
      label: table.table_name,
      description: table.table_comment,
      columns: table.columns || [],
      onEdit: openTableEditModal,
      onDelete: handleDeleteTable
    },
    draggable: true
  }
}

// 构建边
function buildEdge(rel, tables) {
  const sourceTable = tables.find((t) => t.table_name === rel.source_table)
  const targetTable = tables.find((t) => t.table_name === rel.target_table)
  if (!sourceTable || !targetTable) return null

  const sourceColumn = sourceTable.columns?.find((c) => c.column_name === rel.source_column)
  const targetColumn = targetTable.columns?.find((c) => c.column_name === rel.target_column)

  return {
    id: `edge-${rel.id}`,
    source: `table-${sourceTable.id}`,
    target: `table-${targetTable.id}`,
    sourceHandle: sourceColumn ? `${sourceColumn.id}_source` : undefined,
    targetHandle: targetColumn ? `${targetColumn.id}_target` : undefined,
    type: 'relationshipEdge',
    data: {
      id: rel.id,
      relationship_type: rel.relationship_type,
      source_table: rel.source_table,
      source_column: rel.source_column,
      target_table: rel.target_table,
      target_column: rel.target_column,
      onEdit: openRelEditModal,
      onDelete: handleDeleteRelation
    }
  }
}

// 监听 schema 变化
watch(
  () => props.schema,
  (newSchema) => {
    if (newSchema?.tables?.length) {
      nodes.value = newSchema.tables.map((t) => buildNode(t))
      edges.value = (newSchema.relationships || [])
        .map((r) => buildEdge(r, newSchema.tables))
        .filter(Boolean)
    } else {
      nodes.value = []
      edges.value = []
    }
  },
  { immediate: true, deep: true }
)

// 添加表到画布
function addTableToCanvas(table) {
  const existingNodes = nodes.value.length
  const col = existingNodes % 3
  const row = Math.floor(existingNodes / 3)
  const node = buildNode(table)
  node.position = { x: col * 360 + 50, y: row * 310 + 50 }
  nodes.value.push(node)
}

// 连线创建
function onConnect(params) {
  // 解析源和目标
  const sourceNodeId = params.source
  const targetNodeId = params.target
  const sourceHandleId = params.sourceHandle
  const targetHandleId = params.targetHandle

  const sourceNode = nodes.value.find((n) => n.id === sourceNodeId)
  const targetNode = nodes.value.find((n) => n.id === targetNodeId)

  if (!sourceNode || !targetNode) return

  // 从 handle ID 解析列 ID
  const sourceColId = sourceHandleId?.replace('_source', '')
  const targetColId = targetHandleId?.replace('_target', '')

  const sourceCol = sourceNode.data.columns?.find((c) => String(c.id) === sourceColId)
  const targetCol = targetNode.data.columns?.find((c) => String(c.id) === targetColId)

  // 打开关系创建弹窗
  pendingRelation.id = null
  pendingRelation.sourceTable = sourceNode.data.label
  pendingRelation.sourceColumn = sourceCol?.column_name || ''
  pendingRelation.targetTable = targetNode.data.label
  pendingRelation.targetColumn = targetCol?.column_name || ''
  pendingRelation.type = 'many_to_one'
  relModalMode.value = 'create'
  relModalVisible.value = true
}

// 节点拖拽结束
async function onNodeDragStop(event) {
  const node = event.node
  if (!node) return
  const tableId = node.data?.id
  if (!tableId) return

  try {
    await updateTablePosition(tableId, Math.round(node.position.x), Math.round(node.position.y))
  } catch (e) {
    console.error('Save position failed:', e)
  }
}

// 自动布局
function handleAutoLayout() {
  const COLS = 3
  const NODE_WIDTH = 280
  const NODE_HEIGHT = 250
  const GAP_X = 80
  const GAP_Y = 60

  nodes.value = nodes.value.map((node, index) => ({
    ...node,
    position: {
      x: (index % COLS) * (NODE_WIDTH + GAP_X) + 50,
      y: Math.floor(index / COLS) * (NODE_HEIGHT + GAP_Y) + 50
    }
  }))
}

// 保存所有位置
async function handleSavePositions() {
  saving.value = true
  try {
    const promises = nodes.value.map((node) =>
      updateTablePosition(node.data.id, Math.round(node.position.x), Math.round(node.position.y))
    )
    await Promise.all(promises)
    message.success('布局已保存')
  } catch (e) {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

// 打开关系编辑弹窗
function openRelEditModal(relData) {
  pendingRelation.id = relData.id
  pendingRelation.sourceTable = relData.source_table
  pendingRelation.sourceColumn = relData.source_column
  pendingRelation.targetTable = relData.target_table
  pendingRelation.targetColumn = relData.target_column
  pendingRelation.type = relData.relationship_type
  relModalMode.value = 'edit'
  relModalVisible.value = true
}

// 关系确认
async function handleRelationConfirm(relationshipType) {
  relLoading.value = true
  try {
    if (relModalMode.value === 'create') {
      await createRelationship(props.connectionId, {
        source_table: pendingRelation.sourceTable,
        source_column: pendingRelation.sourceColumn,
        target_table: pendingRelation.targetTable,
        target_column: pendingRelation.targetColumn,
        relationship_type: relationshipType
      })
      message.success('关系创建成功')
    } else {
      await updateRelationship(pendingRelation.id, { relationship_type: relationshipType })
      message.success('关系更新成功')
    }
    relModalVisible.value = false
    emit('refresh')
  } catch (e) {
    message.error('操作失败: ' + e.message)
  } finally {
    relLoading.value = false
  }
}

// 删除关系
async function handleDeleteRelation(relationshipId) {
  relDeleteLoading.value = true
  try {
    await deleteRelationship(relationshipId)
    message.success('关系已删除')
    relModalVisible.value = false
    emit('refresh')
  } catch (e) {
    message.error('删除失败: ' + e.message)
  } finally {
    relDeleteLoading.value = false
  }
}

// 打开表编辑弹窗
function openTableEditModal(tableData) {
  const fullTable = props.schema?.tables?.find((t) => t.id === tableData.id)
  editingTable.value = fullTable || tableData
  tableEditModalVisible.value = true
}

// 保存表信息
async function handleTableSave(tableComment) {
  tableLoading.value = true
  try {
    await updateTable(editingTable.value.id, { table_comment: tableComment })
    message.success('表信息已更新')
    tableEditModalVisible.value = false
    emit('refresh')
  } catch (e) {
    message.error('更新失败: ' + e.message)
  } finally {
    tableLoading.value = false
  }
}

// 更新列注释
async function handleColumnUpdate(columnId, comment) {
  try {
    await updateColumn(columnId, { column_comment: comment })
  } catch (e) {
    message.error('列更新失败')
  }
}

// 删除表
async function handleDeleteTable(tableId) {
  try {
    await deleteSchemaTable(tableId)
    message.success('表已删除')
    emit('refresh')
  } catch (e) {
    message.error('删除失败: ' + e.message)
  }
}
</script>

<style scoped lang="less">
.schema-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 500px;
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--gray-50, #f9fafb);
  border-bottom: 1px solid var(--gray-200, #e5e7eb);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;

  .toolbar-title {
    font-weight: 600;
    color: var(--gray-800, #1f2937);
  }

  .table-count {
    font-size: 12px;
    color: var(--gray-500, #6b7280);
  }
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

.editor-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.table-panel {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--gray-200, #e5e7eb);
  background: var(--bg-card, #fff);
  display: flex;
  flex-direction: column;
}

.panel-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 13px;
  color: var(--gray-700, #374151);
  border-bottom: 1px solid var(--gray-200, #e5e7eb);
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.table-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover {
    background: var(--gray-100, #f3f4f6);
  }

  .table-icon {
    color: var(--primary-color, #1890ff);
    font-size: 14px;
  }

  .table-name {
    flex: 1;
    font-size: 13px;
    color: var(--gray-700, #374151);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .column-count {
    font-size: 11px;
    color: var(--gray-400, #9ca3af);
  }
}

.empty-hint {
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--gray-400, #9ca3af);
}

.canvas-container {
  flex: 1;
  overflow: hidden;
}
</style>
