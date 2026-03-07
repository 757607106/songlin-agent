<template>
  <div class="home-container">
    <!-- 加载中状态 -->
    <div v-if="isLoading" class="loading-container">
      <a-spin size="large" />
      <p class="loading-text">正在连接服务...</p>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="error-container">
      <a-result status="error" :title="error.title" :sub-title="error.message">
        <template #extra>
          <a-button type="primary" @click="retryLoad">重试</a-button>
        </template>
      </a-result>
    </div>

    <!-- 正常内容 -->
    <template v-else>
      <div class="background-decorations">
        <div class="blob blob-1"></div>
        <div class="blob blob-2"></div>
        <div class="blob blob-3"></div>
      </div>

      <div class="hero-section">
        <div class="glass-header">
          <div class="logo">
            <img
              :src="infoStore.organization.logo"
              :alt="infoStore.organization.name"
              class="logo-img"
            />
            <span class="logo-text">{{ infoStore.organization.name }}</span>
          </div>
          <nav class="nav-links">
            <router-link
              to="/agent"
              class="nav-link"
              v-if="userStore.isLoggedIn && userStore.isAdmin"
            >
              <span>智能体</span>
            </router-link>
            <router-link
              to="/graph"
              class="nav-link"
              v-if="userStore.isLoggedIn && userStore.isAdmin"
            >
              <span>知识图谱</span>
            </router-link>
            <router-link
              to="/database"
              class="nav-link"
              v-if="userStore.isLoggedIn && userStore.isAdmin"
            >
              <span>知识库</span>
            </router-link>
          </nav>
          <div class="header-actions">
            <div class="github-link">
              <a href="https://github.com/xerrors/Yuxi-Know" target="_blank">
                <svg height="20" width="20" viewBox="0 0 16 16" version="1.1">
                  <path
                    fill-rule="evenodd"
                    d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
                  ></path>
                </svg>
              </a>
            </div>
            <UserInfoComponent :show-button="true" />
          </div>
        </div>

        <div class="hero-layout">
          <div class="hero-content">
            <h1 class="title animate-slide-up" style="animation-delay: 0.1s">
              {{ infoStore.branding.title }}
            </h1>
            <p class="subtitle animate-slide-up" style="animation-delay: 0.2s">
              {{ infoStore.branding.subtitle }}
            </p>
            <!-- <p class="description">{{ infoStore.branding.description }}</p> -->
            <div class="hero-actions animate-slide-up" style="animation-delay: 0.3s">
              <button class="button-base primary btn-primary-glow" @click="goToChat">
                开始对话
              </button>
              <a
                class="button-base secondary"
                href="https://xerrors.github.io/Yuxi-Know/"
                target="_blank"
                >查看文档</a
              >
            </div>
          </div>
          <div
            class="insight-panel glass-panel animate-slide-up"
            v-if="featureCards.length"
            style="animation-delay: 0.4s"
          >
            <div class="stat-card" v-for="card in featureCards" :key="card.label">
              <div class="stat-headline">
                <span class="stat-icon" v-if="card.icon">
                  <component :is="card.icon" />
                </span>
                <p class="stat-value">{{ card.value }}</p>
              </div>
              <p class="stat-label">{{ card.label }}</p>
              <p class="stat-description">{{ card.description }}</p>
            </div>
          </div>
        </div>
      </div>

      <div
        class="section action-section animate-slide-up"
        v-if="actionLinks.length"
        style="animation-delay: 0.5s"
      >
        <div class="action-grid">
          <a
            v-for="action in actionLinks"
            :key="action.name"
            class="action-card hover-card"
            :href="action.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span class="action-icon" v-if="action.icon">
              <component :is="action.icon" />
            </span>
            <div class="action-meta">
              <p class="action-title">{{ action.name }}</p>
              <p class="action-url">{{ action.url }}</p>
            </div>
          </a>
        </div>
      </div>

      <ProjectOverview />

      <footer class="footer">
        <div class="footer-content">
          <p class="copyright">
            {{ infoStore.footer?.copyright || '© 2025 All rights reserved' }}
          </p>
        </div>
      </footer>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useInfoStore } from '@/stores/info'
import { useAgentStore } from '@/stores/agent'
import { useThemeStore } from '@/stores/theme'
import { healthApi } from '@/apis/system_api'
import { Result, Button } from 'ant-design-vue'
import UserInfoComponent from '@/components/UserInfoComponent.vue'
import ProjectOverview from '@/components/ProjectOverview.vue'
import {
  BookText,
  Bug,
  Video,
  Route,
  Github,
  Star,
  CheckCircle2,
  GitCommit,
  ShieldCheck
} from 'lucide-vue-next'

const AResult = Result
const AButton = Button

const router = useRouter()
const userStore = useUserStore()
const infoStore = useInfoStore()
const agentStore = useAgentStore()
const themeStore = useThemeStore()

// 加载状态
const isLoading = ref(true)
const error = ref(null)

const checkHealth = async () => {
  try {
    const response = await healthApi.checkHealth()
    if (response.status !== 'ok') {
      throw new Error('服务不可用')
    }
  } catch (e) {
    error.value = {
      title: '服务连接失败',
      message: '后端服务无法响应，请检查服务是否正常运行'
    }
    throw e
  }
}

const loadData = async () => {
  isLoading.value = true
  error.value = null

  try {
    // 先检查健康状态
    await checkHealth()
    // 健康检查通过后加载配置
    await infoStore.loadInfoConfig()
  } catch (e) {
    console.error('加载失败:', e)
  } finally {
    isLoading.value = false
  }
}

const retryLoad = () => {
  loadData()
}

const goToChat = async () => {
  // 检查用户是否登录
  if (!userStore.isLoggedIn) {
    // 登录后应该跳转到默认智能体而不是/agent
    sessionStorage.setItem('redirect', '/') // 设置为首页，登录后会通过路由守卫处理重定向
    router.push('/login')
    return
  }

  // 根据用户角色进行跳转
  if (userStore.isAdmin) {
    // 管理员用户跳转到聊天页面
    router.push('/agent')
    return
  }

  // 普通用户跳转到默认智能体
  try {
    // 获取默认智能体
    const defaultAgent = agentStore.defaultAgent
    if (defaultAgent?.id) {
      router.push(`/agent/${defaultAgent.id}`)
    } else {
      router.push('/agent')
    }
  } catch (error) {
    console.error('跳转到智能体页面失败:', error)
    router.push('/')
  }
}

onMounted(() => {
  // 加载数据
  loadData()
})

const iconKey = (value) => (typeof value === 'string' ? value.toLowerCase() : '')

// region icon_mapping
const featureIconMap = {
  stars: Star,
  issues: CheckCircle2,
  resolved: CheckCircle2,
  commits: GitCommit,
  license: ShieldCheck,
  default: Star
}

const actionIconMap = {
  doc: BookText,
  docs: BookText,
  document: BookText,
  issue: Bug,
  bug: Bug,
  roadmap: Route,
  plan: Route,
  demo: Video,
  video: Video,
  github: Github,
  default: Github
}
// endregion icon_mapping

const featureCards = computed(() => {
  const list = Array.isArray(infoStore.features) ? infoStore.features : []
  return list
    .map((item) => {
      if (typeof item === 'string') {
        return {
          label: item,
          value: '',
          description: '',
          icon: featureIconMap.default
        }
      }

      const key = iconKey(item.icon || item.type)
      return {
        label: item.label || item.name || '',
        value: item.value || '',
        description: item.description || '',
        icon: featureIconMap[key] || featureIconMap.default
      }
    })
    .filter((item) => item.label || item.value || item.description)
})

const actionLinks = computed(() => {
  const actions = infoStore.actions
  if (!Array.isArray(actions)) {
    return []
  }

  return actions
    .map((item) => {
      const key = iconKey(item?.icon || item?.type)
      return {
        name: item?.name || item?.label || '',
        url: item?.url || item?.link || '',
        icon: actionIconMap[key] || actionIconMap.default
      }
    })
    .filter((item) => item.name && item.url)
})
</script>

<style lang="less" scoped>
.home-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  color: var(--gray-900);
  background: var(--gray-50);
  position: relative;
  overflow-x: hidden;
}

.background-decorations {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  z-index: 0;
  pointer-events: none;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.6;
}

.blob-1 {
  top: -10%;
  right: -10%;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, var(--main-200), var(--main-100));
  animation: float 20s infinite ease-in-out;
}

.blob-2 {
  bottom: -10%;
  left: -10%;
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, var(--main-100), var(--color-secondary-100));
  animation: float 25s infinite ease-in-out reverse;
}

.blob-3 {
  top: 40%;
  left: 40%;
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, var(--color-accent-100), transparent);
  animation: float 15s infinite ease-in-out;
  opacity: 0.4;
}

@keyframes float {
  0%,
  100% {
    transform: translate(0, 0);
  }
  50% {
    transform: translate(30px, -30px);
  }
}

// 加载中状态
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 1.5rem;
  z-index: 10;

  .loading-text {
    color: var(--gray-600);
    font-size: 1rem;
    font-weight: 500;
  }
}

// 错误状态
.error-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem;
  z-index: 10;
}

.glass-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 1rem 3rem;
  background: var(--glass-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--glass-border);
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  transition: all 0.3s ease;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  text-decoration: none;
  color: var(--gray-700);
  font-weight: 500;
  font-size: 0.95rem;
  transition: all 0.2s ease;
  border-radius: 8px;

  &:hover {
    color: var(--main-600);
    background: var(--main-50);
  }

  &.router-link-active {
    color: var(--main-700);
    background: var(--main-100);
    font-weight: 600;
  }

  span {
    white-space: nowrap;
  }
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.logo {
  display: flex;
  align-items: center;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--main-900);
  letter-spacing: -0.02em;

  .logo-img {
    height: 2.2rem;
    margin-right: 0.8rem;
  }
}

.github-link a {
  display: flex;
  align-items: center;
  text-decoration: none;
  color: var(--gray-600);
  padding: 0.6rem;
  border-radius: 50%;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);

  &:hover {
    color: var(--gray-900);
    background: var(--gray-100);
    transform: rotate(15deg);
  }

  svg {
    transition: transform 0.3s ease;
    fill: currentColor;
  }
}

.hero-section {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 6rem 2rem 4rem;
  position: relative;
  z-index: 1;
}

.hero-layout {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
  gap: 4rem;
  align-items: center;
  max-width: 1280px;
  margin: 0 auto;
  padding-top: 2rem;
}

.hero-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 600px;
}

.title {
  font-size: clamp(3rem, 5vw, 4.5rem);
  font-weight: 800;
  margin: 0;
  background: linear-gradient(
    135deg,
    var(--main-900) 0%,
    var(--main-600) 50%,
    var(--color-secondary-500) 100%
  );
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  letter-spacing: -0.03em;
  line-height: 1.1;
  padding-bottom: 0.2em; /* prevent descender clipping */
}

.subtitle {
  font-size: 1.25rem;
  font-weight: 500;
  color: var(--gray-600);
  line-height: 1.6;
  max-width: 90%;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  margin-top: 1rem;
}

.button-base {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 2rem;
  border-radius: 999px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  min-height: 52px;
}

.button-base.primary {
  background: var(--main-600);
  color: white;
  box-shadow: 0 4px 14px 0 rgba(8, 145, 178, 0.39);

  &:hover {
    background: var(--main-700);
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(8, 145, 178, 0.23);
  }

  &:active {
    transform: translateY(0);
  }
}

.button-base.secondary {
  background: white;
  color: var(--gray-700);
  border: 1px solid var(--gray-200);
  box-shadow: var(--shadow-sm);

  &:hover {
    border-color: var(--gray-300);
    color: var(--main-600);
    background: var(--gray-50);
    transform: translateY(-2px);
    box-shadow: var(--shadow-1);
  }
}

.insight-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
  padding: 2rem;
  border-radius: 24px;
  box-shadow: var(--shadow-4);
  background: rgba(255, 255, 255, 0.8);
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  border-radius: 16px;
  transition: background 0.2s ease;

  &:hover {
    background: rgba(255, 255, 255, 0.5);
  }
}

.stat-headline {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: var(--main-50);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--main-600);

  :deep(svg) {
    width: 24px;
    height: 24px;
  }
}

.stat-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--gray-900);
  margin: 0;
  letter-spacing: -0.02em;
}

.stat-label {
  margin: 0;
  color: var(--gray-500);
  font-weight: 600;
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-description {
  margin: 0;
  color: var(--gray-600);
  font-size: 0.95rem;
  line-height: 1.5;
}

.section {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 4rem 2rem;
  position: relative;
  z-index: 1;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 1.5rem;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  border-radius: 16px;
  text-decoration: none;
  color: inherit;
  background: white;
  border: 1px solid var(--gray-100);
  box-shadow: var(--shadow-sm);

  &:hover {
    border-color: var(--main-200);
    .action-icon {
      background: var(--main-600);
      color: white;
    }

    .action-title {
      color: var(--main-700);
    }
  }
}

.action-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--main-50);
  color: var(--main-600);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.3s ease;

  :deep(svg) {
    width: 24px;
    height: 24px;
  }
}

.action-meta {
  flex: 1;
  overflow: hidden;
}

.action-title {
  margin: 0;
  font-weight: 600;
  color: var(--gray-800);
  font-size: 1rem;
  transition: color 0.2s ease;
}

.action-url {
  margin: 0.25rem 0 0;
  font-size: 0.85rem;
  color: var(--gray-500);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.footer {
  margin-top: auto;
  background: white;
  border-top: 1px solid var(--gray-100);
  position: relative;
  z-index: 10;
}

.footer-content {
  text-align: center;
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

.copyright {
  color: var(--gray-500);
  font-size: 0.875rem;
  font-weight: 500;
}

@media (max-width: 768px) {
  .glass-header {
    padding: 0.8rem 1.25rem;
  }

  .nav-links {
    display: none; /* Consider a mobile menu for smaller screens */
  }

  .hero-section {
    padding: 6rem 1.5rem 2rem;
  }

  .title {
    font-size: 2.75rem;
  }

  .hero-layout {
    grid-template-columns: 1fr;
    gap: 3rem;
  }

  .insight-panel {
    padding: 1.5rem;
  }
}
</style>
