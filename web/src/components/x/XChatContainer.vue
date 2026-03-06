<template>
  <div class="x-chat-container">
    <!-- 消息列表 -->
    <div class="x-chat-messages" ref="messagesRef">
      <template v-for="(conv, convIndex) in conversations" :key="convIndex">
        <div class="x-conv-box">
          <XBubbleMessage
            v-for="(message, msgIndex) in conv.messages"
            :key="msgIndex"
            :message="message"
            :is-processing="
              isProcessing &&
              conv.status === 'streaming' &&
              msgIndex === conv.messages.length - 1
            "
            :show-refs="showMsgRefs(message, conv)"
            @retry="$emit('retry', message)"
            @retryStoppedMessage="$emit('retryStoppedMessage', $event)"
          />
        </div>

        <!-- 最后一条消息的 Refs -->
        <RefsComponent
          v-if="shouldShowConvRefs(conv)"
          :message="getLastMessage(conv)"
          :show-refs="['model', 'copy']"
          :is-latest-message="false"
        />
      </template>

      <!-- 生成中状态 -->
      <div v-if="isProcessing && conversations.length > 0" class="x-generating-status">
        <div class="x-generating-indicator">
          <div class="loading-dots">
            <div></div>
            <div></div>
            <div></div>
          </div>
          <span class="generating-text">
            <template v-if="activeSubagent">
              <span class="subagent-badge">{{ activeSubagent }}</span>
              正在执行...
            </template>
            <template v-else>正在生成回复...</template>
          </span>
        </div>
      </div>
    </div>

    <!-- 底部输入区域 -->
    <div class="x-chat-bottom" :class="{ 'start-screen': !conversations.length }">
      <slot name="approval-modal"></slot>

      <div class="x-input-wrapper">
        <!-- 加载状态 -->
        <div v-if="isLoadingMessages" class="x-chat-loading">
          <div class="loading-spinner"></div>
          <span>正在加载消息...</span>
        </div>

        <!-- 欢迎区域 -->
        <div v-if="!conversations.length" class="x-welcome">
          <h1>👋 您好，我是{{ agentName }}！</h1>
        </div>

        <!-- 输入框 -->
        <XSenderInput
          v-model="inputValue"
          :is-loading="isProcessing"
          :disabled="disabled"
          :placeholder="placeholder"
          :supports-file-upload="supportsFileUpload"
          :has-state-content="hasStateContent"
          :is-panel-open="isPanelOpen"
          @send="handleSend"
          @toggle-panel="$emit('toggle-panel')"
        >
          <template #attachment-options>
            <slot name="attachment-options"></slot>
          </template>
        </XSenderInput>

        <!-- 示例问题 -->
        <div v-if="!conversations.length && examples.length > 0" class="x-examples">
          <div class="example-chips">
            <div
              v-for="example in examples"
              :key="example.id"
              class="example-chip"
              @click="$emit('example-click', example.text)"
            >
              {{ example.text }}
            </div>
          </div>
        </div>

        <div v-else class="x-bottom-note">
          <p class="note">请注意辨别内容的可靠性</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import XBubbleMessage from './XBubbleMessage.vue'
import XSenderInput from './XSenderInput.vue'
import RefsComponent from '@/components/RefsComponent.vue'

const props = defineProps({
  conversations: { type: Array, default: () => [] },
  isProcessing: { type: Boolean, default: false },
  isLoadingMessages: { type: Boolean, default: false },
  activeSubagent: { type: String, default: null },
  agentName: { type: String, default: '智能助手' },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '输入问题...' },
  supportsFileUpload: { type: Boolean, default: false },
  hasStateContent: { type: Boolean, default: false },
  isPanelOpen: { type: Boolean, default: false },
  examples: { type: Array, default: () => [] },
  approvalState: { type: Object, default: () => ({}) },
  modelValue: { type: String, default: '' }
})

const emit = defineEmits([
  'update:modelValue',
  'send',
  'retry',
  'retryStoppedMessage',
  'toggle-panel',
  'example-click'
])

const messagesRef = ref(null)

const inputValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const handleSend = (payload) => {
  emit('send', payload)
}

// 获取对话最后一条 AI 消息
const getLastMessage = (conv) => {
  if (!conv?.messages?.length) return null
  for (let i = conv.messages.length - 1; i >= 0; i--) {
    if (conv.messages[i].type === 'ai') return conv.messages[i]
  }
  return null
}

// 是否显示对话级 Refs
const shouldShowConvRefs = (conv) => {
  return (
    getLastMessage(conv) &&
    conv.status !== 'streaming' &&
    !props.approvalState?.showModal
  )
}

// 消息级 Refs 显示逻辑
const showMsgRefs = (msg) => {
  if (props.approvalState?.showModal) return false
  if (msg.isLast && msg.status === 'finished') return ['copy']
  return false
}

// 滚动到底部
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

// 监听消息变化自动滚动
watch(
  () => props.conversations,
  () => {
    if (props.isProcessing) {
      scrollToBottom()
    }
  },
  { deep: true }
)

defineExpose({ scrollToBottom })
</script>

<style lang="less" scoped>
@import '@/assets/css/animations.less';

.x-chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
}

.x-chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.25rem;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
  scrollbar-width: none;
}

.x-conv-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 16px;
}

.x-generating-status {
  display: flex;
  justify-content: flex-start;
  padding: 1rem 0;
  animation: fadeInUp 0.4s ease-out;
}

.x-generating-indicator {
  display: flex;
  align-items: center;
  padding: 0.75rem 0;

  .generating-text {
    margin-left: 12px;
    font-size: 14px;
    font-weight: 500;
    letter-spacing: 0.025em;
    background: linear-gradient(
      90deg,
      var(--gray-700) 0%,
      var(--gray-700) 40%,
      var(--gray-300) 45%,
      var(--gray-200) 50%,
      var(--gray-300) 55%,
      var(--gray-700) 60%,
      var(--gray-700) 100%
    );
    background-size: 200% auto;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: waveFlash 2s linear infinite;

    .subagent-badge {
      display: inline-block;
      padding: 2px 8px;
      margin-right: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--primary-600);
      background: var(--primary-100);
      border-radius: 4px;
      -webkit-background-clip: unset;
      background-clip: unset;
    }
  }
}

.loading-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;

  div {
    width: 6px;
    height: 6px;
    background: linear-gradient(135deg, var(--main-color), var(--main-700));
    border-radius: 50%;
    animation: dotPulse 1.4s infinite ease-in-out both;

    &:nth-child(1) { animation-delay: -0.32s; }
    &:nth-child(2) { animation-delay: -0.16s; }
    &:nth-child(3) { animation-delay: 0s; }
  }
}

.x-chat-bottom {
  position: sticky;
  bottom: 0;
  width: 100%;
  padding: 4px 1rem 0;
  background: var(--gray-0);
  z-index: 1000;

  &.start-screen {
    position: absolute;
    top: 45%;
    left: 50%;
    transform: translate(-50%, -50%);
    bottom: auto;
    max-width: 800px;
    width: 90%;
    background: transparent;
    padding: 0;
  }
}

.x-input-wrapper {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
}

.x-welcome {
  padding: 32px 0;
  text-align: center;

  h1 {
    font-size: 1.2rem;
    color: var(--gray-1000);
    margin: 0;
  }
}

.x-chat-loading {
  padding: 0 50px;
  text-align: center;
  position: absolute;
  top: 20%;
  width: 100%;
  z-index: 9;
  animation: slideInUp 0.5s ease-out;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;

  span {
    color: var(--gray-700);
    font-size: 14px;
  }

  .loading-spinner {
    width: 20px;
    height: 20px;
    border: 2px solid var(--gray-200);
    border-top-color: var(--main-color);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
}

.x-examples {
  margin-top: 16px;
  text-align: center;

  .example-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
  }

  .example-chip {
    padding: 6px 12px;
    background: var(--gray-25);
    border-radius: 16px;
    cursor: pointer;
    font-size: 0.8rem;
    color: var(--gray-700);
    transition: all 0.15s ease;
    white-space: nowrap;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover {
      border-color: var(--main-200);
      color: var(--main-700);
      box-shadow: 0 0px 4px rgba(0, 0, 0, 0.03);
    }
  }
}

.x-bottom-note {
  display: flex;
  justify-content: center;

  .note {
    font-size: small;
    color: var(--gray-300);
    margin: 4px 0;
    user-select: none;
  }
}

@keyframes waveFlash {
  0% { background-position: 200% center; }
  100% { background-position: -200% center; }
}

@keyframes dotPulse {
  0%, 80%, 100% {
    transform: scale(0);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
