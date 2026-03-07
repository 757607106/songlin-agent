<template>
  <div class="header-container">
    <div class="header-content">
      <div class="header-left" v-if="$slots.left">
        <slot name="left"></slot>
      </div>
      <div class="header-main">
        <div class="header-title-row">
          <h1 class="title">{{ title }}</h1>
          <div class="title-extras" v-if="$slots['behind-title']">
            <slot name="behind-title"></slot>
          </div>
        </div>
        <div class="header-description" v-if="description || $slots.description">
          <slot name="description">
            <p>{{ description }}</p>
          </slot>
        </div>
      </div>
      <div class="header-actions" v-if="$slots.actions || loading">
        <div v-if="loading" class="loading-indicator">
          <LoadingOutlined spin />
        </div>
        <slot name="actions"></slot>
      </div>
    </div>
  </div>
</template>

<script setup>
import { LoadingOutlined } from '@ant-design/icons-vue'

defineProps({
  title: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  },
  loading: {
    type: Boolean,
    default: false
  }
})
</script>

<style scoped lang="less">
.header-container {
  padding: 0 0 20px 0;
  width: 100%;
  position: relative;
  z-index: 10;

  // Sticky behavior handled by parent or specific views if needed
  // Removing global sticky to prevent issues inside glass panels
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-main {
  flex: 1;
  min-width: 0;

  .header-title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 4px;

    .title {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
      color: var(--gray-900);
      line-height: 1.3;
      letter-spacing: -0.02em;
    }

    .title-extras {
      display: flex;
      align-items: center;
    }
  }

  .header-description {
    color: var(--gray-500);
    font-size: 14px;
    line-height: 1.5;

    p {
      margin: 0;
    }
  }
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;

  .loading-indicator {
    color: var(--primary-500);
    font-size: 18px;
    display: flex;
    align-items: center;
  }
}

// Responsive adjustments
@media (max-width: 640px) {
  .header-content {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .header-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
