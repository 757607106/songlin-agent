<template>
  <a-modal
    :open="visible"
    :title="mode === 'create' ? '创建关系' : '编辑关系'"
    :confirm-loading="loading"
    @ok="handleSubmit"
    @cancel="handleCancel"
    width="480px"
    destroyOnClose
  >
    <!-- 关系展示 -->
    <div class="relationship-display">
      <div class="endpoint source">
        <div class="table-name">{{ sourceTable }}</div>
        <div class="column-name">{{ sourceColumn }}</div>
      </div>
      <div class="arrow">
        <ArrowRight :size="20" />
      </div>
      <div class="endpoint target">
        <div class="table-name">{{ targetTable }}</div>
        <div class="column-name">{{ targetColumn }}</div>
      </div>
    </div>

    <!-- 关系类型选择 -->
    <div class="form-section">
      <div class="form-label">关系类型</div>
      <a-radio-group v-model:value="formData.relationshipType" class="type-radio-group">
        <a-radio-button
          v-for="item in relationshipTypes"
          :key="item.value"
          :value="item.value"
          class="type-radio-item"
          :style="{ borderColor: item.color }"
        >
          <span class="type-badge" :style="{ background: item.color }">{{ item.label }}</span>
          <span class="type-desc">{{ item.desc }}</span>
        </a-radio-button>
      </a-radio-group>
    </div>

    <!-- Footer 自定义 -->
    <template #footer>
      <div class="modal-footer">
        <a-button
          v-if="mode === 'edit' && relationshipId"
          danger
          :loading="deleteLoading"
          @click="handleDelete"
        >
          删除
        </a-button>
        <div class="footer-right">
          <a-button @click="handleCancel">取消</a-button>
          <a-button type="primary" :loading="loading" @click="handleSubmit">
            {{ mode === 'create' ? '创建' : '保存' }}
          </a-button>
        </div>
      </div>
    </template>
  </a-modal>
</template>

<script setup>
import { reactive, watch } from 'vue'
import { ArrowRight } from 'lucide-vue-next'

const props = defineProps({
  visible: { type: Boolean, default: false },
  mode: { type: String, default: 'create' }, // 'create' | 'edit'
  sourceTable: { type: String, default: '' },
  sourceColumn: { type: String, default: '' },
  targetTable: { type: String, default: '' },
  targetColumn: { type: String, default: '' },
  relationshipId: { type: Number, default: null },
  relationshipType: { type: String, default: 'many_to_one' },
  loading: { type: Boolean, default: false },
  deleteLoading: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible', 'confirm', 'delete'])

const relationshipTypes = [
  { value: 'one_to_one', label: '1:1', desc: '一对一', color: '#8b5cf6' },
  { value: 'one_to_many', label: '1:N', desc: '一对多', color: '#0ea5e9' },
  { value: 'many_to_one', label: 'N:1', desc: '多对一', color: '#10b981' },
  { value: 'many_to_many', label: 'N:M', desc: '多对多', color: '#f59e0b' }
]

const formData = reactive({
  relationshipType: 'many_to_one'
})

watch(
  () => props.visible,
  (val) => {
    if (val) {
      formData.relationshipType = props.relationshipType || 'many_to_one'
    }
  }
)

function handleSubmit() {
  emit('confirm', formData.relationshipType)
}

function handleCancel() {
  emit('update:visible', false)
}

function handleDelete() {
  emit('delete', props.relationshipId)
}
</script>

<style scoped lang="less">
.relationship-display {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 16px;
  background: var(--gray-50, #f9fafb);
  border-radius: 8px;
  margin-bottom: 20px;
}

.endpoint {
  text-align: center;

  .table-name {
    font-weight: 600;
    font-size: 14px;
    color: var(--gray-800, #1f2937);
  }

  .column-name {
    font-size: 12px;
    color: var(--gray-500, #6b7280);
    margin-top: 2px;
  }
}

.arrow {
  color: var(--gray-400, #9ca3af);
}

.form-section {
  margin-bottom: 16px;
}

.form-label {
  font-weight: 500;
  margin-bottom: 8px;
  color: var(--gray-700, #374151);
}

.type-radio-group {
  display: flex;
  flex-direction: column;
  gap: 8px;

  :deep(.ant-radio-button-wrapper) {
    height: auto;
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid var(--gray-200, #e5e7eb);

    &::before {
      display: none;
    }

    &.ant-radio-button-wrapper-checked {
      background: var(--gray-50, #f9fafb);
    }
  }
}

.type-radio-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
}

.type-desc {
  font-size: 13px;
  color: var(--gray-600, #4b5563);
}

.modal-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.footer-right {
  display: flex;
  gap: 8px;
}
</style>
