<template>
  <a-config-provider :theme="{ token: theme }" :locale="zhCN">
    <a-layout v-if="store.user" class="admin-shell">
      <a-layout-sider v-model:collapsed="sidebarCollapsed" :width="200" :collapsed-width="64" theme="dark" class="sidebar">
        <div class="brand">
          <div class="brand-mark">卡</div>
          <div v-if="!sidebarCollapsed" class="brand-text">
            <strong>卡密系统</strong>
          </div>
        </div>
        <a-menu v-model:selectedKeys="selectedKeys" theme="dark" mode="inline" class="admin-menu">
          <a-menu-item key="dashboard">
            <template #icon><DashboardOutlined /></template>
            仪表盘
          </a-menu-item>
          <a-menu-item key="converter">
            <template #icon><FileTextOutlined /></template>
            格式转换
          </a-menu-item>
          <a-menu-item key="cards">
            <template #icon><KeyOutlined /></template>
            卡密管理
          </a-menu-item>
          <a-menu-item key="accountPool">
            <template #icon><DatabaseOutlined /></template>
            号池管理
          </a-menu-item>
          <a-menu-item key="logs">
            <template #icon><HistoryOutlined /></template>
            提取记录
          </a-menu-item>
          <a-menu-item key="security">
            <template #icon><SafetyCertificateOutlined /></template>
            安全中心
          </a-menu-item>
          <a-menu-item key="settings">
            <template #icon><SettingOutlined /></template>
            系统设置
          </a-menu-item>
        </a-menu>
        <button class="sidebar-collapse" type="button" :title="sidebarCollapsed ? '展开导航' : '收起导航'" @click="sidebarCollapsed = !sidebarCollapsed">
          <MenuUnfoldOutlined v-if="sidebarCollapsed" />
          <MenuFoldOutlined v-else />
        </button>
      </a-layout-sider>

      <a-layout>
        <a-layout-header class="topbar admin-header">
          <div class="header-spacer"></div>
          <a-space :size="12">
            <a-dropdown :trigger="['click']" placement="bottomRight" overlay-class-name="user-dropdown">
              <a-button class="user-menu-button">
                <a-avatar :src="store.user.avatar || undefined">{{ store.user.username.slice(0, 1).toUpperCase() }}</a-avatar>
                {{ store.user.username }}
              </a-button>
              <template #overlay>
                <a-menu>
                  <a-menu-item @click="profileOpen = true">
                    <UserOutlined />
                    个人中心
                  </a-menu-item>
                  <a-menu-item @click="passwordOpen = true">
                    <LockOutlined />
                    修改密码
                  </a-menu-item>
                  <a-menu-divider />
                  <a-menu-item danger @click="logout">
                    <LogoutOutlined />
                    退出登录
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </a-space>
        </a-layout-header>

        <a-layout-content class="content admin-content">
          <DashboardView v-if="currentView === 'dashboard'" />
          <FormatConverter v-else-if="currentView === 'converter'" />
          <CardManager v-else-if="currentView === 'cards'" />
          <AccountPool v-else-if="currentView === 'accountPool'" />
          <ExtractionLogs v-else-if="currentView === 'logs'" />
          <SecurityCenter v-else-if="currentView === 'security'" />
          <SystemSettings v-else />
        </a-layout-content>
      </a-layout>

      <ProfileDrawer v-model:open="profileOpen" />
      <a-modal
        v-model:open="passwordOpen"
        title="修改密码"
        :confirm-loading="passwordSaving"
        ok-text="确定"
        cancel-text="取消"
        @ok="submitPassword"
      >
        <a-form :model="passwordForm" layout="vertical">
          <a-form-item label="原密码">
            <a-input-password v-model:value="passwordForm.current_password" autocomplete="current-password" />
          </a-form-item>
          <a-form-item label="新密码">
            <a-input-password v-model:value="passwordForm.new_password" autocomplete="new-password" />
          </a-form-item>
          <a-form-item label="确认新密码">
            <a-input-password v-model:value="passwordForm.confirm_password" autocomplete="new-password" />
          </a-form-item>
        </a-form>
      </a-modal>
    </a-layout>

    <div v-else-if="authReady" class="login-shell">
      <a-card class="login-card" :bordered="false">
        <div class="login-brand">
          <div class="brand-mark">卡</div>
          <h1>卡密管理后台</h1>
        </div>
        <a-form :model="loginForm" layout="vertical" @finish="submitLogin">
          <a-form-item label="管理员账号" name="username">
            <a-input v-model:value="loginForm.username" size="large" autocomplete="username" />
          </a-form-item>
          <a-form-item label="管理员密码" name="password">
            <a-input-password v-model:value="loginForm.password" size="large" autocomplete="current-password" />
          </a-form-item>
          <div v-if="store.loginTurnstile.enabled" class="turnstile-box">
            <div id="turnstile-login-widget" ref="turnstileEl" class="turnstile-widget"></div>
          </div>
          <a-button class="login-submit" type="primary" html-type="submit" size="large" block :loading="loading">登录</a-button>
        </a-form>
      </a-card>
    </div>
    <div v-else class="login-shell">
      <a-spin />
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import {
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  HistoryOutlined,
  KeyOutlined,
  LockOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'
import { useAdminStore } from '../stores/admin'
import DashboardView from './DashboardView.vue'
import FormatConverter from './FormatConverter.vue'
import CardManager from './CardManager.vue'
import AccountPool from './AccountPool.vue'
import ExtractionLogs from './ExtractionLogs.vue'
import SystemSettings from './SystemSettings.vue'
import SecurityCenter from './SecurityCenter.vue'
import ProfileDrawer from '../components/ProfileDrawer.vue'
import { loadTurnstileScript, type TurnstileWidgetId } from '../utils/turnstile'

const theme = {
  colorPrimary: '#111827',
  colorPrimaryHover: '#000000',
  colorText: '#1F2937',
  colorTextBase: '#1F2937',
  colorTextSecondary: '#6B7280',
  colorBorder: '#E5E7EB',
  colorBgLayout: '#f3f5f7',
  colorBgContainer: '#FFFFFF',
  borderRadius: 8,
  fontSize: 14,
}
const store = useAdminStore()
const selectedKeys = ref(['dashboard'])
const sidebarCollapsed = ref(false)
const profileOpen = ref(false)
const passwordOpen = ref(false)
const passwordSaving = ref(false)
const loading = ref(false)
const authReady = ref(false)
const loginForm = reactive({ username: 'admin', password: '' })
const passwordForm = reactive({ current_password: '', new_password: '', confirm_password: '' })
const currentView = computed(() => selectedKeys.value[0])
const turnstileEl = ref<HTMLElement | null>(null)
const turnstileWidgetId = ref<TurnstileWidgetId | null>(null)
const turnstileToken = ref('')

async function loadInitialData() {
  const results = await Promise.allSettled([store.loadSettings(), store.loadTurnstileSettings(), store.loadDashboard(), store.loadBatches()])
  const failed = results.find((item) => item.status === 'rejected')
  if (failed && failed.status === 'rejected') {
    message.warning(failed.reason instanceof Error ? failed.reason.message : '部分数据加载失败')
  }
}

function destroyTurnstile() {
  if (turnstileWidgetId.value !== null) {
    try {
      window.turnstile?.remove?.(turnstileWidgetId.value)
    } catch {
      // ignore widget cleanup errors
    }
  }
  if (turnstileEl.value) turnstileEl.value.innerHTML = ''
  turnstileWidgetId.value = null
  turnstileToken.value = ''
}

async function renderTurnstile() {
  if (store.user || !store.loginTurnstile.enabled || !store.loginTurnstile.site_key || turnstileWidgetId.value !== null) return
  await nextTick()
  const container = turnstileEl.value
  if (!container?.isConnected) return
  try {
    await loadTurnstileScript()
    if (store.user || turnstileWidgetId.value !== null || turnstileEl.value !== container || !container.isConnected) return
    if (!window.turnstile) throw new Error('Turnstile 加载失败')
    turnstileWidgetId.value = window.turnstile.render(container, {
      sitekey: store.loginTurnstile.site_key,
      action: 'admin_login',
      theme: 'light',
      callback: (token: string) => {
        turnstileToken.value = token
      },
      'expired-callback': () => {
        turnstileToken.value = ''
      },
      'error-callback': () => {
        turnstileToken.value = ''
      },
    })
  } catch (error) {
    message.error(error instanceof Error ? error.message : '人机验证加载失败')
  }
}

function resetTurnstile() {
  turnstileToken.value = ''
  if (turnstileWidgetId.value !== null) {
    try {
      window.turnstile?.reset(turnstileWidgetId.value)
    } catch {
      destroyTurnstile()
      void renderTurnstile()
    }
  }
}

async function submitLogin() {
  if (loading.value) return
  if (store.loginTurnstile.enabled && !turnstileToken.value) {
    message.warning('请先完成人机验证')
    return
  }
  loading.value = true
  try {
    await store.login(loginForm.username, loginForm.password, turnstileToken.value)
    destroyTurnstile()
    await loadInitialData()
  } catch (error) {
    resetTurnstile()
    message.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    loading.value = false
  }
}

async function logout() {
  await store.logout()
  await store.loadLoginSettings().catch(() => undefined)
  await renderTurnstile()
}

async function submitPassword() {
  if (passwordSaving.value) return
  if (!passwordForm.current_password || !passwordForm.new_password) {
    message.warning('请填写原密码和新密码')
    return
  }
  if (passwordForm.new_password.length < 8) {
    message.warning('新密码至少 8 位')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    message.warning('两次输入的新密码不一致')
    return
  }
  passwordSaving.value = true
  try {
    await store.changePassword({
      current_password: passwordForm.current_password,
      new_password: passwordForm.new_password,
    })
    message.success('密码已修改，请重新登录')
    passwordOpen.value = false
    passwordForm.current_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm_password = ''
    await store.loadLoginSettings().catch(() => undefined)
    await renderTurnstile()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '修改失败')
  } finally {
    passwordSaving.value = false
  }
}

watch(
  () => (store.user ? '' : `${store.loginTurnstile.enabled}:${store.loginTurnstile.site_key}`),
  () => {
    destroyTurnstile()
    void renderTurnstile()
  },
  { flush: 'post' },
)

onMounted(async () => {
  try {
    await store.me()
    authReady.value = true
    await loadInitialData()
  } catch {
    store.user = null
    await store.loadLoginSettings().catch(() => undefined)
    authReady.value = true
    await renderTurnstile()
  }
})

onBeforeUnmount(destroyTurnstile)
</script>
