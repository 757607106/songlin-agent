<script setup>
import { computed, h } from 'vue'
import { Bubble, ThoughtChain } from 'ant-design-x-vue'
import { Typography } from 'ant-design-vue'
import {
  CheckCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  BulbOutlined
} from '@ant-design/icons-vue'
import RefsComponent from '@/components/RefsComponent.vue'
import markdownit from 'markdown-it'

const props = defineProps({
  message: { type: Object, required: true },
  isProcessing: { type: Boolean, default: false },
  showRefs: { type: [Array, Boolean], default: false },
  isLatestMessage: { type: Boolean, default: false }
})

const emit = defineEmits(['retry', 'retryStoppedMessage', 'openRefs'])

const md = markdownit({ html: true, breaks: true })

// Markdown 渲染函数
const renderMarkdown = (content) => {
  return h(Typography, null, {
    default: () => h('div', { innerHTML: md.render(content || '') })
  })
}

// 解析消息内容
const parsedData = computed(() => {
  let content = props.message.content?.trim() || ''
  let reasoning_content = props.message.additional_kwargs?.reasoning_content || ''

  if (reasoning_content) {
    return { content, reasoning_content }
  }

  const thinkRegex = /<think>(.*?)<\/think>|<think>(.*?)$/s
  const thinkMatch = content.match(thinkRegex)

  if (thinkMatch) {
    reasoning_content = (thinkMatch[1] || thinkMatch[2] || '').trim()
    content = content.replace(thinkMatch[0], '').trim()
  }

  return { content, reasoning_content }
})

// 错误显示
const displayError = computed(() => {
  return !!(props.message.error_type || props.message.extra_metadata?.error_type)
})

const getErrorMessage = computed(() => {
  if (props.message.error_message) return props.message.error_message
  if (props.message.extra_metadata?.error_message) return props.message.extra_metadata.error_message

  const errorTypes = {
    interrupted: '回答生成已中断',
    content_guard_blocked: '检测到敏感内容，已中断输出',
    unexpect: '生成过程中出现异常',
    agent_error: '智能体获取失败'
  }
  return errorTypes[props.message.error_type] || null
})

// 获取状态图标
const getStatusIcon = (status) => {
  switch (status) {
    case 'success':
      return h(CheckCircleOutlined)
    case 'error':
      return h(CloseCircleOutlined)
    case 'pending':
      return h(LoadingOutlined)
    default:
      return undefined
  }
}

// 思考过程 ThoughtChain items
const reasoningChainItems = computed(() => {
  if (!parsedData.value.reasoning_content) return []

  const isThinking = props.message.status === 'reasoning'
  return [
    {
      title: isThinking ? '正在思考...' : '推理过程',
      status: isThinking ? 'pending' : 'success',
      icon: isThinking ? h(LoadingOutlined) : h(BulbOutlined),
      description: parsedData.value.reasoning_content
    }
  ]
})

// 工具调用 ThoughtChain items
const toolChainItems = computed(() => {
  const toolCalls = props.message.tool_calls
  if (!toolCalls || !Array.isArray(toolCalls) || toolCalls.length === 0) return []

  return toolCalls
    .filter((tc) => tc && (tc.id || tc.name))
    .map((tc, index) => {
      const toolName = tc.name || tc.function?.name || '工具调用'
      const hasResult = !!tc.tool_call_result
      const isError = tc.tool_call_result?.status === 'error'

      let status = 'pending'
      if (hasResult) {
        status = isError ? 'error' : 'success'
      }

      let args = tc.args || tc.function?.arguments
      if (typeof args === 'string') {
        try {
          args = JSON.parse(args)
        } catch {
          // keep as string
        }
      }

      return {
        key: tc.id || `tool-${index}`,
        title: toolName,
        status,
        icon: getStatusIcon(status),
        description: typeof args === 'object' ? JSON.stringify(args, null, 2) : String(args || '')
      }
    })
})
</script>

<template>
  <!-- 多模态图片 -->
  <div
    v-if="message.message_type === 'multimodal_image' && message.image_content"
    class="x-message-image"
  >
    <img :src="`data:image/jpeg;base64,${message.image_content}`" alt="用户上传的图片" />
  </div>

  <!-- 用户消息 -->
  <Bubble
    v-if="message.type === 'human'"
    :content="message.content"
    placement="end"
    variant="filled"
    class="x-bubble-human"
  />

  <!-- 系统消息 -->
  <div v-else-if="message.type === 'system'" class="x-message-system">
    {{ message.content }}
  </div>

  <!-- AI 消息 -->
  <div v-else-if="message.type === 'ai'" class="x-message-ai">
    <!-- 思考过程 -->
    <ThoughtChain
      v-if="reasoningChainItems.length > 0"
      :items="reasoningChainItems"
      size="small"
      collapsible
      class="x-thought-chain"
    />

    <!-- 消息内容 -->
    <Bubble
      v-if="parsedData.content"
      :content="parsedData.content"
      placement="start"
      variant="borderless"
      :typing="isProcessing ? { step: 2, interval: 50 } : undefined"
      :message-render="renderMarkdown"
      class="x-bubble-ai"
    />

    <div v-else-if="parsedData.reasoning_content" class="empty-block"></div>

    <!-- 错误提示 -->
    <div v-if="displayError" class="x-error-hint">
      <span v-if="getErrorMessage">{{ getErrorMessage }}</span>
      <span v-else-if="message.error_type === 'interrupted'">回答生成已中断</span>
      <span v-else-if="message.error_type === 'unexpect'">生成过程中出现异常</span>
      <span v-else-if="message.error_type === 'content_guard_blocked'">检测到敏感内容，已中断输出</span>
      <span v-else>{{ message.error_type || '未知错误' }}</span>
    </div>

    <!-- 工具调用链 -->
    <ThoughtChain
      v-if="toolChainItems.length > 0"
      :items="toolChainItems"
      size="small"
      collapsible
      class="x-tool-chain"
    />

    <!-- 用户中断提示 -->
    <div v-if="message.isStoppedByUser" class="x-retry-hint">
      你停止生成了本次回答
      <span class="retry-link" @click="emit('retryStoppedMessage', message.id)">重新编辑问题</span>
    </div>

    <!-- Refs 引用 -->
    <RefsComponent
      v-if="showRefs && message.status === 'finished'"
      :message="message"
      :show-refs="showRefs"
      :is-latest-message="isLatestMessage"
      @retry="emit('retry')"
      @openRefs="emit('openRefs', $event)"
    />
  </div>
</template>

<style lang="less" scoped>
.x-message-image {
  border-radius: 12px;
  overflow: hidden;
  margin-left: auto;
  border: 1px solid rgba(255, 255, 255, 0.2);
  margin-bottom: 8px;

  img {
    max-width: 100%;
    max-height: 200px;
    object-fit: contain;
  }
}

.x-message-system {
  color: var(--gray-600);
  font-style: italic;
  font-size: 14px;
  padding: 8px 12px;
  background-color: var(--gray-50);
  border-left: 3px solid var(--gray-300);
  border-radius: 4px;
  margin: 8px 0;
}

.x-message-ai {
  width: 100%;
}

.x-bubble-human {
  :deep(.ant-bubble-content) {
    background: var(--main-50) !important;
    color: var(--gray-1000);
    border-radius: 12px;
    max-width: 95%;
  }
}

.x-bubble-ai {
  :deep(.ant-bubble-content) {
    background: transparent !important;
    padding: 0;
  }
}

.x-thought-chain,
.x-tool-chain {
  margin: 8px 0;
  padding: 12px;
  background: var(--gray-25);
  border-radius: 8px;
  border: 1px solid var(--gray-150);

  :deep(.ant-thought-chain-item-header-title) {
    font-size: 14px;
    font-weight: 500;
  }

  :deep(.ant-thought-chain-item-content) {
    font-size: 13px;
    color: var(--gray-700);
    white-space: pre-wrap;
    line-height: 1.6;
  }
}

.x-tool-chain {
  :deep(.ant-thought-chain-item-header-title) {
    font-size: 13px;
    font-family: monospace;
  }

  :deep(.ant-thought-chain-item-content) {
    font-size: 12px;
    font-family: monospace;
    color: var(--gray-600);
    max-height: 150px;
    overflow-y: auto;
  }
}

.x-error-hint {
  margin: 10px 0;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  background-color: var(--color-error-50);
  color: var(--color-error-500);
}

.x-retry-hint {
  margin-top: 8px;
  padding: 8px 16px;
  color: var(--gray-600);
  font-size: 14px;

  .retry-link {
    color: var(--color-info-500);
    cursor: pointer;
    margin-left: 4px;

    &:hover {
      text-decoration: underline;
    }
  }
}

.empty-block {
  height: 8px;
}
</style>
