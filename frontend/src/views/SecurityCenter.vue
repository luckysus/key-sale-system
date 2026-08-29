<template>
  <section class="security-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">安全中心</h1>
      </div>
      <a-button :loading="loading" @click="load()"><ReloadOutlined />刷新</a-button>
    </div>

    <div class="security-overview">
      <a-card v-for="item in metrics" :key="item.label" class="summary-card" :bordered="false">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </a-card>
    </div>

    <div class="security-layout">
      <a-card title="后台操作日志" class="table-card security-audit-card" :bordered="false">
        <a-table :columns="auditColumns" :data-source="auditRows" :row-key="(row: any) => row.id" size="middle" :scroll="{ y: 'calc(100vh - 330px)' }" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'created_at'">{{ formatTime(record.created_at) }}</template>
            <template v-else-if="column.key === 'action'">{{ auditActionText(record.action) }}</template>
            <template v-else-if="column.key === 'target'">{{ auditTargetText(record.target) }}</template>
            <template v-else-if="column.key === 'result'">
              <a-tag :color="record.result === 'ok' ? 'green' : 'red'">{{ record.result === 'ok' ? '成功' : '失败' }}</a-tag>
            </template>
          </template>
        </a-table>
      </a-card>

      <div class="security-side">
        <a-card title="异常 IP" class="table-card security-side-card" :bordered="false">
          <a-table
            :columns="abnormalColumns"
            :data-source="abnormalIps"
            :row-key="(row: any) => `${row.ip}-${row.type}`"
            size="middle"
            :scroll="{ y: 'calc((100vh - 420px) / 2)' }"
            :pagination="false"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'type'">
                <a-tag :color="record.type === 'login_failed' ? 'orange' : 'red'">
                  {{ record.type === 'login_failed' ? '登录失败' : '提取失败' }}
                </a-tag>
              </template>
              <template v-else-if="column.key === 'updated_at'">
                {{ formatTime(record.updated_at) }}
              </template>
            </template>
          </a-table>
        </a-card>

        <a-card title="登录失败" class="table-card security-side-card" :bordered="false">
          <a-table :columns="failureColumns" :data-source="failureRows" :row-key="(row: any) => row.key" size="middle" :scroll="{ y: 'calc((100vh - 420px) / 2)' }" :pagination="false">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'updated_at'">{{ formatTime(record.updated_at) }}</template>
              <template v-else-if="column.key === 'locked_until'">{{ formatTime(record.locked_until) }}</template>
            </template>
          </a-table>
        </a-card>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { auditActionText, auditTargetText, formatTime } from '../api/client'
import { useAdminStore } from '../stores/admin'

const store = useAdminStore()
const loading = ref(false)
const summary = computed(() => store.securitySummary)
const abnormalIps = computed(() => summary.value?.abnormal_ips || [])
const auditRows = computed(() => store.auditLogs)
const failureRows = computed(() => store.loginFailures)
const metrics = computed(() => [
  { label: '登录防护', value: summary.value?.turnstile.enabled ? '已启用' : '未启用' },
  { label: '异常 IP', value: summary.value?.abnormal_ips.length || 0 },
  { label: '登录失败记录', value: store.loginFailures.length },
  { label: '后台操作日志', value: store.auditLogs.length },
])

const abnormalColumns = [
  { title: 'IP', dataIndex: 'ip', width: 150 },
  { title: '类型', key: 'type', dataIndex: 'type', width: 110 },
  { title: '次数', dataIndex: 'count', width: 72 },
  { title: '最近时间', key: 'updated_at', dataIndex: 'updated_at', width: 165 },
]
const auditColumns = [
  { title: '时间', key: 'created_at', dataIndex: 'created_at', width: 165 },
  { title: '操作', key: 'action', dataIndex: 'action', width: 140 },
  { title: '目标', key: 'target', dataIndex: 'target' },
  { title: '结果', key: 'result', dataIndex: 'result', width: 82 },
]
const failureColumns = [
  { title: 'IP', dataIndex: 'ip', width: 135 },
  { title: '账号', dataIndex: 'username', width: 120 },
  { title: '次数', dataIndex: 'failures', width: 72 },
  { title: '锁定至', key: 'locked_until', dataIndex: 'locked_until', width: 150 },
  { title: '更新时间', key: 'updated_at', dataIndex: 'updated_at', width: 150 },
]

async function load(silent = false) {
  const quiet = silent === true
  if (!quiet) loading.value = true
  try {
    await Promise.all([store.loadSecuritySummary(), store.loadAuditLogs(), store.loadLoginFailures()])
  } catch (error) {
    if (!quiet) message.error(error instanceof Error ? error.message : '安全数据加载失败')
  } finally {
    if (!quiet) loading.value = false
  }
}

onMounted(() => load(true))
</script>
