<template>
  <section class="account-pool-page">
    <div class="page-header account-pool-head">
      <div>
        <h1 class="page-title">号池管理</h1>
        <span v-if="pool" class="account-pool-updated">最后更新：{{ formatTime(pool.updated_at) }}</span>
      </div>
      <a-button :loading="refreshing" @click="load(false)"><ReloadOutlined />刷新</a-button>
    </div>

    <div v-if="pool" class="account-pool-summary">
      <div><span>真实分组</span><strong>{{ pool.summary.group_count }}</strong></div>
      <div><span>全部账号</span><strong>{{ pool.summary.account_count }}</strong></div>
      <div><span>未提取</span><strong>{{ pool.summary.unallocated_count }}</strong></div>
      <div><span>已提取</span><strong>{{ pool.summary.allocated_count }}</strong></div>
    </div>

    <a-alert v-if="loadError && !pool" type="error" show-icon :message="loadError" />
    <a-spin v-if="initialLoading" class="account-pool-loading" />

    <div v-else-if="pool" class="account-pool-layout">
      <aside class="account-pool-groups" aria-label="账号分组">
        <div class="account-pool-panel-title">账号分组</div>
        <button
          v-for="group in groupItems"
          :key="group.id"
          type="button"
          class="account-pool-group-item"
          :class="{ active: selectedGroup === group.id }"
          @click="selectedGroup = group.id"
        >
          <span>{{ group.name }}</span>
          <strong>{{ group.total }}</strong>
        </button>
      </aside>

      <div class="account-pool-table">
        <div class="table-toolbar account-pool-toolbar">
          <a-input-search v-model:value="keyword" allow-clear placeholder="搜索账号名称 / ID" class="toolbar-search" />
          <a-select v-model:value="allocationFilter" :options="allocationOptions" class="toolbar-status" />
          <a-select v-model:value="statusFilter" :options="statusOptions" class="toolbar-status" />
          <span class="account-pool-result-count">{{ filteredAccounts.length }} 个账号</span>
        </div>

        <a-table
          :columns="columns"
          :data-source="filteredAccounts"
          :row-key="(row: AccountPoolAccount) => row.id"
          :scroll="{ x: 1300, y: 'calc(100vh - 344px)' }"
          :pagination="tablePagination"
          size="middle"
          @change="onTableChange"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'account'">
              <div class="account-pool-account">
                <strong :title="record.name">{{ record.name }}</strong>
                <span>{{ record.id }}</span>
              </div>
            </template>
            <template v-else-if="column.key === 'groups'">
              <div v-if="record.groups.length" class="account-pool-tags">
                <a-tag v-for="group in record.groups" :key="group.id">{{ group.name }}</a-tag>
              </div>
              <a-tag v-else>未分配分组</a-tag>
            </template>
            <template v-else-if="column.key === 'type'">
              {{ [record.type, record.platform].filter(Boolean).join(' / ') || '-' }}
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tooltip :title="record.error_message || undefined">
                <a-tag :color="accountStatusColor(record.status)">{{ accountStatusText(record.status) }}</a-tag>
              </a-tooltip>
            </template>
            <template v-else-if="column.key === 'allocated'">
              <a-tag :color="record.allocated ? 'blue' : 'green'">{{ record.allocated ? '已提取' : '未提取' }}</a-tag>
            </template>
            <template v-else-if="column.key === 'card_code'">
              <span v-if="record.allocation" class="code">{{ record.allocation.card_code }}</span>
              <a-tag v-else-if="record.manual_extracted">手动标记</a-tag>
              <span v-else>-</span>
            </template>
            <template v-else-if="column.key === 'allocated_at'">
              {{ formatTime(record.allocation?.allocated_at || record.manual_extracted_at) }}
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-button
                type="link"
                size="small"
                :danger="record.allocated"
                :loading="statusChanging === record.id"
                :disabled="statusChanging !== null && statusChanging !== record.id"
                @click="askChangeExtraction(record)"
              >
                {{ record.allocated ? '设为未提取' : '标记已提取' }}
              </a-button>
            </template>
          </template>
        </a-table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { formatTime, type AccountPoolAccount } from '../api/client'
import { useAdminStore } from '../stores/admin'
import { confirmDanger } from '../utils/confirm'

const store = useAdminStore()
const selectedGroup = ref('all')
const keyword = ref('')
const allocationFilter = ref('all')
const statusFilter = ref('all')
const refreshing = ref(false)
const initialLoading = ref(!store.accountPool)
const loadError = ref('')
const statusChanging = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | undefined

const pool = computed(() => store.accountPool)
const unassignedCount = computed(() => pool.value?.accounts.filter((account) => account.groups.length === 0).length || 0)
const groupItems = computed(() => [
  { id: 'all', name: '全部分组', total: pool.value?.summary.account_count || 0 },
  { id: 'unassigned', name: '未分配分组', total: unassignedCount.value },
  ...(pool.value?.groups || []).map((group) => ({ id: group.id, name: group.name, total: group.total })),
])
const filteredAccounts = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return (pool.value?.accounts || []).filter((account) => {
    const matchesGroup = selectedGroup.value === 'all'
      || (selectedGroup.value === 'unassigned' ? account.groups.length === 0 : account.groups.some((group) => group.id === selectedGroup.value))
    const matchesQuery = !query || account.name.toLowerCase().includes(query) || account.id.toLowerCase().includes(query)
    const matchesAllocation = allocationFilter.value === 'all'
      || (allocationFilter.value === 'allocated' ? account.allocated : !account.allocated)
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'active' ? account.status === 'active' : account.status !== 'active')
    return matchesGroup && matchesQuery && matchesAllocation && matchesStatus
  })
})

const allocationOptions = [
  { value: 'all', label: '全部提取状态' },
  { value: 'unallocated', label: '未提取' },
  { value: 'allocated', label: '已提取' },
]
const statusOptions = [
  { value: 'all', label: '全部账号状态' },
  { value: 'active', label: '正常' },
  { value: 'other', label: '其他状态' },
]
const columns = [
  { title: '账号', key: 'account', width: 230 },
  { title: '所属分组', key: 'groups', width: 210 },
  { title: '类型', key: 'type', width: 140 },
  { title: '账号状态', key: 'status', width: 110 },
  { title: '提取状态', key: 'allocated', width: 100 },
  { title: '对应卡密', key: 'card_code', width: 220 },
  { title: '提取时间', key: 'allocated_at', width: 170 },
  { title: '操作', key: 'actions', width: 120, fixed: 'right' as const },
]
const tablePagination = reactive({
  current: 1,
  pageSize: 50,
  hideOnSinglePage: true,
  showSizeChanger: true,
  showTotal: (total: number) => `共 ${total} 条`,
})

function onTableChange(pagination: { current?: number; pageSize?: number }) {
  tablePagination.current = pagination.current || 1
  tablePagination.pageSize = pagination.pageSize || tablePagination.pageSize
}

watch([selectedGroup, keyword, allocationFilter, statusFilter], () => {
  tablePagination.current = 1
})

function accountStatusText(status: string) {
  return ({ active: '正常', disabled: '已禁用', error: '异常' } as Record<string, string>)[status] || status || '未知'
}

function accountStatusColor(status: string) {
  return ({ active: 'green', disabled: 'default', error: 'red' } as Record<string, string>)[status] || 'orange'
}

function extractionConfirmText(account: AccountPoolAccount) {
  return account.allocated
    ? '设为未提取后，账号会重新进入可售号池；原卡密仍保持已使用。确定继续？'
    : '确定标记为已提取？该账号将不再参与卡密提取。'
}

async function changeExtractionStatus(account: AccountPoolAccount) {
  if (statusChanging.value) return
  statusChanging.value = account.id
  try {
    await store.setAccountExtractionStatus(account.id, account.name, !account.allocated)
    message.success(account.allocated ? '账号已设为未提取' : '账号已标记为已提取')
    await load(true)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '修改提取状态失败')
    throw error
  } finally {
    statusChanging.value = null
  }
}

function askChangeExtraction(account: AccountPoolAccount) {
  confirmDanger({
    title: extractionConfirmText(account),
    okText: '确定',
    async onOk() {
      await changeExtractionStatus(account)
    },
  })
}

async function load(silent: boolean) {
  if (refreshing.value) return
  if (!silent) refreshing.value = true
  try {
    await store.loadAccountPool()
    loadError.value = ''
  } catch (error) {
    const text = error instanceof Error ? error.message : '读取号池失败'
    if (!pool.value) loadError.value = text
    if (!silent) message.error(text)
  } finally {
    initialLoading.value = false
    if (!silent) refreshing.value = false
  }
}

onMounted(() => {
  void load(Boolean(store.accountPool))
  refreshTimer = setInterval(() => void load(true), 30_000)
})

onBeforeUnmount(() => clearInterval(refreshTimer))
</script>
