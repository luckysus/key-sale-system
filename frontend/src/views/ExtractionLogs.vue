<template>
  <section class="logs-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">提取记录</h1>
      </div>
    </div>

    <a-card class="table-card logs-card" :bordered="false">
      <div class="table-toolbar logs-toolbar">
        <a-input-search
          v-model:value="keyword"
          class="toolbar-search"
          allow-clear
          placeholder="搜索卡密 / IP / 说明"
          @search="load()"
        />
        <a-select v-model:value="resultFilter" class="toolbar-status" :options="resultOptions" @change="load()" />
        <a-button :loading="loading" @click="load()"><ReloadOutlined />刷新</a-button>
        <a-button danger :disabled="!selectedRowKeys.length" :loading="deleting" @click="confirmDelete">
          <DeleteOutlined />批量删除
        </a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="store.logs"
        :row-key="(row: any) => row.id"
        :row-selection="{ selectedRowKeys, onChange: onSelectChange }"
        :scroll="{ x: 1180, y: 'calc(100vh - 300px)' }"
        :pagination="tablePagination"
        size="middle"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'card_code'">
            <span class="code">{{ record.card_code || '-' }}</span>
          </template>
          <template v-else-if="column.key === 'result'">
            <a-tag :color="accessLogResultColor(record.result)">{{ accessLogResultText(record.result) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'message'">
            <span class="ellipsis-cell" :title="accessLogMessageText(record)">{{ accessLogMessageText(record) }}</span>
          </template>
          <template v-else-if="column.key === 'user_agent'">
            <span class="ellipsis-cell" :title="record.user_agent">{{ record.user_agent || '-' }}</span>
          </template>
        </template>
      </a-table>
    </a-card>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { accessLogMessageText, accessLogResultColor, accessLogResultText, formatTime } from '../api/client'
import { useAdminStore } from '../stores/admin'
import { confirmDanger } from '../utils/confirm'

const store = useAdminStore()
const loading = ref(false)
const deleting = ref(false)
const keyword = ref('')
const resultFilter = ref('all')
const selectedRowKeys = ref<number[]>([])

const resultOptions = [
  { value: 'all', label: '全部结果' },
  { value: 'success', label: '成功' },
  { value: 'not_found', label: '无效卡密' },
  { value: 'invalid', label: '格式无效' },
  { value: 'blocked', label: '不可用' },
  { value: 'expired', label: '已过期' },
  { value: 'insufficient', label: '活号不足' },
  { value: 'sub2api_error', label: 'sub2api 错误' },
]

const columns = [
  { title: '时间', key: 'created_at', dataIndex: 'created_at', width: 170 },
  { title: '卡密', key: 'card_code', dataIndex: 'card_code', width: 210 },
  { title: '结果', key: 'result', dataIndex: 'result', width: 110 },
  { title: '说明', key: 'message', dataIndex: 'message', width: 260 },
  { title: 'IP', dataIndex: 'ip', width: 140 },
  { title: '浏览器', key: 'user_agent', dataIndex: 'user_agent', width: 290 },
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

watch([keyword, resultFilter], () => {
  tablePagination.current = 1
})

function onSelectChange(keys: (string | number)[]) {
  selectedRowKeys.value = keys.map(Number).filter((key) => Number.isFinite(key))
}

async function load(silent = false) {
  const quiet = silent === true
  if (!quiet) loading.value = true
  selectedRowKeys.value = []
  try {
    await store.loadLogs({
      keyword: keyword.value.trim(),
      result: resultFilter.value,
      limit: 1000,
    })
  } catch (error) {
    if (!quiet) message.error(error instanceof Error ? error.message : '读取提取记录失败')
  } finally {
    if (!quiet) loading.value = false
  }
}

function confirmDelete() {
  if (!selectedRowKeys.value.length) {
    message.warning('请先选择记录')
    return
  }
  confirmDanger({
    title: `确认删除选中的 ${selectedRowKeys.value.length} 条提取记录？`,
    content: '只删除日志记录，不会删除卡密和账号数据。',
    async onOk() {
      deleting.value = true
      try {
        await store.deleteLogs(selectedRowKeys.value)
        selectedRowKeys.value = []
        await store.loadDashboard().catch(() => undefined)
        message.success('提取记录已删除')
        await load(true)
      } catch (error) {
        message.error(error instanceof Error ? error.message : '删除失败')
        throw error
      } finally {
        deleting.value = false
      }
    },
  })
}

onMounted(() => load(true))
</script>
