<script setup>
import { ref, computed, h } from 'vue'
import { Sender } from 'ant-design-x-vue'
import { message } from 'ant-design-vue'
import { LinkOutlined } from '@ant-design/icons-vue'
import { FolderCode } from 'lucide-vue-next'
import ImagePreviewComponent from '@/components/ImagePreviewComponent.vue'
import AttachmentOptionsComponent from '@/components/AttachmentOptionsComponent.vue'
import { threadApi } from '@/apis'
import { AgentValidator } from '@/utils/agentValidator'
import { handleChatError, handleValidationError } from '@/utils/errorHandler'

const props = defineProps({
  modelValue: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '输入问题...' },
  supportsFileUpload: { type: Boolean, default: false },
  agentId: { type: String, default: '' },
  threadId: { type: String, default: null },
  ensureThread: { type: Function, default: null },
  hasStateContent: { type: Boolean, default: false },
  isPanelOpen: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'send', 'toggle-panel', 'attachment-changed'])

const currentImage = ref(null)
const headerOpen = ref(false)
const attachmentRef = ref(null)

// 输入值变化处理
const handleChange = (val) => {
  emit('update:modelValue', val)
}

// 提交处理
const handleSubmit = () => {
  emit('send', { image: currentImage.value })
  currentImage.value = null
}

// 取消处理
const handleCancel = () => {
  // 取消生成时的逻辑由父组件处理
}

// 附件上传处理
const handleAttachmentUpload = async (files) => {
  if (!files?.length) return
  if (
    !props.agentId ||
    !AgentValidator.validateAgentIdWithError(props.agentId, '上传附件', handleValidationError)
  ) {
    return
  }

  let threadId = props.threadId

  if (!threadId && props.ensureThread) {
    const preferredTitle = files[0]?.name || '新的对话'
    try {
      threadId = await props.ensureThread(preferredTitle)
    } catch {
      return
    }
  }

  if (!threadId) {
    message.error('创建对话失败，无法上传附件')
    return
  }

  const hide = message.loading({
    content: '正在上传附件...',
    key: 'upload-attachment',
    duration: 0
  })

  let successCount = 0
  const failed = []

  for (const file of files) {
    try {
      await threadApi.uploadThreadAttachment(threadId, file)
      successCount += 1
    } catch (error) {
      failed.push(error)
    }
  }

  if (successCount > 0) {
    emit('attachment-changed', threadId)
  }

  if (failed.length === 0) {
    message.success({
      content: `附件上传成功（${successCount}/${files.length}）`,
      key: 'upload-attachment',
      duration: 2
    })
  } else if (successCount > 0) {
    message.warning({
      content: `部分附件上传失败（成功 ${successCount}，失败 ${failed.length}）`,
      key: 'upload-attachment',
      duration: 3
    })
  } else {
    message.destroy('upload-attachment')
    handleChatError(failed[0], 'upload')
  }

  hide?.()
}

const handleImageUpload = (imageData) => {
  if (imageData?.success) {
    currentImage.value = imageData
    headerOpen.value = true
  }
}

const handleImageRemoved = () => {
  currentImage.value = null
  headerOpen.value = false
}

// Header 节点 - 图片预览
const headerNode = computed(() => {
  if (!currentImage.value) return undefined
  return h(
    Sender.Header,
    {
      title: '图片预览',
      open: headerOpen.value,
      onOpenChange: (v) => {
        headerOpen.value = v
      }
    },
    {
      default: () =>
        h(ImagePreviewComponent, {
          'image-data': currentImage.value,
          onRemove: handleImageRemoved,
          class: 'image-preview-wrapper'
        })
    }
  )
})

// Prefix 节点 - 附件按钮（简洁链接图标）
const prefixNode = computed(() => {
  if (!props.supportsFileUpload) {
    // 即使不支持上传，也显示一个占位图标保持布局一致
    return h(LinkOutlined, { class: 'prefix-icon disabled' })
  }
  return h(AttachmentOptionsComponent, {
    ref: attachmentRef,
    disabled: props.disabled,
    onUpload: handleAttachmentUpload,
    'onUpload-image': handleImageUpload,
    class: 'attachment-trigger'
  })
})

// Actions 节点 - 状态按钮（仅在有状态时显示）
const actionsNode = computed(() => {
  if (!props.hasStateContent) return undefined
  return h('div', { class: 'x-sender-actions' }, [
    h(
      'div',
      {
        class: ['state-toggle-btn', { active: props.isPanelOpen }],
        title: '查看工作状态',
        onClick: () => emit('toggle-panel')
      },
      [h(FolderCode, { size: 14 }), h('span', null, '状态')]
    )
  ])
})
</script>

<template>
  <div class="x-sender-wrapper">
    <Sender
      :value="modelValue"
      :placeholder="placeholder"
      :loading="isLoading"
      :disabled="disabled"
      :header="headerNode"
      :prefix="prefixNode"
      :actions="actionsNode"
      :auto-size="{ minRows: 1, maxRows: 6 }"
      @change="handleChange"
      @submit="handleSubmit"
      @cancel="handleCancel"
      class="x-sender"
    />
  </div>
</template>

<style lang="less" scoped>
.x-sender-wrapper {
  width: 100%;
  padding: 16px 20px;
  background: var(--gray-0);
}

.x-sender {
  :deep(.ant-sender) {
    border: 1px solid var(--gray-200);
    border-radius: 24px;
    background: var(--gray-0);
    padding: 4px 8px 4px 16px;
    transition: all 0.2s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);

    &:hover {
      border-color: var(--gray-300);
    }

    &:focus-within {
      border-color: var(--main-400);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
    }
  }

  :deep(.ant-sender-content) {
    align-items: center;
  }

  :deep(.ant-sender-prefix) {
    margin-right: 8px;
    display: flex;
    align-items: center;
  }

  :deep(.ant-sender-input) {
    font-size: 15px;
    line-height: 1.5;
    min-height: 40px;
    padding: 8px 0;

    &::placeholder {
      color: var(--gray-400);
    }
  }

  :deep(.ant-sender-actions) {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  :deep(.ant-sender-actions-btn) {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    cursor: pointer;
    transition: all 0.2s ease;
    flex-shrink: 0;

    &:hover:not(:disabled) {
      transform: scale(1.05);
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
    }

    &:active:not(:disabled) {
      transform: scale(0.95);
    }

    &:disabled {
      background: var(--gray-200);
      cursor: not-allowed;
    }

    .anticon {
      color: white;
      font-size: 16px;
    }
  }
}

.prefix-icon {
  font-size: 18px;
  color: var(--gray-500);
  cursor: pointer;
  transition: color 0.2s ease;

  &:hover:not(.disabled) {
    color: var(--main-500);
  }

  &.disabled {
    cursor: default;
    opacity: 0.5;
  }
}

:deep(.attachment-trigger) {
  .ant-btn {
    border: none;
    background: transparent;
    padding: 0;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;

    &:hover {
      background: var(--gray-100);
      border-radius: 50%;
    }

    .anticon {
      font-size: 18px;
      color: var(--gray-500);
    }
  }
}

.x-sender-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 8px;
}

.state-toggle-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  height: 28px;
  border-radius: 14px;
  font-size: 12px;
  color: var(--gray-600);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  background: var(--gray-100);
  border: none;

  &:hover {
    color: var(--main-600);
    background: var(--main-50);
  }

  &.active {
    color: var(--main-600);
    background: var(--main-100);
    font-weight: 500;
  }

  span {
    line-height: 1;
  }
}

.image-preview-wrapper {
  max-width: 200px;
  padding: 12px;
}
</style>
