<template>
  <div
    class="table-node"
    :class="{ selected: selected, hovered: isHovered }"
    @mouseenter="isHovered = true"
    @mouseleave="isHovered = false"
  >
    <div class="node-header">
      <div class="header-left">
        <TableOutlined class="node-icon" />
        <span class="node-title" :title="data.label">{{ data.label }}</span>
      </div>
      <div v-if="isHovered || selected" class="header-actions">
        <button class="action-btn" @click.stop="handleEdit" title="编辑表">
          <EditOutlined />
        </button>
        <button class="action-btn danger" @click.stop="handleDelete" title="删除表">
          <CloseOutlined />
        </button>
      </div>
    </div>
    <div class="node-content">
      <div
        v-for="column in data.columns"
        :key="column.id"
        class="column-row"
        :class="{
          'primary-key': column.is_primary_key,
          'foreign-key': column.is_foreign_key
        }"
      >
        <div class="column-info">
          <KeyOutlined v-if="column.is_primary_key" class="pk-icon" />
          <LinkOutlined v-if="column.is_foreign_key" class="fk-icon" />
          <span class="column-name">{{ column.column_name }}</span>
        </div>
        <span class="column-type">{{ column.column_type || column.data_type }}</span>
        <Handle
          :id="`${column.id}_source`"
          type="source"
          :position="Position.Right"
          class="column-handle source"
        />
        <Handle
          :id="`${column.id}_target`"
          type="target"
          :position="Position.Left"
          class="column-handle target"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  TableOutlined,
  KeyOutlined,
  LinkOutlined,
  EditOutlined,
  CloseOutlined
} from '@ant-design/icons-vue'

const props = defineProps({
  data: {
    type: Object,
    required: true
  },
  selected: {
    type: Boolean,
    default: false
  }
})

const isHovered = ref(false)

function handleEdit() {
  if (props.data?.onEdit) {
    props.data.onEdit(props.data)
  }
}

function handleDelete() {
  if (props.data?.onDelete) {
    props.data.onDelete(props.data.id)
  }
}
</script>

<style scoped lang="less">
.table-node {
  background: var(--bg-card, #fff);
  border: 1px solid var(--gray-200, #e5e7eb);
  border-radius: 8px;
  min-width: 220px;
  max-width: 280px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  font-size: 12px;
  transition:
    border-color 0.2s,
    box-shadow 0.2s;

  &.selected {
    border-color: var(--primary-color, #1890ff);
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
  }

  &.hovered {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  }
}

.node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--gray-50, #f9fafb);
  border-bottom: 1px solid var(--gray-200, #e5e7eb);
  border-radius: 8px 8px 0 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;

  .node-icon {
    color: var(--primary-color, #1890ff);
    font-size: 14px;
    flex-shrink: 0;
  }

  .node-title {
    font-weight: 600;
    color: var(--gray-800, #1f2937);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.header-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--gray-500, #6b7280);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;

  &:hover {
    background: var(--gray-200, #e5e7eb);
    color: var(--gray-700, #374151);
  }

  &.danger:hover {
    background: #fff1f0;
    color: #f5222d;
  }
}

.node-content {
  padding: 4px 0;
  max-height: 300px;
  overflow-y: auto;
}

.column-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  position: relative;
  transition: background 0.2s;

  &:hover {
    background: var(--gray-50, #f9fafb);
  }

  &.primary-key {
    .column-name {
      font-weight: 600;
    }
  }

  &.foreign-key {
    .column-name {
      color: var(--primary-color, #1890ff);
    }
  }
}

.column-info {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;

  .pk-icon {
    color: #faad14;
    font-size: 11px;
  }

  .fk-icon {
    color: var(--primary-color, #1890ff);
    font-size: 11px;
  }

  .column-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--gray-700, #374151);
  }
}

.column-type {
  font-size: 11px;
  color: var(--gray-500, #6b7280);
  background: var(--gray-100, #f3f4f6);
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 8px;
  flex-shrink: 0;
}

.column-handle {
  width: 8px;
  height: 8px;
  background: var(--primary-color, #1890ff);
  border: 2px solid #fff;
  opacity: 0;
  transition: opacity 0.2s;

  &.source {
    right: -4px;
  }

  &.target {
    left: -4px;
  }
}

.column-row:hover .column-handle {
  opacity: 1;
}
</style>
