export type User = { id: number; username: string; email?: string; avatar?: string }
export type Group = { id: string; name: string }
export type AccountPoolGroup = Group & { total: number; allocated: number; unallocated: number }
export type AccountPoolAllocation = {
  card_id: number
  card_code: string
  card_status: string
  test_status: string
  allocated_at: number
}
export type AccountPoolAccount = {
  id: string
  name: string
  type: string
  platform: string
  status: string
  schedulable: boolean
  concurrency: number
  current_concurrency: number
  error_message: string
  groups: Group[]
  allocated: boolean
  manual_extracted: boolean
  manual_extracted_at?: number
  allocation: AccountPoolAllocation | null
}
export type AccountPoolData = {
  updated_at: number
  summary: {
    group_count: number
    account_count: number
    allocated_count: number
    unallocated_count: number
  }
  groups: AccountPoolGroup[]
  accounts: AccountPoolAccount[]
}
export type Batch = { id: number; name: string; note: string; created_at: number }
export type Card = {
  id: number
  code: string
  batch_name?: string
  batch_id?: number
  group_id: string
  group_name: string
  account_count: number
  status: string
  used_by: string
  used_at?: number
  created_at: number
}
export type AccountAllocation = { id: number; card_id: number; sub2api_account_id: string; account_name: string; test_status: string; allocated_at: number }
export type AccessLog = {
  id: number
  card_id?: number
  card_code?: string
  ip: string
  user_agent: string
  result: string
  message: string
  created_at: number
}
export type AccessLogFilters = { card_id?: number; result?: string; keyword?: string; limit?: number }
export type Sub2APISettings = { base_url: string; has_api_key: boolean; has_bearer_token: boolean }
export type LoginTurnstileSettings = { enabled: boolean; site_key: string }
export type TurnstileSettings = LoginTurnstileSettings & { has_secret_key: boolean }
export type StockWarning = { group_id: string; group_name: string; total: number; allocated: number; available: number; min_available: number }
export type StockSnapshot = { updated_at: number; items?: StockWarning[]; warnings: StockWarning[] }
export type DashboardData = {
  overview: {
    total_cards: number
    unused_cards: number
    used_cards: number
    disabled_cards: number
    today_success: number
    today_failed: number
  }
  trend: { date: string; success: number; failed: number }[]
  stock: StockSnapshot
  recent_logs: AccessLog[]
}
export type StockThreshold = { group_id: string; group_name: string; min_available: number; enabled: boolean }
export type SMTPSettings = {
  enabled: boolean
  host: string
  port: number
  username: string
  from_email: string
  to_email: string
  use_ssl: boolean
  use_tls: boolean
  has_password: boolean
}
export type SecuritySummary = {
  turnstile: TurnstileSettings
  abnormal_ips: { ip: string; type: string; count: number; updated_at: number }[]
  recent_audit_logs: AuditLog[]
  recent_login_failures: LoginFailure[]
}
export type AuditLog = { id: number; actor_username: string; action: string; target: string; ip: string; result: string; created_at: number }
export type LoginFailure = { key: string; ip: string; username: string; failures: number; locked_until: number; updated_at: number }
export type CardFilters = { status?: string; batch_id?: number | null; group_id?: string; keyword?: string; limit?: number }

async function parseJson(response: Response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.ok === false) {
    throw new Error(data.detail || data.error || data.message || `HTTP ${response.status}`)
  }
  return data
}

async function safeFetch(input: RequestInfo | URL, init?: RequestInit) {
  try {
    return await fetch(input, init)
  } catch (error) {
    if (error instanceof TypeError) throw new Error('网络请求失败，请刷新页面或稍后重试')
    throw error
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return parseJson(await safeFetch(path, { credentials: 'same-origin' }))
}

// 读取双提交 CSRF Cookie（登录成功后由后端下发的非 HttpOnly csrf_token）。
export function readCookie(name: string): string {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + escaped + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : ''
}

let csrfRefresh: Promise<void> | null = null

async function ensureCsrfToken() {
  if (readCookie('csrf_token')) return
  csrfRefresh ||= safeFetch('/api/admin/me', { credentials: 'same-origin' })
    .then((response) => {
      if (!response.ok) throw new Error('请先登录')
      return response.json().then(() => undefined).catch(() => undefined)
    })
    .finally(() => {
      csrfRefresh = null
    })
  await csrfRefresh
}

export async function apiSend<T>(path: string, method: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json' }
  // 契约：请求头 X-CSRF-Token 必须与 cookie csrf_token 一致，写操作才被后端放行。
  if (path.startsWith('/api/admin/') && path !== '/api/admin/login') await ensureCsrfToken()
  const csrfToken = readCookie('csrf_token')
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  return parseJson(await safeFetch(path, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  }))
}

export function formatTime(ts?: number) {
  return ts ? new Date(ts * 1000).toLocaleString() : '-'
}

export function fileNameFromDisposition(header: string | null, fallback: string) {
  const match = /filename="?([^";]+)"?/i.exec(header || '')
  return match?.[1] || fallback
}

export function csvSafeCell(value: unknown) {
  const text = String(value ?? '').replace(/[\r\n\t]+/g, ' ').trim()
  return /^[=+\-@]/.test(text) ? `'${text}` : text
}

export const buyerRedeemSteps = ['正在校验卡密', '正在验活账号', '正在打包文件', '下载已生成']

export function accessLogResultText(result: string) {
  return ({
    success: '成功',
    invalid: '格式无效',
    not_found: '无效卡密',
    blocked: '不可用',
    expired: '已过期',
    insufficient: '活号不足',
    sub2api_error: 'sub2api 错误',
    timeout: '处理超时',
    busy: '处理中',
  } as Record<string, string>)[result] || result
}

export function accessLogResultColor(result: string) {
  return ({
    success: 'green',
    invalid: 'orange',
    not_found: 'orange',
    blocked: 'default',
    expired: 'gold',
    insufficient: 'volcano',
    sub2api_error: 'red',
    timeout: 'red',
    busy: 'blue',
  } as Record<string, string>)[result] || 'default'
}

export function accessLogMessageText(log: Pick<AccessLog, 'result' | 'message'>) {
  if (log.result === 'not_found' && String(log.message || '').startsWith('sha256:')) return '无效卡密（已隐藏原始输入）'
  if (log.result === 'invalid') return '卡密格式不正确'
  const accountCount = /^(\d+)\s+accounts?$/i.exec(String(log.message || '').trim())
  if (accountCount) return `${accountCount[1]} 个账号`
  return log.message || '-'
}

export function auditActionText(action: string) {
  return ({
    login: '登录后台',
    logout: '退出登录',
    update_profile: '修改个人资料',
    change_password: '修改密码',
    update_settings: '保存系统设置',
    stock_check: '检查库存',
    smtp_test: '发送测试邮件',
    generate_cards: '生成卡密',
    delete_card: '删除卡密',
    bulk_delete_cards: '批量删除卡密',
    set_card_status: '修改卡密状态',
    bulk_set_card_status: '批量修改卡密状态',
    set_account_extraction_status: '修改账号提取状态',
    delete_batch: '删除批次',
    bulk_delete_batches: '批量删除批次',
    bulk_delete_access_logs: '批量删除提取记录',
  } as Record<string, string>)[action] || action || '-'
}

export function auditTargetText(target: string) {
  const raw = String(target || '').trim()
  if (!raw) return '-'
  const direct = ({
    sub2api: 'sub2api 连接',
    turnstile: '登录防护',
    stock_thresholds: '库存预警',
    smtp: '邮件通知',
  } as Record<string, string>)[raw]
  if (direct) return direct

  const keyText: Record<string, string> = {
    batch_id: '批次 ID',
    account_id: '账号 ID',
    card_id: '卡密 ID',
    count: '数量',
    group: '分组',
    status: '状态',
    user_id: '用户 ID',
    warnings: '预警数量',
    extracted: '提取状态',
  }
  const valueText: Record<string, string> = {
    disabled: '已禁用',
    unused: '未使用',
    used: '已使用',
    true: '已提取',
    false: '未提取',
  }

  return raw
    .split(',')
    .map((part) => {
      const [key, ...rest] = part.split('=')
      const cleanKey = key.trim()
      const value = rest.join('=').trim()
      if (!value) return keyText[cleanKey] || cleanKey || '-'
      return `${keyText[cleanKey] || cleanKey}：${valueText[value] || value}`
    })
    .join('，')
}

function unwrapPayload(payload: unknown): unknown {
  const data = payload as any
  if (data && typeof data === 'object' && 'code' in data && data.code !== 0 && data.code !== '0') {
    throw new Error(data.message || data.msg || 'sub2api 返回错误')
  }
  return data && typeof data === 'object' && 'data' in data ? data.data : data
}

export function extractAccounts(payload: unknown): Record<string, unknown>[] {
  const data = unwrapPayload(payload) as any
  if (Array.isArray(data)) return data
  if (Array.isArray(data?.accounts)) return data.accounts
  if (Array.isArray(data?.items)) return data.items
  if (data && typeof data === 'object' && ('credentials' in data || 'name' in data)) return [data]
  throw new Error('无法识别账号数据格式')
}

export function parseAccountsText(rawText: string): Record<string, unknown>[] {
  const text = String(rawText || '').replace(/^\uFEFF/, '').trim()
  if (!text) throw new Error('文件内容为空')
  try {
    return extractAccounts(JSON.parse(text))
  } catch (error) {
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    if (lines.length < 2) throw error instanceof Error ? error : new Error('输入不是有效 JSON')
    return lines.map((line, index) => {
      try {
        return JSON.parse(line)
      } catch (lineError) {
        throw new Error(`第 ${index + 1} 行不是有效 JSON：${lineError instanceof Error ? lineError.message : lineError}`)
      }
    })
  }
}

export function accountsToJsonl(accounts: Record<string, unknown>[]) {
  if (!accounts.length) throw new Error('未找到账号数据')
  const lines = accounts.map((account) => JSON.stringify(account))
  const text = `${lines.join('\n')}\n`
  return {
    text,
    count: accounts.length,
    maxLineLength: Math.max(...lines.map((line) => line.length)),
    size: new Blob([text]).size,
  }
}

export function safeOutputName(name = 'sub2api') {
  return `${String(name || 'sub2api').replace(/[\\/:*?"<>|]+/g, '_')}.full.jsonl.txt`
}

export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes)) return '-'
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}
