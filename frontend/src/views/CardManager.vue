<template>
  <section>
    <div class="page-header">
      <div>
        <h1 class="page-title">卡密管理</h1>
      </div>
      <a-space>
        <a-button type="primary" @click="openGenerate"><PlusOutlined />生成卡密</a-button>
        <a-button @click="batchOpen = true"><BarsOutlined />批次管理</a-button>
      </a-space>
    </div>

    <a-card class="table-card" :bordered="false">
      <div class="table-toolbar card-toolbar">
        <a-input-search v-model:value="query" allow-clear placeholder="搜索卡密 / 分组 / 使用者" class="toolbar-search" @search="loadAll" />
        <a-select v-model:value="statusFilter" :options="statusOptions" class="toolbar-status" @change="loadAll" />
        <a-select v-model:value="batchFilter" :options="batchOptions" allow-clear placeholder="批次" class="toolbar-status" @change="loadAll" />
        <a-select v-model:value="groupFilter" :options="groupOptions" allow-clear placeholder="分组" class="toolbar-status" @change="loadAll" />
        <a-button :loading="loading" @click="loadAll()"><ReloadOutlined />刷新</a-button>
        <a-button :disabled="!selectedRowKeys.length" @click="exportCards(selectedCards, 'selected-cards.csv')"><DownloadOutlined />导出选中</a-button>
        <a-button danger :disabled="!selectedRowKeys.length" :loading="deleting" @click="askDeleteSelected">
          <DeleteOutlined />
          批量删除
        </a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="store.cards"
        :row-key="(row: any) => row.id"
        :row-selection="rowSelection"
        :scroll="{ x: 1180, y: 'calc(100vh - 300px)' }"
        :pagination="tablePagination"
        size="middle"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'code'">
            <a-space>
              <span class="code">{{ record.code }}</span>
              <a-tooltip v-if="record.status === 'unused'" title="复制卡密提取信息">
                <a-button type="text" size="small" class="copy-icon-button" @click="copyCards([record.code])">
                  <CopyOutlined />
                </a-button>
              </a-tooltip>
            </a-space>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusText(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'used_at'">
            {{ formatTime(record.used_at) }}
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'actions'">
            <a-space>
              <a-button size="small" @click="showDetail(record)">详情</a-button>
              <a-button
                v-if="record.status === 'disabled'"
                size="small"
                :disabled="statusChanging === record.id"
                @click="changeStatus(record, 'unused')"
              >
                启用
              </a-button>
              <a-button
                v-else
                size="small"
                :disabled="record.status === 'used' || statusChanging === record.id"
                @click="askDisable(record)"
              >
                禁用
              </a-button>
              <a-button size="small" danger @click="askDeleteOne(record.id)">删除</a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <BatchManager v-model:open="batchOpen" />

    <a-modal v-model:open="generateOpen" title="生成卡密" width="640px" @ok="generate" :confirm-loading="generating">
      <a-form layout="vertical">
        <a-form-item label="sub2api 分组">
          <a-space-compact block>
            <a-select v-model:value="form.group_id" :options="groupOptions" show-search placeholder="请选择分组" />
            <a-button @click="loadGroups">读取分组</a-button>
          </a-space-compact>
        </a-form-item>
        <a-row :gutter="12">
          <a-col :span="12">
            <a-form-item label="每个卡密提取账号数量">
              <a-input-number v-model:value="form.account_count" :min="1" :max="200" class="wide" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="生成卡密数量">
              <a-input-number v-model:value="form.generate_count" :min="1" :max="500" class="wide" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="批次名称">
          <a-input v-model:value="form.batch_name" placeholder="留空则按分组自动创建" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="generatedOpen" width="720px">
      <template #title>新生成的卡密（{{ generatedCards.length }} 张）</template>
      <a-textarea :value="generatedText" class="generated-card-output" :rows="12" readonly />
      <template #footer>
        <a-button @click="generatedOpen = false">关闭</a-button>
        <a-button type="primary" @click="copyCards(generatedCards.map((card) => card.code))">
          <CopyOutlined />复制全部
        </a-button>
      </template>
    </a-modal>

    <a-modal v-model:open="detailOpen" title="卡密详情" width="780px" :footer="null">
      <a-spin :spinning="detailLoading">
        <template v-if="detailData">
          <a-descriptions bordered :column="2" size="small" class="mb16">
            <a-descriptions-item label="卡密">{{ detailData.card.code }}</a-descriptions-item>
            <a-descriptions-item label="状态">{{ statusText(detailData.card.status) }}</a-descriptions-item>
            <a-descriptions-item label="批次">{{ detailData.card.batch_name || '-' }}</a-descriptions-item>
            <a-descriptions-item label="分组">{{ detailData.card.group_name }}</a-descriptions-item>
            <a-descriptions-item label="账号数量">{{ detailData.card.account_count }}</a-descriptions-item>
            <a-descriptions-item label="使用者">{{ detailData.card.used_by || '-' }}</a-descriptions-item>
            <a-descriptions-item label="使用时间">{{ formatTime(detailData.card.used_at) }}</a-descriptions-item>
            <a-descriptions-item label="创建时间">{{ formatTime(detailData.card.created_at) }}</a-descriptions-item>
          </a-descriptions>

          <a-tabs>
            <a-tab-pane key="allocations" tab="分配账号">
              <a-table :columns="allocationColumns" :data-source="detailData.allocations" :row-key="(row: any) => row.id" size="small" :scroll="{ y: 260 }" :pagination="false">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'allocated_at'">{{ formatTime(record.allocated_at) }}</template>
                </template>
              </a-table>
            </a-tab-pane>
            <a-tab-pane key="logs" tab="提取记录">
              <a-table :columns="logColumns" :data-source="detailData.logs" :row-key="(row: any) => row.id" size="small" :scroll="{ y: 260 }" :pagination="{ pageSize: 5, showSizeChanger: false }">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'created_at'">{{ formatTime(record.created_at) }}</template>
                  <template v-else-if="column.key === 'result'"><a-tag :color="record.result === 'success' ? 'green' : 'red'">{{ resultText(record.result) }}</a-tag></template>
                </template>
              </a-table>
            </a-tab-pane>
          </a-tabs>
        </template>
      </a-spin>
    </a-modal>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { BarsOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { csvSafeCell, formatTime, type AccountAllocation, type AccessLog, type Card } from '../api/client'
import { useAdminStore } from '../stores/admin'
import { formatCardDeliveryInfo } from '../utils/cardDelivery'
import { confirmDanger } from '../utils/confirm'
import BatchManager from './BatchManager.vue'

const store = useAdminStore()
const generateOpen = ref(false)
const batchOpen = ref(false)
const generating = ref(false)
const generatedOpen = ref(false)
const generatedCards = ref<Card[]>([])
const detailOpen = ref(false)
const detailLoading = ref(false)
const loading = ref(false)
const deleting = ref(false)
const statusChanging = ref<number | null>(null)
const detailData = ref<{ card: Card; logs: AccessLog[]; allocations: AccountAllocation[] } | null>(null)
const query = ref('')
const statusFilter = ref('all')
const batchFilter = ref<number | undefined>()
const groupFilter = ref<string | undefined>()
const selectedRowKeys = ref<number[]>([])
const form = reactive({
  group_id: '',
  account_count: 1,
  generate_count: 1,
  batch_name: '',
})
const columns = [
  { title: '卡密', key: 'code', dataIndex: 'code', width: 230 },
  { title: '批次', dataIndex: 'batch_name', width: 180 },
  { title: '分组', dataIndex: 'group_name', width: 150 },
  { title: '账号数', dataIndex: 'account_count', width: 90 },
  { title: '使用者', dataIndex: 'used_by', width: 130 },
  { title: '状态', key: 'status', dataIndex: 'status', width: 100 },
  { title: '使用时间', key: 'used_at', dataIndex: 'used_at', width: 165 },
  { title: '创建时间', key: 'created_at', dataIndex: 'created_at', width: 165 },
  { title: '操作', key: 'actions', fixed: 'right', width: 210 },
]
const allocationColumns = [
  { title: '账号 ID', dataIndex: 'sub2api_account_id' },
  { title: '账号名', dataIndex: 'account_name' },
  { title: '状态', dataIndex: 'test_status', width: 100 },
  { title: '分配时间', key: 'allocated_at', dataIndex: 'allocated_at', width: 170 },
]
const logColumns = [
  { title: '时间', key: 'created_at', dataIndex: 'created_at', width: 170 },
  { title: '结果', key: 'result', dataIndex: 'result', width: 110 },
  { title: '说明', dataIndex: 'message' },
  { title: 'IP', dataIndex: 'ip', width: 140 },
]
const tablePagination = reactive({
  current: 1,
  pageSize: 20,
  showSizeChanger: true,
  showTotal: (total: number) => `共 ${total} 条`,
})
function onTableChange(pagination: { current?: number; pageSize?: number }) {
  tablePagination.current = pagination.current || 1
  tablePagination.pageSize = pagination.pageSize || tablePagination.pageSize
}

watch([query, statusFilter, batchFilter, groupFilter], () => {
  tablePagination.current = 1
})

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'unused', label: '未使用' },
  { value: 'used', label: '已使用' },
  { value: 'disabled', label: '已禁用' },
]
const batchOptions = computed(() => store.batches.map((batch) => ({ value: batch.id, label: batch.name })))
const groupOptions = computed(() => {
  const map = new Map<string, string>()
  for (const group of store.groups) map.set(group.id, group.name)
  for (const card of store.cards) map.set(card.group_id, card.group_name)
  return Array.from(map.entries()).map(([value, label]) => ({ value, label }))
})
const selectedCards = computed(() => store.cards.filter((card) => selectedRowKeys.value.includes(card.id)))
const generatedText = computed(() => formatCardDeliveryInfo(generatedCards.value.map((card) => card.code)))
const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: (keys: (string | number)[]) => {
    selectedRowKeys.value = keys.map(Number)
  },
}))

function statusText(status: string) {
  return ({ unused: '未使用', used: '已使用', disabled: '已禁用' } as Record<string, string>)[status] || status
}
function statusColor(status: string) {
  return ({ unused: 'green', used: 'blue', disabled: 'red' } as Record<string, string>)[status] || 'default'
}
function resultText(result: string) {
  return ({ success: '成功', invalid: '无效', not_found: '不存在', blocked: '不可用', expired: '已过期', insufficient: '活号不足', sub2api_error: 'sub2api 错误' } as Record<string, string>)[result] || result
}
async function showDetail(card: Card) {
  detailOpen.value = true
  detailLoading.value = true
  try {
    detailData.value = await store.loadCardDetail(card.id)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '详情读取失败')
  } finally {
    detailLoading.value = false
  }
}
async function copyCards(codes: string[]) {
  const text = formatCardDeliveryInfo(codes)
  if (!text) return
  await navigator.clipboard.writeText(text)
  message.success('已复制')
}
async function changeStatus(card: Card, status: string) {
  if (statusChanging.value) return
  statusChanging.value = card.id
  try {
    await store.setCardStatus(card.id, status)
    message.success(status === 'disabled' ? '卡密已禁用' : '卡密已启用')
    await loadAll(true)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '操作失败')
  } finally {
    statusChanging.value = null
  }
}

function askDisable(card: Card) {
  if (card.status === 'used') return
  confirmDanger({
    title: '禁用后买家不能使用这个卡密，确定禁用？',
    okText: '禁用',
    async onOk() {
      await changeStatus(card, 'disabled')
    },
  })
}
async function loadAll(silent = false) {
  const quiet = silent === true
  if (!quiet) loading.value = true
  try {
    await Promise.all([
      store.loadCards({
        status: statusFilter.value,
        batch_id: batchFilter.value,
        group_id: groupFilter.value,
        keyword: query.value.trim(),
        limit: 1000,
      }),
      store.loadBatches(),
    ])
  } catch (error) {
    if (!quiet) message.error(error instanceof Error ? error.message : '刷新失败')
  } finally {
    if (!quiet) loading.value = false
  }
}
async function loadGroups() {
  try {
    await store.loadGroups()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '读取分组失败')
  }
}
async function openGenerate() {
  generateOpen.value = true
  if (!store.groups.length) await loadGroups()
}
async function generate() {
  const group = store.groups.find((item) => item.id === form.group_id)
  if (!group) {
    message.warning('请选择 sub2api 分组')
    return
  }
  generating.value = true
  try {
    generatedCards.value = await store.generateCards({
      ...form,
      group_name: group.name,
      batch_name: form.batch_name || `${group.name} 批次`,
    })
    message.success('卡密已生成')
    generateOpen.value = false
    generatedOpen.value = true
    await loadAll(true)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '生成失败')
  } finally {
    generating.value = false
  }
}

function exportCards(cards: Card[], filename: string) {
  const rows = cards.map((card) => [
    card.code,
    card.batch_name || '',
    card.group_name,
    card.account_count,
    statusText(card.status),
    card.used_by || '',
    formatTime(card.used_at),
    formatTime(card.created_at),
  ])
  const csv = [['卡密', '批次', '分组', '账号数', '状态', '使用者', '使用时间', '创建时间'], ...rows]
    .map((row) => row.map((item) => `"${csvSafeCell(item).replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function deleteOne(id: number) {
  try {
    await store.deleteCard(id)
    selectedRowKeys.value = selectedRowKeys.value.filter((item) => item !== id)
    message.success('卡密已删除')
    await loadAll(true)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '删除失败')
    throw error
  }
}

async function deleteSelected() {
  if (!selectedRowKeys.value.length) return
  deleting.value = true
  try {
    await store.deleteCards(selectedRowKeys.value)
    selectedRowKeys.value = []
    message.success('已删除选中卡密')
    await loadAll(true)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '批量删除失败')
    throw error
  } finally {
    deleting.value = false
  }
}

function askDeleteOne(id: number) {
  confirmDanger({
    title: '确定删除这个卡密？',
    content: '删除后不可恢复。',
    async onOk() {
      await deleteOne(id)
    },
  })
}

function askDeleteSelected() {
  if (!selectedRowKeys.value.length) {
    message.warning('请先选择卡密')
    return
  }
  confirmDanger({
    title: '确定删除选中的卡密？',
    content: `将删除 ${selectedRowKeys.value.length} 个卡密，删除后不可恢复。`,
    async onOk() {
      await deleteSelected()
    },
  })
}

onMounted(async () => {
  await loadAll(true)
  await loadGroups()
})
</script>
