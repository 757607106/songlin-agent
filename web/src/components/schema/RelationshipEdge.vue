<template>
  <BaseEdge :id="id" :path="path" :style="edgeStyle" :marker-end="markerEnd" />
  <EdgeLabelRenderer>
    <div
      :style="{
        transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
        pointerEvents: 'all'
      }"
      class="edge-label-wrapper"
      :class="{ selected: selected, hovered: isHovered }"
      @mouseenter="isHovered = true"
      @mouseleave="isHovered = false"
      @click.stop="handleClick"
    >
      <span class="edge-label" :style="{ borderColor: strokeColor, color: strokeColor }">
        {{ relationshipLabel }}
      </span>
      <button v-if="isHovered || selected" class="delete-btn" @click.stop="handleDelete">
        <CloseOutlined />
      </button>
    </div>
  </EdgeLabelRenderer>
</template>

<script setup>
import { computed, ref } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, MarkerType } from '@vue-flow/core'
import { CloseOutlined } from '@ant-design/icons-vue'

const props = defineProps({
  id: String,
  sourceX: Number,
  sourceY: Number,
  targetX: Number,
  targetY: Number,
  sourcePosition: String,
  targetPosition: String,
  data: Object,
  selected: Boolean
})

const isHovered = ref(false)

// 使用后端格式的关系类型
const RELATIONSHIP_LABELS = {
  one_to_one: '1:1',
  one_to_many: '1:N',
  many_to_one: 'N:1',
  many_to_many: 'N:M'
}

const RELATIONSHIP_COLORS = {
  one_to_one: '#8b5cf6',
  one_to_many: '#0ea5e9',
  many_to_one: '#10b981',
  many_to_many: '#f59e0b'
}

const relationshipType = computed(() => props.data?.relationship_type || 'many_to_one')

const relationshipLabel = computed(() => RELATIONSHIP_LABELS[relationshipType.value] || 'N:1')

const strokeColor = computed(() => RELATIONSHIP_COLORS[relationshipType.value] || '#64748b')

const pathData = computed(() =>
  getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition
  })
)

const path = computed(() => pathData.value[0])
const labelX = computed(() => pathData.value[1])
const labelY = computed(() => pathData.value[2])

const edgeStyle = computed(() => ({
  stroke: strokeColor.value,
  strokeWidth: props.selected ? 3 : 2,
  strokeDasharray: ['many_to_many', 'many_to_one'].includes(relationshipType.value) ? '5,5' : ''
}))

const markerEnd = computed(() => ({
  type: MarkerType.ArrowClosed,
  color: strokeColor.value
}))

function handleClick() {
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
.edge-label-wrapper {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  user-select: none;

  &.selected .edge-label,
  &.hovered .edge-label {
    transform: scale(1.05);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }
}

.edge-label {
  background: #fff;
  border: 2px solid;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  transition:
    transform 0.2s,
    box-shadow 0.2s;
}

.delete-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: #f5222d;
  color: #fff;
  cursor: pointer;
  font-size: 10px;
  transition: transform 0.2s;

  &:hover {
    transform: scale(1.1);
  }
}
</style>
