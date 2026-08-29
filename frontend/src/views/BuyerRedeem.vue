<template>
  <a-config-provider :theme="{ token: theme }">
    <main class="buyer-shell">
      <div class="buyer-stage-word" aria-hidden="true">REDEEM</div>
      <div class="buyer-stage-noise" aria-hidden="true"></div>
      <div class="buyer-sparks" aria-hidden="true">
        <span class="buyer-spark buyer-spark-one">✦</span>
        <span class="buyer-spark buyer-spark-two">✷</span>
        <span class="buyer-spark buyer-spark-three">★</span>
        <span class="buyer-spark buyer-spark-four">✦</span>
        <span class="buyer-spark buyer-spark-five">✹</span>
      </div>
      <div class="buyer-sticker" aria-hidden="true">4 STEP DELIVERY!</div>

      <section class="buyer-tool" aria-labelledby="buyer-title">
        <header class="buyer-tool-head">
          <span class="buyer-mark" aria-hidden="true"><KeyOutlined /></span>
          <div>
            <span>LUCKY KEY</span>
            <h1 id="buyer-title">卡密提取</h1>
          </div>
        </header>

        <a-form :model="form" layout="vertical" @finish="redeem">
          <a-form-item label="卡密" name="code">
            <a-input v-model:value="form.code" size="large" placeholder="XXXX-XXXX-XXXX-XXXX" :disabled="loading || !serviceAvailable" class="buyer-code-input" />
          </a-form-item>
          <a-form-item v-if="challengeRequired" class="buyer-turnstile-item">
            <div id="turnstile-redeem-widget" ref="turnstileEl" class="turnstile-widget"></div>
          </a-form-item>
          <a-button type="primary" html-type="submit" size="large" block :loading="loading" :disabled="loading || !serviceAvailable" class="buyer-submit">
            <template v-if="!loading" #icon><CloudDownloadOutlined /></template>
            {{ loading ? activeStepText : '提取账号' }}
          </a-button>
        </a-form>

        <div v-if="currentStep >= 0" class="buyer-progress" aria-live="polite">
          <div class="buyer-progress-track" aria-hidden="true">
            <span v-for="(step, index) in buyerRedeemSteps" :key="step" :class="{ active: index === currentStep, done: index < currentStep }"></span>
          </div>
          <div class="buyer-progress-meta">
            <strong>{{ activeStepText }}</strong>
            <span>{{ currentStep + 1 }} / {{ buyerRedeemSteps.length }}</span>
          </div>
        </div>

        <a-alert v-if="messageText" class="buyer-alert" :type="messageType" show-icon :message="messageText" />
      </section>
    </main>
  </a-config-provider>
</template>

<script setup lang="ts">
import { CloudDownloadOutlined, KeyOutlined } from '@ant-design/icons-vue'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { buyerRedeemSteps, fileNameFromDisposition } from '../api/client'
import { loadTurnstileScript, type TurnstileWidgetId } from '../utils/turnstile'

const theme = {
  colorPrimary: '#FF3AF2',
  colorPrimaryHover: '#7B2FFF',
  colorText: '#FFFFFF',
  colorTextBase: '#FFFFFF',
  colorTextSecondary: '#D7C9FF',
  colorBorder: '#00F5D4',
  colorBgLayout: '#0D0D1A',
  colorBgContainer: '#2D1B4E',
  colorSuccess: '#00F5D4',
  colorWarning: '#FFE600',
  colorError: '#FF3AF2',
  borderRadius: 16,
}
const form = reactive({ code: '' })
const loading = ref(false)
const currentStep = ref(-1)
const messageText = ref('')
const messageType = ref<'success' | 'error' | 'info' | 'warning'>('info')
const serviceAvailable = ref(false)
const challengeRequired = ref(false)
const turnstileSiteKey = ref('')
const turnstileEl = ref<HTMLElement | null>(null)
const turnstileWidgetId = ref<TurnstileWidgetId | null>(null)
const turnstileToken = ref('')
const timers: number[] = []
const activeStepText = computed(() => buyerRedeemSteps[Math.max(0, currentStep.value)] || '正在处理')

function clearTimers() {
  while (timers.length) window.clearTimeout(timers.pop())
}

function startStepTimer() {
  clearTimers()
  currentStep.value = 0
  timers.push(window.setTimeout(() => {
    if (loading.value) currentStep.value = 1
  }, 450))
  timers.push(window.setTimeout(() => {
    if (loading.value) currentStep.value = 2
  }, 1200))
}

function destroyTurnstile() {
  if (turnstileWidgetId.value !== null) {
    try {
      window.turnstile?.remove?.(turnstileWidgetId.value)
    } catch {
      // The widget can already be gone after a challenge navigation.
    }
  }
  if (turnstileEl.value) turnstileEl.value.innerHTML = ''
  turnstileWidgetId.value = null
  turnstileToken.value = ''
}

async function renderTurnstile() {
  if (!challengeRequired.value) return
  if (!turnstileSiteKey.value || turnstileWidgetId.value !== null) return
  await nextTick()
  const container = turnstileEl.value
  if (!container?.isConnected) return
  try {
    await loadTurnstileScript()
    if (!challengeRequired.value || turnstileWidgetId.value !== null || turnstileEl.value !== container || !container.isConnected) return
    if (!window.turnstile) throw new Error('人机验证加载失败')
    turnstileWidgetId.value = window.turnstile.render(container, {
      sitekey: turnstileSiteKey.value,
      action: 'buyer_redeem',
      theme: 'dark',
      size: 'flexible',
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
    serviceAvailable.value = false
    messageType.value = 'error'
    messageText.value = error instanceof Error ? error.message : '人机验证加载失败'
  }
}

function resetTurnstile() {
  turnstileToken.value = ''
  if (turnstileWidgetId.value === null) return
  try {
    window.turnstile?.reset(turnstileWidgetId.value)
  } catch {
    destroyTurnstile()
    void renderTurnstile()
  }
}

async function loadRedeemSettings(silent = false) {
  try {
    const response = await fetch('/api/public/redeem-settings', { credentials: 'same-origin' })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
    const required = Boolean(data.turnstile?.required)
    const siteKey = String(data.turnstile?.site_key || '')
    serviceAvailable.value = true
    challengeRequired.value = required
    turnstileSiteKey.value = siteKey
    if (required) {
      await renderTurnstile()
    } else {
      destroyTurnstile()
    }
  } catch (error) {
    serviceAvailable.value = false
    if (!silent) {
      messageType.value = 'error'
      messageText.value = error instanceof Error ? error.message : '兑换服务暂时不可用'
    }
  }
}

async function redeem() {
  if (loading.value || !serviceAvailable.value) return
  const code = form.code.trim()
  if (!code) {
    messageType.value = 'warning'
    messageText.value = '请输入卡密'
    currentStep.value = -1
    return
  }
  if (challengeRequired.value && !turnstileToken.value) {
    messageType.value = 'warning'
    messageText.value = '请先完成人机验证'
    currentStep.value = -1
    return
  }
  messageText.value = ''
  loading.value = true
  startStepTimer()
  try {
    const response = await fetch('/api/redeem', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, turnstile_token: turnstileToken.value }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || data.message || `HTTP ${response.status}`)
    }
    currentStep.value = 2
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = fileNameFromDisposition(response.headers.get('content-disposition'), 'accounts.zip')
    document.body.append(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    currentStep.value = 3
    messageType.value = 'success'
    messageText.value = '下载已生成，里面包含 sub2api.json 和 cpa.json。'
    challengeRequired.value = false
    destroyTurnstile()
  } catch (error) {
    currentStep.value = -1
    messageType.value = 'error'
    messageText.value = error instanceof Error ? error.message : '提取失败'
    resetTurnstile()
    await loadRedeemSettings(true)
  } finally {
    loading.value = false
    clearTimers()
  }
}

onMounted(() => {
  void loadRedeemSettings()
})

onBeforeUnmount(() => {
  clearTimers()
  destroyTurnstile()
})
</script>
