<template>
  <a-modal
    :open="visible"
    :title="`编辑表 - ${table?.table_name || ''}`"
    :confirm-loading="loading"
    @ok="handleSubmit"
    @cancel="handleCancel"
    width="600px"
    destroyOnClose
  >
    <a-form layout="vertical">
      <a-form-item label="表名">
        <a-input :value="table?.table_name" disabled />
      </a-form-item>

      <a-form-item label="表描述">
        <a-textarea v-model:value="formData.tableComment" :rows="2" placeholder="请输入表描述" />
      </a-form-item>

      <a-form-item label="列信息">
        <a-table
          :columns="columnTableColumns"
          :data-source="table?.columns || []"
          :pagination="false"
          size="small"
          rowKey="id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'column_comment'">
              <div v-if="editingColumnId === record.id" class="edit-cell">
                <a-input
                  v-model:value="editingComment"
                  size="small"
                  @pressEnter="saveColumnComment(record.id)"
                  @blur="saveColumnComment(record.id)"
                  ref="commentInput"
                />
              </div>
              <div v-else class="comment-cell" @click="startEditColumn(record)">
                <span>{{ record.column_comment || '-' }}</span>
                <EditOutlined class="edit-icon" />
              </div>
            </template>
          </template>
        </a-table>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { reactive, ref, watch, nextTick } from 'vue'
import { EditOutlined } from '@ant-design/icons-vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  table: { type: Object, default: null },
  loading: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible', 'save', 'updateColumn'])

const formData = reactive({
  tableComment: ''
})

const editingColumnId = ref(null)
const editingComment = ref('')
const commentInput = ref(null)

const columnTableColumns = [
  { title: '列名', dataIndex: 'column_name', key: 'column_name', width: 140 },
  { title: '类型', dataIndex: 'column_type', key: 'column_type', width: 100 },
  {
    title: '主键',
    dataIndex: 'is_primary_key',
    key: 'is_primary_key',
    width: 60,
    customRender: ({ text }) => (text ? 'Y' : '')
  },
  { title: '描述', dataIndex: 'column_comment', key: 'column_comment' }
]

watch(
  () => props.visible,
  (val) => {
    if (val && props.table) {
      formData.tableComment = props.table.table_comment || ''
      editingColumnId.value = null
    }
  }
)

function startEditColumn(record) {
  editingColumnId.value = record.id
  editingComment.value = record.column_comment || ''
  nextTick(() => {
    commentInput.value?.focus()
  })
}

function saveColumnComment(columnId) {
  if (editingColumnId.value === columnId) {
    emit('updateColumn', columnId, editingComment.value)
    editingColumnId.value = null
  }
}

function handleSubmit() {
  emit('save', formData.tableComment)
}

function handleCancel() {
  emit('update:visible', false)
}
</script>

<style scoped lang="less">
.comment-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  padding: 4px 0;

  &:hover {
    background: var(--gray-50, #f9fafb);
  }

  .edit-icon {
    opacity: 0;
    font-size: 12px;
    color: var(--gray-400, #9ca3af);
    transition: opacity 0.2s;
  }

  &:hover .edit-icon {
    opacity: 1;
  }
}

.edit-cell {
  padding: 2px 0;
}
</style>
