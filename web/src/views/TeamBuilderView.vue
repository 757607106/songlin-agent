<template>
  <div class="team-builder-view">
    <AgentChatComponent ref="chatRef" agent-id="ArchitectAgent" :single-mode="true">
      <template #header-left>
        <div class="agent-nav-btn" @click="goBack">
          <ArrowLeft :size="18" class="nav-btn-icon" />
          <span class="text">返回</span>
        </div>
      </template>
      <template #header-right>
        <UserInfoComponent />
      </template>
    </AgentChatComponent>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import AgentChatComponent from '@/components/AgentChatComponent.vue'
import UserInfoComponent from '@/components/UserInfoComponent.vue'
import { useAgentStore } from '@/stores/agent'

const router = useRouter()
const agentStore = useAgentStore()
const chatRef = ref(null)

const goBack = () => {
  router.push('/agent-square')
}

onMounted(async () => {
  if (!agentStore.isInitialized) {
    await agentStore.initialize()
  }
})
</script>

<style lang="less" scoped>
.team-builder-view {
  width: 100%;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: row;
}
</style>
