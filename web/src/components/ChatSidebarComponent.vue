<template>
  <div
    class="chat-sidebar"
    :class="{ 'sidebar-open': chatUIStore.isSidebarOpen, 'no-transition': isInitialRender }"
  >
    <div class="sidebar-content">
      <div class="sidebar-header">
        <div class="header-title">{{ branding.name }}</div>
        <div class="header-actions">
          <div
            class="toggle-sidebar nav-btn"
            v-if="chatUIStore.isSidebarOpen"
            @click="toggleCollapse"
          >
            <PanelLeftClose size="20" color="var(--gray-800)" />
          </div>
        </div>
      </div>
      <div class="conversation-list-top">
        <div class="top-actions">
          <button
            type="text"
            @click="createNewChat"
            class="new-chat-btn"
            :disabled="chatUIStore.creatingNewChat"
          >
            <LoaderCircle v-if="chatUIStore.creatingNewChat" size="18" class="loading-icon" />
            <MessageSquarePlus v-else size="18" />
            创建新对话
          </button>
          <a-select
            v-model:value="selectedRuntimeStatus"
            class="status-filter"
            size="small"
            :options="runtimeStatusOptions"
            @change="handleRuntimeStatusChange"
          />
        </div>
      </div>
      <div class="conversation-list">
        <template v-if="Object.keys(groupedChats).length > 0">
          <div v-for="(group, groupName) in groupedChats" :key="groupName" class="chat-group">
            <div class="chat-group-title">{{ groupName }}</div>
            <div
              v-for="chat in group"
              :key="chat.id"
              class="conversation-item"
              :class="{ active: currentChatId === chat.id }"
              @click="selectChat(chat)"
            >
              <div class="conversation-title">{{ chat.title || '新的对话' }}</div>
              <div class="conversation-status">
                <span class="status-dot" :class="statusClass(chat.runtime_status)"></span>
              </div>
              <div class="actions-mask"></div>
              <div class="conversation-actions">
                <a-dropdown :trigger="['click']" @click.stop>
                  <template #overlay>
                    <a-menu>
                      <a-menu-item
                        key="rename"
                        @click.stop="renameChat(chat.id)"
                        :icon="h(EditOutlined)"
                      >
                        重命名
                      </a-menu-item>
                      <a-menu-item
                        key="delete"
                        @click.stop="deleteChat(chat.id)"
                        :icon="h(DeleteOutlined)"
                      >
                        删除
                      </a-menu-item>
                    </a-menu>
                  </template>
                  <a-button type="text" class="more-btn" @click.stop>
                    <MoreOutlined />
                  </a-button>
                </a-dropdown>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="empty-list">暂无对话历史</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, h, ref, watch } from 'vue'
import { DeleteOutlined, EditOutlined, MoreOutlined } from '@ant-design/icons-vue'
import { message, Modal } from 'ant-design-vue'
import { PanelLeftClose, MessageSquarePlus, LoaderCircle } from 'lucide-vue-next'
import dayjs, { parseToShanghai } from '@/utils/time'
import { useChatUIStore } from '@/stores/chatUI'
import { useInfoStore } from '@/stores/info'
import { storeToRefs } from 'pinia'

// 使用 chatUI store
const chatUIStore = useChatUIStore()
const infoStore = useInfoStore()

const { branding } = storeToRefs(infoStore)

const props = defineProps({
  currentAgentId: {
    type: String,
    default: null
  },
  currentChatId: {
    type: String,
    default: null
  },
  chatsList: {
    type: Array,
    default: () => []
  },
  isInitialRender: {
    type: Boolean,
    default: false
  },
  singleMode: {
    type: Boolean,
    default: true
  },
  agents: {
    type: Array,
    default: () => []
  },
  selectedAgentId: {
    type: String,
    default: null
  },
  runtimeStatusFilter: {
    type: String,
    default: 'all'
  }
})

const emit = defineEmits([
  'create-chat',
  'select-chat',
  'delete-chat',
  'rename-chat',
  'toggle-sidebar',
  'open-agent-modal',
  'runtime-status-change'
])

const runtimeStatusOptions = [
  { label: '所有状态', value: 'all' },
  { label: '空闲', value: 'idle' },
  { label: '忙碌', value: 'busy' },
  { label: '已中断', value: 'interrupted' },
  { label: '错误', value: 'error' }
]

const selectedRuntimeStatus = ref('all')

watch(
  () => props.runtimeStatusFilter,
  (value) => {
    selectedRuntimeStatus.value = value || 'all'
  },
  { immediate: true }
)

const handleRuntimeStatusChange = (value) => {
  selectedRuntimeStatus.value = value
  emit('runtime-status-change', value)
}

const statusClass = (status) => {
  const normalized = status || 'idle'
  if (normalized === 'busy') return 'is-busy'
  if (normalized === 'interrupted') return 'is-interrupted'
  if (normalized === 'error') return 'is-error'
  if (normalized === 'idle') return 'is-idle'
  return 'is-unknown'
}

const groupedChats = computed(() => {
  const groups = {}
  const now = dayjs().tz('Asia/Shanghai')
  const today = now.startOf('day')
  const yesterday = today.subtract(1, 'day')
  const weekStart = today.subtract(7, 'day')
  const filteredChats =
    selectedRuntimeStatus.value === 'all'
      ? props.chatsList
      : props.chatsList.filter(
          (chat) => (chat.runtime_status || 'idle') === selectedRuntimeStatus.value
        )
  const sortedChats = [...filteredChats].sort((a, b) => {
    const dateA = parseToShanghai(a.updated_at || a.created_at)
    const dateB = parseToShanghai(b.updated_at || b.created_at)
    if (!dateA || !dateB) return 0
    return dateB.diff(dateA)
  })
  const normalizedAttentionChats = sortedChats.filter(
    (chat) => (chat.runtime_status || 'idle') === 'interrupted'
  )
  if (normalizedAttentionChats.length > 0) {
    groups['需要关注'] = normalizedAttentionChats
  }

  sortedChats.forEach((chat) => {
    if ((chat.runtime_status || 'idle') === 'interrupted') return
    const chatDate = parseToShanghai(chat.updated_at || chat.created_at)
    if (!chatDate) {
      return
    }
    if (chatDate.isAfter(today) || chatDate.isSame(today)) {
      groups['今天'] = groups['今天'] || []
      groups['今天'].push(chat)
    } else if (chatDate.isAfter(yesterday) || chatDate.isSame(yesterday)) {
      groups['昨天'] = groups['昨天'] || []
      groups['昨天'].push(chat)
    } else if (chatDate.isAfter(weekStart)) {
      groups['本周'] = groups['本周'] || []
      groups['本周'].push(chat)
    } else {
      groups['更早'] = groups['更早'] || []
      groups['更早'].push(chat)
    }
  })

  return groups
})

const createNewChat = () => {
  emit('create-chat')
}

const selectChat = (chat) => {
  emit('select-chat', chat.id)
}

const deleteChat = (chatId) => {
  emit('delete-chat', chatId)
}

const renameChat = async (chatId) => {
  try {
    const chat = props.chatsList.find((c) => c.id === chatId)
    if (!chat) return

    let newTitle = chat.title
    Modal.confirm({
      title: '重命名对话',
      content: h('div', { style: { marginTop: '12px' } }, [
        h('input', {
          value: newTitle,
          style: {
            width: '100%',
            padding: '4px 8px',
            border: '1px solid var(--gray-150)',
            background: 'var(--gray-0)',
            borderRadius: '4px'
          },
          onInput: (e) => {
            newTitle = e.target.value
          }
        })
      ]),
      okText: '确认',
      cancelText: '取消',
      onOk: () => {
        if (!newTitle.trim()) {
          message.warning('标题不能为空')
          return Promise.reject()
        }
        emit('rename-chat', { chatId, title: newTitle })
      },
      onCancel: () => {}
    })
  } catch (error) {
    console.error('重命名对话失败:', error)
  }
}

const toggleCollapse = () => {
  emit('toggle-sidebar')
}
</script>

<style lang="less" scoped>
.chat-sidebar {
  width: 0;
  height: 100%;
  background-color: var(--gray-0);
  transition: all 0.3s ease;
  display: flex;
  flex-direction: column;
  border: none;
  overflow: hidden;

  .sidebar-content {
    // 保持内部宽度，避免折叠时压缩
    width: 280px;
    min-width: 280px;
    height: 100%;
    display: flex;
    flex-direction: column;
    opacity: 1;
    transform: translateX(0);
    transition:
      opacity 0.2s ease,
      transform 0.3s ease;
  }

  &:not(.sidebar-open) .sidebar-content {
    opacity: 0;
    transform: translateX(-12px);
  }

  &.no-transition {
    transition: none !important;
  }

  &.sidebar-open {
    width: 280px;
    max-width: 300px;
    border-right: 1px solid var(--gray-200);
  }

  .sidebar-header {
    height: var(--header-height);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
    border-bottom: 1px solid var(--gray-50);
    flex-shrink: 0;

    .header-title {
      font-weight: 600;
      font-size: 16px;
      color: var(--gray-900);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      // color: var(--gray-600);
    }
  }

  .conversation-list-top {
    padding: 8px 12px;

    .top-actions {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .new-chat-btn {
      width: 100%;
      padding: 8px 12px;
      border-radius: 8px;
      background-color: var(--gray-0);
      color: var(--main-color);
      border: 1px solid var(--gray-150);
      transition: all 0.2s ease;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      box-shadow: 0 3px 4px rgba(0, 10, 20, 0.02);

      &:hover:not(:disabled) {
        box-shadow: 0 3px 4px rgba(0, 10, 20, 0.07);
      }

      &:disabled {
        cursor: not-allowed;
        opacity: 0.7;
      }

      .loading-icon {
        animation: spin 1s linear infinite;
      }
    }

    .status-filter {
      width: 100%;
    }
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  .conversation-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;

    .chat-group {
      margin-bottom: 16px;
    }

    .chat-group-title {
      padding: 4px 8px;
      font-size: 12px;
      color: var(--gray-500);
      font-weight: 500;
      text-transform: uppercase;
    }

    .conversation-item {
      display: flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 6px;
      margin: 4px 0;
      cursor: pointer;
      transition: background-color 0.2s ease;
      position: relative;
      overflow: hidden;

      .conversation-title {
        flex: 1;
        font-size: 14px;
        color: var(--gray-800);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        transition: color 0.2s ease;
      }

      .conversation-status {
        width: 14px;
        display: flex;
        justify-content: center;
        align-items: center;
        margin-right: 28px;

        .status-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          display: inline-block;
        }

        .status-dot.is-idle {
          background: #22c55e;
        }

        .status-dot.is-busy {
          background: #3b82f6;
        }

        .status-dot.is-interrupted {
          background: #f97316;
        }

        .status-dot.is-error {
          background: #dc2626;
        }

        .status-dot.is-unknown {
          background: #9ca3af;
        }
      }

      .actions-mask {
        position: absolute;
        right: 0;
        top: 0;
        bottom: 0;
        width: 60px;
        background: linear-gradient(to right, transparent, var(--bg-sider) 20px);
        opacity: 0;
        transition: opacity 0.3s ease;
        pointer-events: none;
      }

      .conversation-actions {
        display: flex;
        align-items: center;
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        opacity: 0;
        transition: opacity 0.3s ease;

        .more-btn {
          color: var(--gray-600);
          background-color: transparent !important;
          padding: 0;
          &:hover {
            color: var(--main-500);
            background-color: transparent !important;
          }
        }
      }

      &:hover {
        background-color: var(--gray-25);

        .actions-mask {
          background: linear-gradient(to right, transparent, var(--gray-25) 20px);
        }

        .actions-mask,
        .conversation-actions {
          opacity: 1;
        }
      }

      &.active {
        background-color: var(--gray-50);

        .conversation-title {
          color: var(--main-600);
          font-weight: 500;
        }
        .actions-mask {
          background: linear-gradient(to right, transparent, var(--gray-50) 20px);
        }
      }
    }

    .empty-list {
      text-align: center;
      margin-top: 20px;
      color: var(--gray-500);
      font-size: 14px;
    }
  }
}

// Scrollbar styling
.conversation-list::-webkit-scrollbar {
  width: 5px;
}
.conversation-list::-webkit-scrollbar-track {
  background: transparent;
}
.conversation-list::-webkit-scrollbar-thumb {
  background: var(--gray-300);
  border-radius: 5px;
}
.conversation-list::-webkit-scrollbar-thumb:hover {
  background: var(--gray-400);
}

.toggle-sidebar.nav-btn {
  cursor: pointer;
  height: 2.5rem;
  display: flex;
  justify-content: center;
  align-items: center;
  border-radius: 8px;
  // padding: 0.5rem;
  transition: background-color 0.3s;

  svg {
    stroke: var(--gray-600);
  }

  &:hover svg {
    stroke: var(--main-color);
  }
}
</style>
