<template>
  <div class="agent-config-sidebar" :class="{ open: isOpen }">
    <!-- 侧边栏头部 -->
    <div class="sidebar-header">
      <div class="header-center">
        <a-segmented v-model:value="activeTab" :options="segmentedOptions" />
      </div>
      <a-button type="text" size="small" @click="closeSidebar" class="close-btn">
        <X :size="16" />
      </a-button>
    </div>

    <!-- 侧边栏内容 -->
    <div class="sidebar-content">
      <div class="agent-info" v-if="selectedAgent">
        <div class="agent-basic-info">
          <p class="agent-description">{{ selectedAgent.description }}</p>
        </div>

        <!-- <a-divider /> -->

        <div v-if="selectedAgentId && configurableItems" class="config-form-content">
          <!-- 配置表单 -->
          <a-form :model="agentConfig" layout="vertical" class="config-form">
            <a-alert
              v-if="isEmptyConfig"
              type="warning"
              message="该智能体没有配置项"
              show-icon
              class="config-alert"
            />
            <a-alert
              v-if="!selectedAgent.has_checkpointer"
              type="error"
              message="该智能体没有配置 Checkpointer，功能无法正常使用"
              show-icon
              class="config-alert"
            />

            <!-- 统一显示所有配置项 -->
            <template v-for="(value, key) in configurableItems" :key="key">
              <a-form-item
                v-if="shouldShowConfig(key, value)"
                :label="getConfigLabel(key, value)"
                :name="key"
                class="config-item"
              >
                <p v-if="value.description" class="config-description">{{ value.description }}</p>

                <!-- <div>{{ value }}</div> -->
                <!-- 模型选择 -->
                <div v-if="value.template_metadata.kind === 'llm'" class="model-selector">
                  <ModelSelectorComponent
                    @select-model="(spec) => handleModelChange(key, spec)"
                    :model_spec="agentConfig[key] || ''"
                  />
                </div>

                <!-- 系统提示词 -->
                <div
                  v-else-if="value.template_metadata.kind === 'prompt'"
                  class="system-prompt-container"
                >
                  <!-- 编辑模式 -->
                  <div class="prompt-edit-wrapper" v-if="systemPromptEditMode">
                    <a-textarea
                      :value="agentConfig[key]"
                      @update:value="(val) => agentStore.updateAgentConfig({ [key]: val })"
                      :rows="10"
                      :placeholder="getPlaceholder(key, value)"
                      class="system-prompt-input"
                      @blur="handlePromptBlur"
                      ref="systemPromptTextarea"
                    />
                    <a-button
                      type="link"
                      size="small"
                      class="optimize-prompt-btn"
                      :loading="optimizingPrompt"
                      @click.stop="optimizePrompt(key)"
                      :disabled="!agentConfig[key]?.trim()"
                    >
                      <Sparkles :size="14" />
                      优化
                    </a-button>
                  </div>
                  <!-- 显示模式 -->
                  <div v-else class="system-prompt-display" @click="enterEditMode">
                    <div
                      class="system-prompt-content"
                      :class="{ 'is-placeholder': !agentConfig[key] }"
                    >
                      {{ agentConfig[key] || getPlaceholder(key, value) }}
                    </div>
                    <div class="edit-hint">点击编辑</div>
                  </div>
                </div>

                <!-- 工具选择 -->
                <!-- <div v-else-if="value.template_metadata.kind === 'tools'" class="tools-selector">
                  <div class="tools-summary">
                    <div class="tools-summary-info">
                      <span class="tools-count">已选择 {{ getSelectedCount(key) }} 个工具</span>
                      <a-button
                        type="link"
                        size="small"
                        @click="clearSelection(key)"
                        v-if="getSelectedCount(key) > 0"
                        class="clear-btn"
                      >
                        清空
                      </a-button>
                    </div>
                    <a-button
                      type="primary"
                      @click="openToolsModal"
                      class="select-tools-btn"
                      size="small"
                    >
                      选择工具
                    </a-button>
                  </div>
                  <div v-if="getSelectedCount(key) > 0" class="selected-tools-preview">
                    <a-tag
                      v-for="toolId in agentConfig[key]"
                      :key="toolId"
                      closable
                      @close="removeSelectedTool(toolId)"
                      class="tool-tag"
                    >
                      {{ getToolNameById(toolId) }}
                    </a-tag>
                  </div>
                </div> -->

                <!-- 数据源选择 -->
                <a-select
                  v-else-if="value.template_metadata.kind === 'datasource'"
                  :value="agentConfig[key]"
                  @update:value="(val) => agentStore.updateAgentConfig({ [key]: val })"
                  placeholder="请选择数据源连接"
                  allow-clear
                  class="config-select"
                >
                  <a-select-option
                    v-for="conn in datasourceConnections"
                    :key="conn.id"
                    :value="conn.id"
                  >
                    {{ conn.name }} ({{ conn.db_type }})
                  </a-select-option>
                </a-select>

                <!-- 子智能体编辑器 -->
                <SubagentEditor
                  v-else-if="value.template_metadata.kind === 'subagents'"
                  :modelValue="agentConfig[key] || []"
                  @update:modelValue="(val) => agentStore.updateAgentConfig({ [key]: val })"
                />

                <!-- 布尔类型 -->
                <a-switch
                  v-else-if="isBooleanConfig(value)"
                  :checked="coerceBoolean(agentConfig[key], value.default)"
                  @update:checked="(val) => updateTypedConfigValue(key, val, value)"
                />

                <!-- 单选 -->
                <a-select
                  v-else-if="
                    value?.options.length > 0 && (value?.type === 'str' || value?.type === 'select')
                  "
                  :value="agentConfig[key]"
                  @update:value="(val) => agentStore.updateAgentConfig({ [key]: val })"
                  class="config-select"
                >
                  <a-select-option v-for="option in value.options" :key="option" :value="option">
                    {{ option.label || option }}
                  </a-select-option>
                </a-select>

                <!-- 多选 / 工具列表 (统一处理) -->
                <div v-else-if="isListConfig(key, value)" class="list-config-container">
                  <!-- Case 1: <= 5 options, inline list -->
                  <div v-if="getConfigOptions(value).length <= 5" class="multi-select-cards">
                    <div class="multi-select-label">
                      <span>已选择 {{ getSelectedCount(key) }} 项</span>
                      <a-button
                        type="link"
                        size="small"
                        class="clear-btn"
                        @click="clearSelection(key)"
                        v-if="getSelectedCount(key) > 0"
                      >
                        清空
                      </a-button>
                    </div>
                    <div class="options-grid">
                      <div
                        v-for="option in getConfigOptions(value)"
                        :key="getOptionValue(option)"
                        class="option-card"
                        :class="{
                          selected: isOptionSelected(key, getOptionValue(option)),
                          unselected: !isOptionSelected(key, getOptionValue(option))
                        }"
                        @click="toggleOption(key, getOptionValue(option))"
                      >
                        <div class="option-content">
                          <span class="option-text">{{ getOptionLabel(option) }}</span>
                          <div class="option-indicator">
                            <Check
                              v-if="isOptionSelected(key, getOptionValue(option))"
                              :size="16"
                            />
                            <Plus v-else :size="16" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- Case 2: > 5 options, Modal trigger -->

                  <div v-else class="selection-container">
                    <div class="selection-summary">
                      <div class="selection-summary-info">
                        <span class="selection-count">已选择 {{ getSelectedCount(key) }} 项</span>

                        <a-button
                          type="link"
                          size="small"
                          class="clear-btn"
                          @click="clearSelection(key)"
                          v-if="getSelectedCount(key) > 0"
                        >
                          清空
                        </a-button>
                      </div>

                      <a-button
                        type="primary"
                        size="small"
                        class="selection-trigger-btn"
                        @click="openSelectionModal(key)"
                      >
                        选择...
                      </a-button>
                    </div>

                    <!-- Selected Preview Tags -->

                    <div v-if="getSelectedCount(key) > 0" class="selection-preview">
                      <a-tag
                        v-for="val in agentConfig[key]"
                        :key="val"
                        closable
                        @close="toggleOption(key, val)"
                        class="selection-tag"
                      >
                        {{ getOptionLabelFromValue(key, val) }}
                      </a-tag>
                    </div>
                  </div>
                </div>

                <!-- 数字 -->
                <a-input-number
                  v-else-if="isNumericConfig(value)"
                  :value="coerceNumber(agentConfig[key], value.default)"
                  @update:value="(val) => updateTypedConfigValue(key, val, value)"
                  :placeholder="getPlaceholder(key, value)"
                  class="config-input-number"
                />

                <!-- 滑块 -->
                <a-slider
                  v-else-if="value?.type === 'slider'"
                  :value="agentConfig[key]"
                  @update:value="(val) => agentStore.updateAgentConfig({ [key]: val })"
                  :min="value.min"
                  :max="value.max"
                  :step="value.step"
                  class="config-slider"
                />

                <!-- 其他类型 -->
                <a-input
                  v-else
                  :value="agentConfig[key]"
                  @update:value="(val) => agentStore.updateAgentConfig({ [key]: val })"
                  :placeholder="getPlaceholder(key, value)"
                  class="config-input"
                />
              </a-form-item>
            </template>
          </a-form>
        </div>
      </div>
    </div>

    <!-- 固定在底部的操作按钮 -->
    <div class="sidebar-footer" v-if="!isEmptyConfig && userStore.isAdmin">
      <div class="form-actions">
        <a-button
          type="primary"
          @click="saveConfig"
          class="save-btn"
          :class="{ changed: agentStore.hasConfigChanges }"
          :disabled="isSavingConfig"
        >
          保存
        </a-button>
      </div>
    </div>

    <!-- 通用选择弹窗 -->

    <a-modal
      v-model:open="selectionModalOpen"
      :title="`选择${configurableItems[currentConfigKey]?.name || '项目'}`"
      :width="800"
      :footer="null"
      :maskClosable="false"
      class="selection-modal"
    >
      <div class="selection-modal-content">
        <div class="selection-search">
          <a-input
            v-model:value="selectionSearchText"
            placeholder="搜索..."
            allow-clear
            class="search-input"
          >
            <template #prefix>
              <Search :size="16" class="search-icon" />
            </template>
          </a-input>
        </div>

        <div class="selection-list">
          <div
            v-for="option in filteredOptions"
            :key="getOptionValue(option)"
            class="selection-item"
            :class="{ selected: tempSelectedValues.includes(getOptionValue(option)) }"
            @click="toggleModalSelection(getOptionValue(option))"
          >
            <div class="selection-item-content">
              <div class="selection-item-header">
                <span class="selection-item-name">{{ getOptionLabel(option) }}</span>

                <div class="selection-item-indicator">
                  <Check v-if="tempSelectedValues.includes(getOptionValue(option))" :size="16" />

                  <Plus v-else :size="16" />
                </div>
              </div>

              <div v-if="getOptionDescription(option)" class="selection-item-description">
                {{ getOptionDescription(option) }}
              </div>
            </div>
          </div>
        </div>

        <div class="selection-modal-footer">
          <div class="selected-count">已选择 {{ tempSelectedValues.length }} 项</div>

          <div class="modal-actions">
            <a-button @click="closeSelectionModal">取消</a-button>

            <a-button type="primary" @click="confirmSelection">确认</a-button>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { message } from 'ant-design-vue'
import { X, Check, Plus, Search, Sparkles } from 'lucide-vue-next'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import SubagentEditor from '@/components/SubagentEditor.vue'
import { agentApi } from '@/apis/agent_api'
import { useAgentStore } from '@/stores/agent'
import { useUserStore } from '@/stores/user'
import { useDatabaseStore } from '@/stores/database'
import { getConnections, listReporterSkills } from '@/apis/text2sql_api'
import { storeToRefs } from 'pinia'

// Props
const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  }
})

// Emits
const emit = defineEmits(['close'])

// Store 管理
const agentStore = useAgentStore()
const userStore = useUserStore()
const databaseStore = useDatabaseStore()

const datasourceConnections = ref([])
const reporterSkills = ref([])

watch(
  () => props.isOpen,
  (val) => {
    if (val) {
      databaseStore.loadDatabases().catch(() => {})
      getConnections()
        .then((res) => {
          datasourceConnections.value = res.data || []
        })
        .catch(() => {})
    }
  }
)

const {
  availableTools,
  selectedAgent,
  selectedAgentId,
  agentConfig,
  configurableItems
} = storeToRefs(agentStore)

// console.log(availableTools.value)

// 本地状态
const selectionModalOpen = ref(false)
const currentConfigKey = ref(null)
const tempSelectedValues = ref([])
const selectionSearchText = ref('')
const systemPromptEditMode = ref(false)
const optimizingPrompt = ref(false)
const activeTab = ref('basic')

const isEmptyConfig = computed(() => {
  return !selectedAgentId.value || Object.keys(configurableItems.value).length === 0
})

const isSavingConfig = ref(false)

const hasOtherConfigs = computed(() => {
  if (isEmptyConfig.value) return false
  return Object.entries(configurableItems.value).some(([, value]) => {
    const isBasic =
      value.template_metadata?.kind === 'prompt' || value.template_metadata?.kind === 'llm'
    const isTools =
      value.template_metadata?.kind === 'mcps' ||
      value.template_metadata?.kind === 'knowledges' ||
      value.template_metadata?.kind === 'tools' ||
      value.template_metadata?.kind === 'datasource'

    return !isBasic && !isTools
  })
})

const segmentedOptions = computed(() => {
  const options = [
    { label: '基础', value: 'basic' },
    { label: '工具', value: 'tools' }
  ]

  if (hasOtherConfigs.value) {
    options.push({ label: '其他', value: 'other' })
  }

  return options
})

// 通用选项获取与处理
const getConfigOptions = (value) => {
  if (value?.template_metadata?.kind === 'tools') {
    return availableTools.value ? Object.values(availableTools.value) : []
  }
  if (value?.template_metadata?.kind === 'knowledges') {
    return databaseStore.databases || []
  }
  if (value?.template_metadata?.kind === 'skills') {
    const inlineOptions = Array.isArray(value?.options) ? value.options : []
    if (inlineOptions.length > 0) {
      return inlineOptions
    }
    return reporterSkills.value || []
  }
  return value?.options || []
}

const isListConfig = (key, value) => {
  const isTools = value?.template_metadata?.kind === 'tools'
  const isList = value?.type === 'list'
  return isTools || isList
}

const isBooleanConfig = (value) => {
  return value?.type === 'bool' || typeof value?.default === 'boolean'
}

const isNumericConfig = (value) => {
  return ['number', 'int', 'integer', 'float'].includes(value?.type)
}

const coerceBoolean = (val, fallback = false) => {
  if (typeof val === 'boolean') return val
  if (typeof val === 'string') {
    const normalized = val.trim().toLowerCase()
    if (['1', 'true', 'yes', 'on'].includes(normalized)) return true
    if (['0', 'false', 'no', 'off', ''].includes(normalized)) return false
  }
  return Boolean(fallback)
}

const coerceNumber = (val, fallback = 0) => {
  if (typeof val === 'number' && Number.isFinite(val)) return val
  const parsed = Number(val)
  if (Number.isFinite(parsed)) return parsed
  const fallbackParsed = Number(fallback)
  return Number.isFinite(fallbackParsed) ? fallbackParsed : 0
}

const updateTypedConfigValue = (key, val, configItem) => {
  if (isBooleanConfig(configItem)) {
    agentStore.updateAgentConfig({
      [key]: coerceBoolean(val, configItem?.default)
    })
    return
  }
  if (isNumericConfig(configItem)) {
    const numericValue = coerceNumber(val, configItem?.default)
    const normalizedValue =
      configItem?.type === 'int' || configItem?.type === 'integer'
        ? Math.trunc(numericValue)
        : numericValue
    agentStore.updateAgentConfig({
      [key]: normalizedValue
    })
    return
  }
  agentStore.updateAgentConfig({
    [key]: val
  })
}

const getOptionValue = (option) => {
  if (typeof option === 'object' && option !== null) {
    return option.id || option.value || option.name
  }
  return option
}

const getOptionLabel = (option) => {
  if (typeof option === 'object' && option !== null) {
    return option.name || option.label || option.id
  }
  return option
}

const getOptionDescription = (option) => {
  if (typeof option === 'object' && option !== null) {
    return option.description || '暂无描述'
  }
  return null
}

const filteredOptions = computed(() => {
  if (!currentConfigKey.value) return []
  const key = currentConfigKey.value
  const configItem = configurableItems.value[key]
  const options = getConfigOptions(configItem)

  if (!selectionSearchText.value) return options

  const search = selectionSearchText.value.toLowerCase()
  return options.filter((opt) => {
    const label = String(getOptionLabel(opt)).toLowerCase()
    const desc = String(getOptionDescription(opt) || '').toLowerCase()
    return label.includes(search) || desc.includes(search)
  })
})

// 方法
const shouldShowConfig = (key, value) => {
  const isBasic =
    value.template_metadata?.kind === 'prompt' || value.template_metadata?.kind === 'llm'
  const isTools =
    value.template_metadata?.kind === 'mcps' ||
    value.template_metadata?.kind === 'knowledges' ||
    value.template_metadata?.kind === 'tools' ||
    value.template_metadata?.kind === 'datasource' ||
    value.template_metadata?.kind === 'skills'

  if (activeTab.value === 'basic') {
    // 基础：System Prompt, LLM Model
    return isBasic
  } else if (activeTab.value === 'tools') {
    // 工具：Tools, MCPs, Knowledges, Datasource
    return isTools
  } else {
    // 其他：剩余所有配置
    return !isBasic && !isTools
  }
}

const closeSidebar = () => {
  emit('close')
}

const getConfigLabel = (key, value) => {
  // console.log(configurableItems)
  if (value.description && value.name !== key) {
    return `${value.name}`
    // return `${value.name}（${key}）`;
  }
  return key
}

const getPlaceholder = (key, value) => {
  return `（默认: ${value.default}）`
}

const handleModelChange = (key, spec) => {
  if (typeof spec !== 'string' || !spec) return
  agentStore.updateAgentConfig({
    [key]: spec
  })
}

// 多选相关方法
const ensureArray = (key) => {
  const config = agentConfig.value || {}
  if (!config[key] || !Array.isArray(config[key])) {
    return []
  }
  return config[key]
}

const isOptionSelected = (key, option) => {
  const currentOptions = ensureArray(key)
  return currentOptions.includes(option)
}

const getSelectedCount = (key) => {
  const currentOptions = ensureArray(key)
  return currentOptions.length
}

const toggleOption = (key, option) => {
  const currentOptions = [...ensureArray(key)]
  const index = currentOptions.indexOf(option)

  if (index > -1) {
    currentOptions.splice(index, 1)
  } else {
    currentOptions.push(option)
  }

  agentStore.updateAgentConfig({
    [key]: currentOptions
  })
}

const clearSelection = (key) => {
  agentStore.updateAgentConfig({
    [key]: []
  })
}

// 统一选择弹窗相关方法
const getOptionLabelFromValue = (key, val) => {
  const options = getConfigOptions(configurableItems.value[key])
  const option = options.find((opt) => getOptionValue(opt) === val)
  return option ? getOptionLabel(option) : val
}

const openSelectionModal = async (key) => {
  currentConfigKey.value = key
  // 如果是工具，可能需要刷新
  if (configurableItems.value[key]?.template_metadata?.kind === 'tools' && selectedAgentId.value) {
    try {
      await agentStore.fetchAgentDetail(selectedAgentId.value, true)
    } catch (error) {
      console.error('刷新工具列表失败:', error)
    }
  }
  // 如果是知识库，需要获取知识库列表
  if (configurableItems.value[key]?.template_metadata?.kind === 'knowledges') {
    try {
      await databaseStore.loadDatabases()
    } catch (error) {
      console.error('加载知识库列表失败:', error)
    }
  }
  if (configurableItems.value[key]?.template_metadata?.kind === 'skills') {
    const inlineOptions = Array.isArray(configurableItems.value[key]?.options)
      ? configurableItems.value[key].options
      : []
    if (inlineOptions.length === 0) {
      const connectionId = agentConfig.value?.db_connection_id
      if (!connectionId) {
        message.warning('请先选择数据源，再选择技能')
        return
      }
      try {
        const res = await listReporterSkills(connectionId)
        const items = Array.isArray(res?.data) ? res.data : []
        reporterSkills.value = items
          .filter((item) => item.status === 'published')
          .map((item) => ({
            id: item.id,
            name: item.business_scenario ? `${item.business_scenario} (${item.id})` : item.id,
            description: `状态: ${item.status}；指标: ${(item.target_metrics || []).join('、') || '未设置'}`
          }))
      } catch (error) {
        console.error('加载技能列表失败:', error)
        message.error('加载技能列表失败')
        return
      }
    }
  }
  const currentValues = agentConfig.value[key] || []
  tempSelectedValues.value = [...currentValues]
  selectionModalOpen.value = true
}

const toggleModalSelection = (optionValue) => {
  const index = tempSelectedValues.value.indexOf(optionValue)
  if (index > -1) {
    tempSelectedValues.value.splice(index, 1)
  } else {
    tempSelectedValues.value.push(optionValue)
  }
}

const confirmSelection = () => {
  if (currentConfigKey.value) {
    agentStore.updateAgentConfig({
      [currentConfigKey.value]: [...tempSelectedValues.value]
    })
  }
  closeSelectionModal()
}

const closeSelectionModal = () => {
  selectionModalOpen.value = false
  currentConfigKey.value = null
  tempSelectedValues.value = []
  selectionSearchText.value = ''
}

// 系统提示词编辑相关方法
const enterEditMode = () => {
  systemPromptEditMode.value = true
  // 使用 nextTick 确保 DOM 更新后再聚焦
  nextTick(() => {
    const textarea = document.querySelector('.system-prompt-input')
    if (textarea) {
      textarea.focus()
    }
  })
}

const handlePromptBlur = (event) => {
  // 如果点击的是优化按钮，不要关闭编辑模式
  const relatedTarget = event.relatedTarget
  if (relatedTarget && relatedTarget.closest('.optimize-prompt-btn')) {
    return
  }
  systemPromptEditMode.value = false
}

const optimizePrompt = async (key) => {
  if (!agentConfig.value[key]?.trim()) return
  optimizingPrompt.value = true
  try {
    const res = await agentApi.optimizePrompt(agentConfig.value[key])
    if (res.optimized_prompt) {
      agentStore.updateAgentConfig({ [key]: res.optimized_prompt })
      message.success('提示词已优化')
    }
  } catch (e) {
    console.error('优化提示词失败:', e)
    message.error('优化失败，请稍后重试')
  } finally {
    optimizingPrompt.value = false
  }
}

// 验证和过滤配置项
const validateAndFilterConfig = () => {
  const validatedConfig = { ...agentConfig.value }
  const configItems = configurableItems.value

  // 遍历所有配置项
  Object.keys(configItems).forEach((key) => {
    const configItem = configItems[key]
    const currentValue = validatedConfig[key]

    // 检查工具配置
    if (configItem.template_metadata?.kind === 'tools' && Array.isArray(currentValue)) {
      const availableToolIds = availableTools.value
        ? Object.values(availableTools.value).map((tool) => tool.id)
        : []
      validatedConfig[key] = currentValue.filter((toolId) => availableToolIds.includes(toolId))

      if (validatedConfig[key].length !== currentValue.length) {
        console.warn(`工具配置 ${key} 中包含无效的工具ID，已自动过滤`)
      }
    }

    // 检查多选配置项 (type === 'list' 且有 options)
    else if (
      configItem.type === 'list' &&
      configItem.options.length > 0 &&
      Array.isArray(currentValue)
    ) {
      const validOptions = configItem.options
      validatedConfig[key] = currentValue.filter((value) => validOptions.includes(value))

      if (validatedConfig[key].length !== currentValue.length) {
        console.warn(`配置项 ${key} 中包含无效的选项，已自动过滤`)
      }
    } else if (isBooleanConfig(configItem)) {
      validatedConfig[key] = coerceBoolean(currentValue, configItem.default)
    } else if (isNumericConfig(configItem)) {
      const numericValue = coerceNumber(currentValue, configItem.default)
      validatedConfig[key] =
        configItem.type === 'int' || configItem.type === 'integer'
          ? Math.trunc(numericValue)
          : numericValue
    }
  })

  return validatedConfig
}

// 配置保存和重置
const saveConfig = async () => {
  if (!selectedAgentId.value) {
    message.error('没有选择智能体')
    return
  }

  if (!agentStore.hasConfigChanges) return

  try {
    isSavingConfig.value = true
    // 验证和过滤配置
    const validatedConfig = validateAndFilterConfig()

    // 如果配置有变化，先更新到store
    if (JSON.stringify(validatedConfig) !== JSON.stringify(agentConfig.value)) {
      agentStore.updateAgentConfig(validatedConfig)
      message.info('检测到无效配置项，已自动过滤')
    }

    await agentStore.saveAgentConfig()
    message.success('配置已保存到服务器')
  } catch (error) {
    console.error('保存配置到服务器出错:', error)
    message.error('保存配置到服务器失败')
  } finally {
    isSavingConfig.value = false
  }
}

</script>

<style lang="less" scoped>
@padding-bottom: 0px;
.agent-config-sidebar {
  position: relative;
  width: 0;
  height: 100vh;
  background: var(--gray-0);
  border-left: 1px solid var(--gray-200);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;

  &.open {
    width: 400px;
  }

  .sidebar-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 20px;
    border-bottom: 1px solid var(--gray-150);
    background: var(--gray-0);
    flex-shrink: 0;
    min-width: 400px;
    height: var(--header-height);

    .header-center {
      flex: 1;
      display: flex;
      justify-content: center;
    }

    .close-btn {
      color: var(--gray-600);
      border: none;
      padding: 4px;

      &:hover {
        color: var(--gray-900);
        background: var(--gray-100);
      }
    }
  }

  .sidebar-content {
    flex: 1;
    overflow-y: auto;
    padding: 8px 12px;
    min-width: 400px;
    padding-bottom: @padding-bottom;

    .agent-info {
      .agent-basic-info {
        .agent-description {
          margin: 0 0 12px 0;
          font-size: 14px;
          color: var(--gray-700);
          line-height: 1.5;
        }
      }
    }

    .config-form-content {
      margin-bottom: 20px;
      .config-form {
        .config-alert {
          margin-bottom: 16px;
        }

        .config-item {
          background-color: var(--gray-25);
          padding: 12px;
          border-radius: 8px;
          border: 1px solid var(--gray-100);
          // box-shadow: 0px 0px 2px var(--shadow-3);

          :deep(.ant-form-item-label > label) {
            font-weight: 600;
          }

          :deep(label.form_item_model) {
            font-weight: 600;
          }

          .config-description {
            margin: 4px 0 8px 0;
            font-size: 12px;
            color: var(--gray-600);
            line-height: 1.4;
          }

          .model-selector {
            width: 100%;
          }

          .system-prompt-input {
            resize: vertical;
            background: var(--gray-50);
            border: 1px solid var(--gray-200);
            padding: 6px 10px;
            font-size: 12px;

            &:focus {
              outline: none;
            }
          }

          .system-prompt-container {
            width: 100%;
          }

          .prompt-edit-wrapper {
            position: relative;
            width: 100%;

            .optimize-prompt-btn {
              position: absolute;
              right: 4px;
              bottom: 4px;
              display: flex;
              align-items: center;
              gap: 4px;
              font-size: 12px;
              color: var(--main-600);
              padding: 2px 8px;
              height: auto;
              background: var(--gray-0);
              border-radius: 4px;
              opacity: 0.9;

              &:hover:not(:disabled) {
                color: var(--main-700);
                opacity: 1;
              }

              &:disabled {
                color: var(--gray-400);
                cursor: not-allowed;
              }
            }
          }

          .system-prompt-display {
            min-height: 60px;
            border-radius: 6px;
            cursor: pointer;
            position: relative;
            transition: all 0.2s ease;

            &:hover {
              border-color: var(--main-color);
              background: var(--gray-25);

              .edit-hint {
                opacity: 1;
              }
            }

            .system-prompt-content {
              white-space: pre-wrap;
              word-break: break-word;
              line-height: 1.5;
              color: var(--gray-900);
              font-size: 12px;
              max-height: 500px;
              overflow: scroll;

              &.is-placeholder {
                color: var(--gray-400);
                font-style: italic;
              }

              &:empty::before {
                content: attr(data-placeholder);
                color: var(--gray-400);
              }
            }

            .edit-hint {
              position: absolute;
              top: -32px;
              right: 0px;
              font-size: 12px;
              color: var(--main-800);
              opacity: 0;
              transition: opacity 0.2s ease;
              background: var(--gray-0);
              padding: 2px 6px;
              border-radius: 4px;
            }
          }

          .config-select,
          .config-input,
          .config-input-number {
            width: 100%;
          }

          .config-slider {
            width: 100%;
          }
        }
      }
    }
  }

  .sidebar-footer {
    padding: 8px 12px;
    border-top: 1px solid var(--gray-100);
    background: var(--gray-0);
    // min-width: 400px;
    z-index: 10;
    flex-shrink: 0; // Ensure footer doesn't shrink

    .form-actions {
      display: flex;
      flex-direction: row;
      gap: 12px;
      justify-content: space-between;
      align-items: center;

      .icon-btn {
        width: 36px;
        height: 36px;
        border-radius: 6px;
        color: var(--gray-600);
        border: 1px solid var(--gray-200);
        background: var(--gray-0);
        display: flex;
        justify-content: center;
        align-items: center;

        &:hover:not(:disabled) {
          color: var(--main-600);
          border-color: var(--main-200);
          background: var(--main-10);
        }

        &.is-default {
          // color: var(--main-500);
          color: var(--color-warning-500);
        }

        &[danger]:hover:not(:disabled) {
          color: var(--error-600);
          border-color: var(--error-200);
          background: var(--error-10);
        }

        &:disabled {
          cursor: not-allowed;
          background: transparent;
          color: var(--gray-400);
          border-color: var(--gray-200);

          &.is-default {
            opacity: 1;
          }
        }
      }

      .save-btn {
        flex: 1;
        height: 36px;
        border-radius: 6px;
        font-weight: 500;
        font-size: 14px;
        background-color: var(--gray-100);
        border: 1px solid var(--gray-200);
        color: var(--gray-600);
        transition: all 0.2s ease;

        &.changed {
          background-color: var(--main-color);
          color: var(--gray-0);
          border-color: var(--main-color);
        }

        &:hover:not(:disabled) {
          opacity: 0.9;
        }

        &:disabled {
          cursor: not-allowed;
          background-color: var(--gray-100);
          border-color: var(--gray-200);
          color: var(--gray-400);
        }
      }
    }
  }
}

// 选择器样式
.selection-container {
  .selection-summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 10px;
    background: var(--gray-0);
    border-radius: 8px;
    border: 1px solid var(--gray-150);
    margin-bottom: 8px;

    .selection-summary-info {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--gray-900);

      .selection-count {
        color: var(--gray-900);
        font-weight: 500;
      }
    }

    .selection-trigger-btn {
      background: var(--main-color);
      border: none;
      border-radius: 4px;
      height: 28px;
      font-size: 12px;
      font-weight: 500;

      &:hover {
        background: var(--main-color);
        opacity: 0.9;
      }
    }
  }

  .selection-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;

    .selection-tag {
      margin: 0;
      padding: 4px 8px;
      border-radius: 8px;
      background: var(--gray-150);
      border: none;
      color: var(--gray-900);
      font-size: 12px;

      :deep(.anticon-close) {
        color: var(--gray-600);
        margin-left: 4px;

        &:hover {
          color: var(--gray-900);
        }
      }
    }
  }
}

// 多选卡片样式
.multi-select-cards {
  .multi-select-label {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    font-size: 12px;
    color: var(--gray-600);
  }

  .options-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .option-card {
    border: 1px solid var(--gray-300);
    border-radius: 8px;
    padding: 8px 12px;
    cursor: pointer;
    transition: all 0.2s ease;
    background: var(--gray-0);

    &:hover {
      border-color: var(--main-color);
    }

    &.selected {
      border-color: var(--main-color);
      background: var(--main-10);

      .option-indicator {
        color: var(--main-color);
      }

      .option-text {
        color: var(--main-color);
        font-weight: 500;
      }
    }

    &.unselected {
      .option-indicator {
        color: var(--gray-400);
      }

      .option-text {
        color: var(--gray-700);
      }
    }

    .option-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;

      .option-text {
        flex: 1;
        font-size: 13px;
        line-height: 1.4;
      }

      .option-indicator {
        flex-shrink: 0;
        font-size: 14px;
        display: flex;
        align-items: center;
      }
    }
  }
}

// 选择弹窗样式
.selection-modal {
  .selection-modal-content {
    .selection-search {
      margin-bottom: 16px;

      .search-input {
        border-radius: 8px;
        border: 1px solid var(--gray-300);
        height: 36px;
        font-size: 14px;
        transition: all 0.2s ease;
        background: var(--gray-0);

        .search-icon {
          color: var(--gray-500);
          font-size: 16px;
        }

        &:focus-within {
          border-color: var(--main-color);
          box-shadow: 0 0 0 2px rgba(var(--main-color-rgb), 0.1);

          .search-icon {
            color: var(--main-color);
          }
        }

        &:hover {
          border-color: var(--gray-400);
        }
      }
    }

    .selection-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      max-height: max(60vh, 800px);
      overflow-y: auto;
      border-radius: 8px;
      margin-bottom: 16px;

      // 在小屏幕下调整为单列布局
      @media (max-width: 480px) {
        grid-template-columns: 1fr;
      }

      &::-webkit-scrollbar {
        width: 6px;
      }

      &::-webkit-scrollbar-track {
        background: var(--gray-100);
        border-radius: 3px;
      }

      &::-webkit-scrollbar-thumb {
        background: var(--gray-400);
        border-radius: 3px;
      }

      &::-webkit-scrollbar-thumb:hover {
        background: var(--gray-500);
      }

      .selection-item {
        padding: 12px 16px;
        border-bottom: none;
        cursor: pointer;
        transition: all 0.2s ease;
        border-radius: 8px;
        margin-bottom: 4px;
        background: var(--gray-0);
        border: 1px solid var(--gray-200);

        &:hover {
          border-color: var(--gray-300);
          background: var(--gray-20);
        }
        .selection-item-content {
          .selection-item-header {
            display: flex;
            align-items: center;
            gap: 8px;

            .selection-item-name {
              font-size: 14px;
              font-weight: 500;
              color: var(--gray-900);
              line-height: 1.3;
              flex: 1;
            }

            .selection-item-indicator {
              color: var(--gray-400);
              font-size: 16px;
              transition: all 0.2s ease;
              flex-shrink: 0;
              display: flex;
              align-items: center;
            }
          }

          .selection-item-description {
            font-size: 12px;
            color: var(--gray-600);
            line-height: 1.4;
            margin-top: 6px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
          }
        }

        &.selected {
          background: var(--main-10);
          border-color: var(--main-color);

          .selection-item-content {
            .selection-item-name {
              color: var(--main-800);
            }
            .selection-item-indicator {
              color: var(--main-800);
            }
          }
          .selection-item-description {
            color: var(--gray-900);
          }
        }
      }
    }

    .selection-modal-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 16px;
      border-top: 1px solid var(--gray-200);

      .selected-count {
        font-size: 14px;
        color: var(--gray-700);
        font-weight: 500;
        padding: 6px 12px;
        background: var(--gray-50);
        border-radius: 8px;
        border: 1px solid var(--gray-200);
      }

      .modal-actions {
        display: flex;
        gap: 12px;

        :deep(.ant-btn) {
          border-radius: 8px;
          height: 36px;
          font-size: 14px;
          font-weight: 500;
          padding: 0 16px;
          transition: all 0.2s ease;

          &.ant-btn-default {
            border: 1px solid var(--gray-300);
            color: var(--gray-700);
            background: var(--gray-0);

            &:hover {
              border-color: var(--main-color);
              color: var(--main-color);
            }
          }

          &.ant-btn-primary {
            background: var(--main-color);
            border: none;
            color: var(--gray-0);

            &:hover {
              background: var(--main-color);
              opacity: 0.9;
            }
          }
        }
      }
    }
  }
}

.clear-btn {
  padding: 0;
  height: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--main-700);

  &:hover {
    color: var(--main-800);
  }
}

// 响应式适配
@media (max-width: 768px) {
  .agent-config-sidebar.open {
    width: 100%;
  }

  .sidebar-header,
  .sidebar-content {
    min-width: 100% !important;
  }
}
</style>
