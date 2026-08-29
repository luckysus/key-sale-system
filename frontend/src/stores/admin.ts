import { defineStore } from 'pinia'
import {
  apiGet,
  apiSend,
  type AccessLogFilters,
  type AccountAllocation,
  type AccountPoolData,
  type AccessLog,
  type AuditLog,
  type Batch,
  type Card,
  type CardFilters,
  type DashboardData,
  type Group,
  type LoginFailure,
  type LoginTurnstileSettings,
  type SecuritySummary,
  type SMTPSettings,
  type StockSnapshot,
  type StockThreshold,
  type Sub2APISettings,
  type TurnstileSettings,
  type User,
} from '../api/client'

export const useAdminStore = defineStore('admin', {
  state: () => ({
    user: null as User | null,
    cards: [] as Card[],
    batches: [] as Batch[],
    logs: [] as AccessLog[],
    groups: [] as Group[],
    accountPool: null as AccountPoolData | null,
    dashboard: null as DashboardData | null,
    stockThresholds: [] as StockThreshold[],
    smtp: { enabled: false, host: '', port: 465, username: '', from_email: '', to_email: '', use_ssl: true, use_tls: false, has_password: false } as SMTPSettings,
    securitySummary: null as SecuritySummary | null,
    auditLogs: [] as AuditLog[],
    loginFailures: [] as LoginFailure[],
    sub2api: { base_url: 'http://127.0.0.1:5220', has_api_key: false, has_bearer_token: false } as Sub2APISettings,
    turnstile: { enabled: false, site_key: '', has_secret_key: false } as TurnstileSettings,
    loginTurnstile: { enabled: false, site_key: '' } as LoginTurnstileSettings,
  }),
  actions: {
    async me() {
      const data = await apiGet<{ user: User }>('/api/admin/me')
      this.user = data.user
      return data.user
    },
    async login(username: string, password: string, turnstileToken = '') {
      const data = await apiSend<{ user: User }>('/api/admin/login', 'POST', { username, password, turnstile_token: turnstileToken })
      this.user = data.user
    },
    async logout() {
      await apiSend('/api/admin/logout', 'POST', {})
      this.user = null
    },
    async saveProfile(email: string, avatar: string) {
      const data = await apiSend<{ user: User }>('/api/admin/profile', 'PUT', { email, avatar })
      this.user = data.user
    },
    async changePassword(payload: { current_password: string; new_password: string }) {
      await apiSend('/api/admin/password', 'PUT', payload)
      this.user = null
    },
    async loadSettings() {
      const data = await apiGet<{ settings: Sub2APISettings }>('/api/admin/settings/sub2api')
      this.sub2api = data.settings
    },
    async saveSettings(payload: { base_url: string; api_key: string; bearer_token?: string }) {
      await apiSend('/api/admin/settings/sub2api', 'PUT', payload)
      await this.loadSettings()
    },
    async loadLoginSettings() {
      const data = await apiGet<{ turnstile: LoginTurnstileSettings }>('/api/public/login-settings')
      this.loginTurnstile = data.turnstile
    },
    async loadTurnstileSettings() {
      const data = await apiGet<{ settings: TurnstileSettings }>('/api/admin/settings/turnstile')
      this.turnstile = data.settings
    },
    async saveTurnstileSettings(payload: { enabled: boolean; site_key: string; secret_key?: string }) {
      await apiSend('/api/admin/settings/turnstile', 'PUT', payload)
      await this.loadTurnstileSettings()
      await this.loadLoginSettings()
    },
    async loadDashboard() {
      const data = await apiGet<DashboardData>('/api/admin/dashboard')
      this.dashboard = data
    },
    async loadGroups() {
      const data = await apiGet<{ groups: Group[] }>('/api/admin/sub2api/groups')
      this.groups = data.groups
    },
    async loadAccounts(groupId: string) {
      const data = await apiGet<{ accounts: Record<string, unknown>[] }>(`/api/admin/sub2api/accounts?group_id=${encodeURIComponent(groupId)}`)
      return data.accounts
    },
    async loadAccountPool() {
      const data = await apiGet<AccountPoolData>('/api/admin/account-pool')
      this.accountPool = data
      return data
    },
    async setAccountExtractionStatus(accountId: string, accountName: string, extracted: boolean) {
      await apiSend(`/api/admin/account-pool/${encodeURIComponent(accountId)}/extraction-status`, 'PUT', {
        extracted,
        account_name: accountName,
      })
      await this.loadAccountPool()
    },
    async loadCards(filters: CardFilters = {}) {
      const params = new URLSearchParams()
      if (filters.status && filters.status !== 'all') params.set('status', filters.status)
      if (filters.batch_id) params.set('batch_id', String(filters.batch_id))
      if (filters.group_id) params.set('group_id', filters.group_id)
      if (filters.keyword) params.set('keyword', filters.keyword)
      if (filters.limit) params.set('limit', String(filters.limit))
      const suffix = params.toString() ? `?${params.toString()}` : ''
      const data = await apiGet<{ cards: Card[] }>(`/api/admin/cards${suffix}`)
      this.cards = data.cards
    },
    async loadCardDetail(id: number) {
      return apiGet<{ card: Card; logs: AccessLog[]; allocations: AccountAllocation[] }>(`/api/admin/cards/${id}`)
    },
    async loadBatches() {
      const data = await apiGet<{ batches: Batch[] }>('/api/admin/batches')
      this.batches = data.batches
    },
    async deleteBatch(id: number) {
      await apiSend(`/api/admin/batches/${id}`, 'DELETE')
      this.batches = this.batches.filter((batch) => batch.id !== id)
      this.cards = this.cards.map((card) => (card.batch_id === id ? { ...card, batch_id: undefined, batch_name: '' } : card))
    },
    async deleteBatches(ids: number[]) {
      await apiSend('/api/admin/batches/bulk-delete', 'POST', { ids })
      this.batches = this.batches.filter((batch) => !ids.includes(batch.id))
      this.cards = this.cards.map((card) => (ids.includes(card.batch_id || 0) ? { ...card, batch_id: undefined, batch_name: '' } : card))
    },
    async loadLogs(filters: AccessLogFilters = {}) {
      const params = new URLSearchParams()
      if (filters.card_id) params.set('card_id', String(filters.card_id))
      if (filters.result && filters.result !== 'all') params.set('result', filters.result)
      if (filters.keyword) params.set('keyword', filters.keyword)
      if (filters.limit) params.set('limit', String(filters.limit))
      const suffix = params.toString() ? `?${params.toString()}` : ''
      const data = await apiGet<{ logs: AccessLog[] }>(`/api/admin/logs${suffix}`)
      this.logs = data.logs
    },
    async deleteLogs(ids: number[]) {
      await apiSend('/api/admin/logs/bulk-delete', 'POST', { ids })
      this.logs = this.logs.filter((log) => !ids.includes(log.id))
    },
    async generateCards(payload: unknown) {
      const data = await apiSend<{ cards: Card[] }>('/api/admin/cards/generate', 'POST', payload)
      await this.loadCards()
      await this.loadBatches()
      return data.cards
    },
    async setCardStatus(id: number, status: string) {
      const data = await apiSend<{ card: Card }>(`/api/admin/cards/${id}/status`, 'PUT', { status })
      const index = this.cards.findIndex((card) => card.id === id)
      if (index >= 0) this.cards[index] = { ...this.cards[index], ...data.card }
      else await this.loadCards()
    },
    async bulkSetCardsStatus(ids: number[], status: string) {
      await apiSend('/api/admin/cards/bulk-status', 'POST', { ids, status })
      this.cards = this.cards.map((card) => (ids.includes(card.id) && card.status !== 'used' ? { ...card, status } : card))
    },
    async deleteCard(id: number) {
      await apiSend(`/api/admin/cards/${id}`, 'DELETE')
      await this.loadCards()
    },
    async deleteCards(ids: number[]) {
      await apiSend('/api/admin/cards/bulk-delete', 'POST', { ids })
      this.cards = this.cards.filter((card) => !ids.includes(card.id))
    },
    async loadStockThresholds() {
      const data = await apiGet<{ settings: { thresholds: StockThreshold[] } }>('/api/admin/settings/stock-thresholds')
      this.stockThresholds = data.settings.thresholds
    },
    async saveStockThresholds(thresholds: StockThreshold[]) {
      await apiSend('/api/admin/settings/stock-thresholds', 'PUT', { thresholds })
      await this.loadStockThresholds()
    },
    async checkStock() {
      const data = await apiSend<{ stock: StockSnapshot }>('/api/admin/stock/check', 'POST', {})
      if (this.dashboard) this.dashboard.stock = data.stock
      return data.stock
    },
    async loadSmtpSettings() {
      const data = await apiGet<{ settings: SMTPSettings }>('/api/admin/settings/smtp')
      this.smtp = data.settings
    },
    async saveSmtpSettings(payload: Omit<SMTPSettings, 'has_password'> & { password?: string }) {
      await apiSend('/api/admin/settings/smtp', 'PUT', payload)
      await this.loadSmtpSettings()
    },
    async testSmtpSettings() {
      await apiSend('/api/admin/settings/smtp/test', 'POST', {})
    },
    async loadSecuritySummary() {
      const data = await apiGet<SecuritySummary>('/api/admin/security/summary')
      this.securitySummary = data
    },
    async loadAuditLogs() {
      const data = await apiGet<{ logs: AuditLog[] }>('/api/admin/security/audit-logs?limit=200')
      this.auditLogs = data.logs
    },
    async loadLoginFailures() {
      const data = await apiGet<{ failures: LoginFailure[] }>('/api/admin/security/login-failures?limit=200')
      this.loginFailures = data.failures
    },
  },
})
