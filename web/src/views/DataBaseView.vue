<template>
  <div class="database-container layout-container">
    <div class="glass-panel">
      <HeaderComponent title="文档知识库" :loading="dbState.listLoading">
        <template #actions>
          <a-button type="primary" @click="state.openNewDatabaseModel = true">
            <template #icon><PlusOutlined /></template>
            新建知识库
          </a-button>
        </template>
      </HeaderComponent>

      <!-- 加载状态 -->
      <div v-if="dbState.listLoading" class="loading-container">
        <a-spin size="large" />
        <p>正在加载知识库...</p>
      </div>

      <!-- 空状态显示 -->
      <div v-else-if="!databases || databases.length === 0" class="empty-state">
        <div class="empty-icon-wrapper">
          <DatabaseOutlined class="empty-icon" />
        </div>
        <h3 class="empty-title">暂无知识库</h3>
        <p class="empty-description">创建您的第一个知识库，开始管理文档和知识</p>
        <a-button type="primary" size="large" @click="state.openNewDatabaseModel = true">
          <template #icon>
            <PlusOutlined />
          </template>
          创建知识库
        </a-button>
      </div>

      <!-- 数据库列表 -->
      <div v-else class="databases-grid">
        <div
          v-for="database in databases"
          :key="database.db_id"
          class="database-card"
          @click="navigateToDatabase(database.db_id)"
        >
          <!-- 私有知识库锁定图标 -->
          <div v-if="database.metadata?.is_private" class="private-badge" title="私有知识库">
            <LockOutlined />
          </div>

          <div class="card-content">
            <div class="card-header-row">
              <div class="icon-wrapper">
                <component :is="getKbTypeIcon(database.kb_type || 'lightrag')" />
              </div>
              <div class="header-info">
                <h3 class="title">{{ database.name }}</h3>
                <div class="meta-info">
                  <span class="file-count"
                    >{{ database.files ? Object.keys(database.files).length : 0 }} 文件</span
                  >
                  <span class="separator">•</span>
                  <span class="time" v-if="database.created_at">
                    {{ formatCreatedTime(database.created_at) }}
                  </span>
                </div>
              </div>
            </div>

            <p class="description">{{ database.description || '暂无描述' }}</p>

            <div class="tags-row">
              <a-tag color="blue" v-if="database.embed_info?.name" class="custom-tag">
                {{ database.embed_info.name }}
              </a-tag>
              <a-tag
                :color="getKbTypeColor(database.kb_type || 'lightrag')"
                class="kb-type-tag custom-tag"
              >
                {{ getKbTypeLabel(database.kb_type || 'lightrag') }}
              </a-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <a-modal
      :open="state.openNewDatabaseModel"
      title="新建知识库"
      :confirm-loading="dbState.creating"
      @ok="handleCreateDatabase"
      @cancel="cancelCreateDatabase"
      class="custom-modal new-database-modal"
      width="800px"
      destroyOnClose
      :maskClosable="false"
    >
      <!-- 知识库类型选择 -->
      <div class="form-section">
        <h3 class="section-title">知识库类型<span class="required">*</span></h3>
        <div class="kb-type-cards">
          <div
            v-for="(typeInfo, typeKey) in orderedKbTypes"
            :key="typeKey"
            class="kb-type-card"
            :class="{ active: newDatabase.kb_type === typeKey }"
            :data-type="typeKey"
            @click="handleKbTypeChange(typeKey)"
          >
            <div class="card-header">
              <component :is="getKbTypeIcon(typeKey)" class="type-icon" />
              <span class="type-title">{{ getKbTypeLabel(typeKey) }}</span>
            </div>
            <div class="card-description">{{ typeInfo.description }}</div>
            <div class="selection-indicator" v-if="newDatabase.kb_type === typeKey">
              <CheckCircleFilled />
            </div>
          </div>
        </div>
      </div>

      <div class="form-section">
        <h3 class="section-title">基本信息</h3>
        <div class="form-item">
          <label>知识库名称<span class="required">*</span></label>
          <a-input v-model:value="newDatabase.name" placeholder="请输入知识库名称" size="large" />
        </div>

        <div class="form-item">
          <label>嵌入模型</label>
          <EmbeddingModelSelector
            v-model:value="newDatabase.embed_model_name"
            style="width: 100%"
            size="large"
            placeholder="请选择嵌入模型"
          />
        </div>
      </div>

      <!-- 仅对 LightRAG 提供语言选择和LLM选择 -->
      <div v-if="newDatabase.kb_type === 'lightrag'" class="form-section">
        <h3 class="section-title">LightRAG 配置</h3>
        <div class="form-row">
          <div class="form-item half">
            <label>语言</label>
            <a-select
              v-model:value="newDatabase.language"
              :options="languageOptions"
              style="width: 100%"
              size="large"
              :dropdown-match-select-width="false"
            />
          </div>
          <div class="form-item half">
            <label>语言模型 (LLM)</label>
            <ModelSelectorComponent
              :model_spec="llmModelSpec"
              placeholder="请选择模型"
              @select-model="handleLLMSelect"
              size="large"
              style="width: 100%"
            />
          </div>
        </div>
        <p class="helper-text">可以在设置中配置更多语言模型</p>
      </div>

      <div class="form-section">
        <h3 class="section-title">知识库描述</h3>
        <p class="helper-text">
          在智能体流程中，这里的描述会作为工具的描述。智能体会根据知识库的标题和描述来选择合适的工具。详细的描述有助于智能体更精准地调用。
        </p>
        <AiTextarea
          v-model="newDatabase.description"
          :name="newDatabase.name"
          placeholder="请输入知识库描述..."
          :auto-size="{ minRows: 3, maxRows: 10 }"
        />
      </div>

      <!-- 共享配置 -->
      <div class="form-section">
        <h3 class="section-title">权限设置</h3>
        <div class="share-config-wrapper">
          <ShareConfigForm v-model="shareConfig" :auto-select-user-dept="true" />
        </div>
      </div>

      <template #footer>
        <div class="modal-footer">
          <a-button key="back" @click="cancelCreateDatabase" size="large">取消</a-button>
          <a-button
            key="submit"
            type="primary"
            :loading="dbState.creating"
            @click="handleCreateDatabase"
            size="large"
            >创建知识库</a-button
          >
        </div>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useConfigStore } from '@/stores/config'
import { useDatabaseStore } from '@/stores/database'
import {
  LockOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  DatabaseOutlined,
  CheckCircleFilled
} from '@ant-design/icons-vue'
import { typeApi } from '@/apis/knowledge_api'
import HeaderComponent from '@/components/HeaderComponent.vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import EmbeddingModelSelector from '@/components/EmbeddingModelSelector.vue'
import ShareConfigForm from '@/components/ShareConfigForm.vue'
import dayjs, { parseToShanghai } from '@/utils/time'
import AiTextarea from '@/components/AiTextarea.vue'
import { getKbTypeLabel, getKbTypeIcon, getKbTypeColor } from '@/utils/kb_utils'

const route = useRoute()
const router = useRouter()
const configStore = useConfigStore()
const databaseStore = useDatabaseStore()

// 使用 store 的状态
const { databases, state: dbState } = storeToRefs(databaseStore)

const state = reactive({
  openNewDatabaseModel: false
})

// 共享配置状态（用于提交数据）
const shareConfig = ref({
  is_shared: true,
  accessible_department_ids: []
})

// 语言选项（值使用英文，以保证后端/LightRAG 兼容；标签为中英文方便理解）
const languageOptions = [
  { label: '中文 Chinese', value: 'Chinese' },
  { label: '英语 English', value: 'English' },
  { label: '日语 Japanese', value: 'Japanese' },
  { label: '韩语 Korean', value: 'Korean' },
  { label: '德语 German', value: 'German' },
  { label: '法语 French', value: 'French' },
  { label: '西班牙语 Spanish', value: 'Spanish' },
  { label: '葡萄牙语 Portuguese', value: 'Portuguese' },
  { label: '俄语 Russian', value: 'Russian' },
  { label: '阿拉伯语 Arabic', value: 'Arabic' },
  { label: '印地语 Hindi', value: 'Hindi' }
]

const createEmptyDatabaseForm = () => ({
  name: '',
  description: '',
  embed_model_name: configStore.config?.embed_model,
  kb_type: 'milvus',
  is_private: false,
  storage: '',
  language: 'Chinese',
  llm_info: {
    provider: '',
    model_name: ''
  }
})

const newDatabase = reactive(createEmptyDatabaseForm())

const llmModelSpec = computed(() => {
  const provider = newDatabase.llm_info?.provider || ''
  const modelName = newDatabase.llm_info?.model_name || ''
  if (provider && modelName) {
    return `${provider}/${modelName}`
  }
  return ''
})

// 支持的知识库类型
const supportedKbTypes = ref({})

// 有序的知识库类型
const orderedKbTypes = computed(() => supportedKbTypes.value)

// 加载支持的知识库类型
const loadSupportedKbTypes = async () => {
  try {
    const data = await typeApi.getKnowledgeBaseTypes()
    supportedKbTypes.value = data.kb_types
    console.log('支持的知识库类型:', supportedKbTypes.value)
  } catch (error) {
    console.error('加载知识库类型失败:', error)
    // 如果加载失败，设置默认类型
    supportedKbTypes.value = {
      lightrag: {
        description: '基于图检索的知识库，支持实体关系构建和复杂查询',
        class_name: 'LightRagKB'
      }
    }
  }
}

// 重排序模型信息现在直接从 configStore.config.reranker_names 获取，无需单独加载

const resetNewDatabase = () => {
  Object.assign(newDatabase, createEmptyDatabaseForm())
  // 重置共享配置
  shareConfig.value = {
    is_shared: true,
    accessible_department_ids: []
  }
}

const cancelCreateDatabase = () => {
  state.openNewDatabaseModel = false
  resetNewDatabase()
}

// 格式化创建时间
const formatCreatedTime = (createdAt) => {
  if (!createdAt) return ''
  const parsed = parseToShanghai(createdAt)
  if (!parsed) return ''

  const today = dayjs().startOf('day')
  const createdDay = parsed.startOf('day')
  const diffInDays = today.diff(createdDay, 'day')

  if (diffInDays === 0) {
    return '今天'
  }
  if (diffInDays === 1) {
    return '昨天'
  }
  if (diffInDays < 7) {
    return `${diffInDays}天前`
  }
  return parsed.format('YYYY-MM-DD')
}

// 处理知识库类型改变
const handleKbTypeChange = (type) => {
  console.log('知识库类型改变:', type)
  resetNewDatabase()
  newDatabase.kb_type = type
}

// 处理LLM选择
const handleLLMSelect = (spec) => {
  console.log('LLM选择:', spec)
  if (typeof spec !== 'string' || !spec) return

  const index = spec.indexOf('/')
  const provider = index !== -1 ? spec.slice(0, index) : ''
  const modelName = index !== -1 ? spec.slice(index + 1) : ''

  newDatabase.llm_info.provider = provider
  newDatabase.llm_info.model_name = modelName
}

// 构建请求数据（只负责表单数据转换）
const buildRequestData = () => {
  const requestData = {
    database_name: newDatabase.name.trim(),
    description: newDatabase.description?.trim() || '',
    embed_model_name: newDatabase.embed_model_name || configStore.config.embed_model,
    kb_type: newDatabase.kb_type,
    additional_params: {
      is_private: newDatabase.is_private || false
    }
  }

  // 添加共享配置
  requestData.share_config = {
    is_shared: shareConfig.value.is_shared,
    accessible_departments: shareConfig.value.is_shared
      ? []
      : shareConfig.value.accessible_department_ids || []
  }

  // 根据类型添加特定配置
  if (['milvus'].includes(newDatabase.kb_type)) {
    if (newDatabase.storage) {
      requestData.additional_params.storage = newDatabase.storage
    }
  }

  if (newDatabase.kb_type === 'lightrag') {
    requestData.additional_params.language = newDatabase.language || 'English'
    if (newDatabase.llm_info.provider && newDatabase.llm_info.model_name) {
      requestData.llm_info = {
        provider: newDatabase.llm_info.provider,
        model_name: newDatabase.llm_info.model_name
      }
    }
  }

  return requestData
}

// 创建按钮处理
const handleCreateDatabase = async () => {
  const requestData = buildRequestData()
  try {
    await databaseStore.createDatabase(requestData)
    resetNewDatabase()
    state.openNewDatabaseModel = false
  } catch (error) {
    // 错误已在 store 中处理
  }
}

const navigateToDatabase = (databaseId) => {
  router.push({ path: `/database/${databaseId}` })
}

watch(
  () => route.path,
  (newPath) => {
    if (newPath === '/database') {
      databaseStore.loadDatabases()
    }
  }
)

onMounted(() => {
  loadSupportedKbTypes()
  databaseStore.loadDatabases()
})
</script>

<style lang="less" scoped>
.database-container {
  padding: 24px;
  height: 100%;
  overflow: hidden;

  .glass-panel {
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 24px;
  }
}

.databases-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
  padding: 4px; // Prevent shadow clipping
  overflow-y: auto;
  padding-bottom: 24px;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    background-color: var(--gray-200);
    border-radius: 3px;
  }
}

.database-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 16px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  position: relative;
  display: flex;
  flex-direction: column;
  height: 180px;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 24px -8px var(--shadow-color-lg);
    border-color: var(--primary-200);

    .icon-wrapper {
      transform: scale(1.05);
      background: var(--primary-50);
      color: var(--primary-600);
    }
  }

  .private-badge {
    position: absolute;
    top: 16px;
    right: 16px;
    color: var(--warning-500);
    background: var(--warning-50);
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    font-size: 14px;
  }

  .card-content {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .card-header-row {
    display: flex;
    align-items: flex-start;
    margin-bottom: 16px;

    .icon-wrapper {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: var(--gray-50);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      color: var(--primary-500);
      margin-right: 16px;
      transition: all 0.3s ease;
      flex-shrink: 0;
    }

    .header-info {
      flex: 1;
      min-width: 0;
      padding-top: 2px;

      .title {
        font-size: 16px;
        font-weight: 600;
        color: var(--gray-900);
        margin: 0 0 6px 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .meta-info {
        display: flex;
        align-items: center;
        color: var(--gray-500);
        font-size: 12px;

        .separator {
          margin: 0 6px;
          color: var(--gray-300);
        }
      }
    }
  }

  .description {
    color: var(--gray-600);
    font-size: 14px;
    line-height: 1.5;
    margin: 0 0 auto 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .tags-row {
    margin-top: 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;

    .custom-tag {
      margin: 0;
      border: none;
      background: var(--gray-100);
      color: var(--gray-600);
      border-radius: 6px;
      padding: 2px 8px;
      font-size: 12px;

      &.kb-type-tag {
        background: var(--primary-50);
        color: var(--primary-600);
        font-weight: 500;
      }
    }
  }
}

.loading-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: var(--gray-500);
  gap: 16px;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;

  .empty-icon-wrapper {
    width: 80px;
    height: 80px;
    background: var(--gray-50);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 24px;

    .empty-icon {
      font-size: 40px;
      color: var(--gray-400);
    }
  }

  .empty-title {
    font-size: 20px;
    font-weight: 600;
    color: var(--gray-900);
    margin: 0 0 12px 0;
  }

  .empty-description {
    font-size: 14px;
    color: var(--gray-500);
    margin: 0 0 32px 0;
    max-width: 400px;
  }
}

// Modal Styles
.form-section {
  margin-bottom: 24px;

  .section-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--gray-900);
    margin: 0 0 16px 0;
    display: flex;
    align-items: center;

    .required {
      color: var(--error-500);
      margin-left: 4px;
    }
  }

  .helper-text {
    font-size: 13px;
    color: var(--gray-500);
    margin: 8px 0 0 0;
    line-height: 1.5;
  }
}

.form-item {
  margin-bottom: 16px;

  label {
    display: block;
    margin-bottom: 8px;
    font-size: 14px;
    font-weight: 500;
    color: var(--gray-700);

    .required {
      color: var(--error-500);
      margin-left: 4px;
    }
  }

  &.half {
    flex: 1;
  }
}

.form-row {
  display: flex;
  gap: 20px;
}

.kb-type-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;

  @media (max-width: 768px) {
    grid-template-columns: 1fr;
  }

  .kb-type-card {
    border: 2px solid var(--gray-100);
    border-radius: 12px;
    padding: 16px;
    cursor: pointer;
    transition: all 0.3s ease;
    background: var(--gray-0);
    position: relative;

    &:hover {
      border-color: var(--primary-300);
      transform: translateY(-2px);
    }

    &.active {
      border-color: var(--primary-500);
      background: var(--primary-50);

      .type-icon {
        color: var(--primary-600);
      }

      .type-title {
        color: var(--primary-700);
      }
    }

    .card-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;

      .type-icon {
        font-size: 20px;
        color: var(--gray-400);
        transition: color 0.3s;
      }

      .type-title {
        font-weight: 600;
        color: var(--gray-800);
        font-size: 15px;
      }
    }

    .card-description {
      font-size: 12px;
      color: var(--gray-600);
      line-height: 1.5;
      min-height: 36px;
    }

    .selection-indicator {
      position: absolute;
      top: 10px;
      right: 10px;
      color: var(--primary-500);
      font-size: 16px;
    }
  }
}

.share-config-wrapper {
  background: var(--gray-50);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--gray-100);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

:deep(.ant-input),
:deep(.ant-select-selector) {
  border-radius: 8px !important;
}

:deep(.ant-modal-content) {
  border-radius: 16px;
  overflow: hidden;
}

:deep(.ant-modal-header) {
  margin-bottom: 20px;
}
</style>
