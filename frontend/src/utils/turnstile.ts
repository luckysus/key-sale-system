export type TurnstileWidgetId = string | number

export type TurnstileRenderOptions = {
  sitekey: string
  action?: string
  callback: (token: string) => void
  'expired-callback': () => void
  'error-callback': () => void
  theme?: 'light' | 'dark' | 'auto'
  size?: 'normal' | 'compact' | 'flexible'
}

export type TurnstileApi = {
  render: (container: string | HTMLElement, options: TurnstileRenderOptions) => TurnstileWidgetId
  reset: (widgetId?: TurnstileWidgetId) => void
  remove?: (widgetId: TurnstileWidgetId) => void
}

declare global {
  interface Window {
    turnstile?: TurnstileApi
    __turnstileLoading?: Promise<void>
  }
}

export function loadTurnstileScript() {
  if (window.turnstile) return Promise.resolve()
  if (window.__turnstileLoading) return window.__turnstileLoading
  window.__turnstileLoading = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-turnstile="true"]')
    existing?.remove()
    const script = document.createElement('script')
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
    script.async = true
    script.defer = true
    script.dataset.turnstile = 'true'
    script.onload = () => {
      if (window.turnstile) resolve()
      else {
        script.remove()
        reject(new Error('Turnstile 加载失败'))
      }
    }
    script.onerror = () => {
      script.remove()
      reject(new Error('Turnstile 加载失败'))
    }
    document.head.appendChild(script)
  }).finally(() => {
    window.__turnstileLoading = undefined
  })
  return window.__turnstileLoading
}
