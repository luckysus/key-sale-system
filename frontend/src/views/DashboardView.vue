<template>
  <section class="dashboard-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">仪表盘</h1>
      </div>
      <a-space>
      <a-button :loading="loading" @click="load()"><ReloadOutlined />刷新</a-button>
        <a-button type="primary" :loading="checkingStock" @click="checkStock">刷新库存</a-button>
      </a-space>
    </div>

    <div class="metric-grid">
      <a-card v-for="item in metrics" :key="item.label" class="metric-tile" :bordered="false">
        <div class="metric-title">{{ item.label }}</div>
        <div class="metric-number" :class="item.tone">{{ item.value }}</div>
      </a-card>
    </div>

    <a-row :gutter="12" class="dashboard-main">
      <a-col :xs="24" :xl="15">
        <a-card title="30 天提取趋势" class="table-card panel-card" :bordered="false">
          <div v-if="trendRows.length" class="trend-chart" @mouseleave="hoveredTrendIndex = null">
            <div class="trend-legend" aria-label="趋势图图例">
              <span><i class="success"></i>成功</span>
              <span><i class="failed"></i>失败</span>
            </div>
            <svg viewBox="0 0 900 160" preserveAspectRatio="none" role="img" aria-label="30 天提取成功和失败趋势图">
              <line v-for="y in [12, 46, 80, 114, 148]" :key="y" x1="12" :y1="y" x2="888" :y2="y" class="trend-grid-line" />
              <path :d="successPath" class="trend-line success" />
              <path :d="failedPath" class="trend-line failed" />
              <rect
                v-for="(row, index) in trendRows"
                :key="row.date"
                :x="(index * 900) / trendRows.length"
                y="0"
                :width="900 / trendRows.length"
                height="160"
                class="trend-hit-area"
                @mouseenter="hoveredTrendIndex = index"
              />
            </svg>
            <div class="trend-date-axis" aria-hidden="true">
              <span v-for="label in trendDateLabels" :key="label.date" :style="{ left: `${label.left}%` }">{{ label.text }}</span>
            </div>
            <div v-if="hoveredTrend" class="trend-tooltip" :class="trendTooltipEdge" :style="{ left: `${trendTooltipLeft}%` }">
              <strong>{{ hoveredTrend.date }}</strong>
              <span>成功：{{ hoveredTrend.success }}</span>
              <span>失败：{{ hoveredTrend.failed }}</span>
            </div>
          </div>
          <a-empty v-else description="暂无提取趋势" />
        </a-card>
      </a-col>
      <a-col :xs="24" :xl="9">
        <a-card title="库存提醒" class="table-card panel-card" :bordered="false">
          <a-empty v-if="!stockWarnings.length" description="暂无库存预警" />
          <a-list v-else :data-source="stockWarnings" size="small">
            <template #renderItem="{ item }">
              <a-list-item>
                <a-list-item-meta>
                  <template #title>{{ item.group_name }}</template>
                  <template #description>可用 {{ item.available }} / 阈值 {{ item.min_available }}</template>
                </a-list-item-meta>
                <a-tag color="red">不足</a-tag>
              </a-list-item>
            </template>
          </a-list>
          <div class="stock-updated">更新时间：{{ formatTime(dashboard?.stock?.updated_at) }}</div>
        </a-card>
      </a-col>
    </a-row>

    <a-card ref="logCardRef" title="最近提取记录" class="table-card panel-card dashboard-log-card" :bordered="false">
      <a-table
        class="dashboard-log-table"
        :columns="logColumns"
        :data-source="recentLogs"
        :row-key="(row: any) => row.id"
        size="middle"
        :scroll="{ x: 900, y: logTableBodyHeight }"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'card_code'">
            <span class="code">{{ record.card_code || '-' }}</span>
          </template>
          <template v-else-if="column.key === 'result'">
            <a-tag :color="accessLogResultColor(record.result)">{{ accessLogResultText(record.result) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'message'">
            {{ accessLogMessageText(record) }}
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ formatTime(record.created_at) }}
          </template>
        </template>
      </a-table>
    </a-card>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { accessLogMessageText, accessLogResultColor, accessLogResultText, formatTime } from '../api/client'
import { useAdminStore } from '../stores/admin'
import { trendPath } from '../utils/trendChart'

const store = useAdminStore()
const loading = ref(false)
const checkingStock = ref(false)
const hoveredTrendIndex = ref<number | null>(null)
const logTableBodyHeight = ref(240)
const logCardRef = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
let logCardObserver: ResizeObserver | undefined

function updateLogTableBodyHeight() {
  const card = (logCardRef.value as { $el?: HTMLElement } | null)?.$el || logCardRef.value as HTMLElement | null
  const body = card?.querySelector<HTMLElement>('.ant-card-body')
  if (body) logTableBodyHeight.value = Math.max(120, body.clientHeight - 2)
}

const dashboard = computed(() => store.dashboard)
const stockWarnings = computed(() => dashboard.value?.stock?.warnings || [])
const recentLogs = computed(() => dashboard.value?.recent_logs || [])
const trendRows = computed(() => dashboard.value?.trend || [])
const maxTrend = computed(() => Math.max(1, ...trendRows.value.flatMap((row) => [row.success, row.failed])))
const successPath = computed(() => trendPath(trendRows.value.map((row) => row.success), 900, 160, 12, maxTrend.value))
const failedPath = computed(() => trendPath(trendRows.value.map((row) => row.failed), 900, 160, 12, maxTrend.value))
const hoveredTrend = computed(() => hoveredTrendIndex.value === null ? null : trendRows.value[hoveredTrendIndex.value])
const trendTooltipLeft = computed(() => {
  if (hoveredTrendIndex.value === null || trendRows.value.length < 2) return 0
  return (hoveredTrendIndex.value / (trendRows.value.length - 1)) * 100
})
const trendTooltipEdge = computed(() => {
  if (hoveredTrendIndex.value === 0) return 'at-start'
  if (hoveredTrendIndex.value === trendRows.value.length - 1) return 'at-end'
  return ''
})
const trendDateLabels = computed(() => {
  const rows = trendRows.value
  if (!rows.length) return []
  const count = Math.min(6, rows.length)
  return Array.from({ length: count }, (_, position) => {
    const index = Math.round((position * (rows.length - 1)) / Math.max(1, count - 1))
    return {
      date: rows[index].date,
      text: rows[index].date.slice(5).replace('-', '/'),
      left: (index / Math.max(1, rows.length - 1)) * 100,
    }
  })
})
const metrics = computed(() => [
  { label: '全部卡密', value: dashboard.value?.overview.total_cards || 0, tone: 'tone-indigo' },
  { label: '未使用', value: dashboard.value?.overview.unused_cards || 0, tone: 'tone-blue' },
  { label: '已使用', value: dashboard.value?.overview.used_cards || 0, tone: 'tone-green' },
  { label: '已禁用', value: dashboard.value?.overview.disabled_cards || 0, tone: 'tone-orange' },
  { label: '今日成功', value: dashboard.value?.overview.today_success || 0, tone: 'tone-cyan' },
  { label: '今日失败', value: dashboard.value?.overview.today_failed || 0, tone: 'tone-red' },
])
const logColumns = [
  { title: '时间', key: 'created_at', dataIndex: 'created_at', width: 170 },
  { title: '卡密', key: 'card_code', dataIndex: 'card_code', width: 210 },
  { title: '结果', key: 'result', dataIndex: 'result', width: 110 },
  { title: '说明', key: 'message', dataIndex: 'message' },
  { title: 'IP', dataIndex: 'ip', width: 140 },
]

async function load(silent = false) {
  const quiet = silent === true
  if (!quiet) loading.value = true
  try {
    await store.loadDashboard()
  } catch (error) {
    if (!quiet) message.error(error instanceof Error ? error.message : '仪表盘加载失败')
  } finally {
    if (!quiet) loading.value = false
  }
}

async function checkStock() {
  checkingStock.value = true
  try {
    await store.checkStock()
    message.success('库存已刷新')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '库存刷新失败')
  } finally {
    checkingStock.value = false
  }
}

onMounted(async () => {
  await load(true)
  await nextTick()
  updateLogTableBodyHeight()
  const card = (logCardRef.value as { $el?: HTMLElement } | null)?.$el || logCardRef.value as HTMLElement | null
  if (card) {
    logCardObserver = new ResizeObserver(updateLogTableBodyHeight)
    logCardObserver.observe(card)
  }
})

onBeforeUnmount(() => logCardObserver?.disconnect())
</script>
