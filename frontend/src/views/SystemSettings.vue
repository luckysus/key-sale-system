<template>
  <section class="settings-page">
    <div class="page-header settings-head">
      <div>
        <h1 class="page-title">系统设置</h1>
      </div>
    </div>

    <a-tabs v-model:activeKey="activeTab" class="settings-tabs">
      <a-tab-pane key="sub2api" tab="sub2api 连接">
        <a-card class="table-card settings-table-card" :bordered="false">
          <div class="settings-table">
            <div class="settings-row settings-row-head">
              <div>配置项</div>
              <div>值</div>
              <div>说明</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">sub2api 地址</div>
              <div><a-input v-model:value="form.base_url" placeholder="http://127.0.0.1:5220" /></div>
              <div class="settings-desc">建议填写服务器本机地址，避免绕公网域名。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">管理员密钥 x-api-key</div>
              <div><a-input-password v-model:value="form.api_key" placeholder="保存后不回显，留空会清除" /></div>
              <div class="settings-desc">用于读取分组、拉取账号和实时验活。</div>
            </div>
          </div>
          <div class="settings-actions">
            <a-button type="primary" :loading="saving" @click="save">保存设置</a-button>
            <a-button :loading="loadingGroups" @click="testGroups">读取分组测试</a-button>
          </div>
        </a-card>
      </a-tab-pane>

      <a-tab-pane key="security" tab="登录防护">
        <a-card class="table-card settings-table-card" :bordered="false">
          <div class="settings-table">
            <div class="settings-row settings-row-head">
              <div>配置项</div>
              <div>值</div>
              <div>说明</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">启用 Turnstile</div>
              <div><a-switch v-model:checked="turnstileForm.enabled" /></div>
              <div class="settings-desc">只保护后台登录，买家提取页不启用。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">站点密钥</div>
              <div><a-input v-model:value="turnstileForm.site_key" placeholder="Cloudflare Turnstile 站点密钥" /></div>
              <div class="settings-desc">Cloudflare 控制台生成的站点密钥。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">私密密钥</div>
              <div>
                <a-input-password
                  v-model:value="turnstileForm.secret_key"
                  :placeholder="store.turnstile.has_secret_key ? '已保存，留空保留当前密钥' : 'Cloudflare Turnstile 私密密钥'"
                />
              </div>
              <div class="settings-desc">后端加密保存，不会回显到浏览器。</div>
            </div>
          </div>
          <div class="settings-actions">
            <a-button type="primary" :loading="savingTurnstile" @click="saveTurnstile">保存防护设置</a-button>
          </div>
        </a-card>
      </a-tab-pane>

      <a-tab-pane key="stock" tab="库存预警">
        <a-card class="table-card settings-table-card" :bordered="false">
          <div class="settings-inline-toolbar">
            <a-select v-model:value="stockGroupId" :options="groupOptions" show-search placeholder="选择分组" class="stock-group-select" />
            <a-button @click="addStockRow">添加分组</a-button>
            <a-button :loading="loadingGroups" @click="testGroups">读取分组</a-button>
            <a-button :loading="checkingStock" @click="checkStock">立即检查库存</a-button>
          </div>
          <a-table :columns="stockColumns" :data-source="stockRows" :row-key="(row: any) => row.group_id" size="middle" :scroll="{ y: 320 }" :pagination="false">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'enabled'">
                <a-switch v-model:checked="record.enabled" />
              </template>
              <template v-else-if="column.key === 'min_available'">
                <a-input-number v-model:value="record.min_available" :min="0" :max="100000" />
              </template>
              <template v-else-if="column.key === 'actions'">
                <a-button type="text" danger @click="removeStockRow(record.group_id)">删除</a-button>
              </template>
            </template>
          </a-table>
          <div class="settings-actions">
            <a-button type="primary" :loading="savingStock" @click="saveStock">保存库存预警</a-button>
          </div>
        </a-card>
      </a-tab-pane>

      <a-tab-pane key="smtp" tab="邮件通知">
        <a-card class="table-card settings-table-card" :bordered="false">
          <div class="settings-table">
            <div class="settings-row settings-row-head">
              <div>配置项</div>
              <div>值</div>
              <div>说明</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">启用通知</div>
              <div><a-switch v-model:checked="smtpForm.enabled" /></div>
              <div class="settings-desc">库存不足、sub2api 失败和异常提取时发送邮件。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">SMTP 主机</div>
              <div><a-input v-model:value="smtpForm.host" placeholder="smtp.example.com" /></div>
              <div class="settings-desc">邮箱服务商提供的 SMTP 地址。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">端口</div>
              <div><a-input-number v-model:value="smtpForm.port" :min="1" :max="65535" class="wide" /></div>
              <div class="settings-desc">常见 SSL 端口为 465，TLS 端口为 587。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">账号</div>
              <div><a-input v-model:value="smtpForm.username" /></div>
              <div class="settings-desc">SMTP 登录账号，通常是邮箱地址。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">密码</div>
              <div><a-input-password v-model:value="smtpForm.password" :placeholder="store.smtp.has_password ? '已保存，留空保留当前密码' : 'SMTP 密码或授权码'" /></div>
              <div class="settings-desc">后端加密保存，不会回显。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">发件邮箱</div>
              <div><a-input v-model:value="smtpForm.from_email" /></div>
              <div class="settings-desc">邮件 From 地址。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">收件邮箱</div>
              <div><a-input v-model:value="smtpForm.to_email" /></div>
              <div class="settings-desc">提醒会发到这个邮箱。</div>
            </div>
            <div class="settings-row">
              <div class="settings-label">连接方式</div>
              <div>
                <a-space>
                  <a-checkbox v-model:checked="smtpForm.use_ssl">SSL</a-checkbox>
                  <a-checkbox v-model:checked="smtpForm.use_tls">TLS</a-checkbox>
                </a-space>
              </div>
              <div class="settings-desc">465 通常勾选 SSL；587 通常勾选 TLS。</div>
            </div>
          </div>
          <div class="settings-actions">
            <a-button type="primary" :loading="savingSmtp" @click="saveSmtp">保存邮件通知</a-button>
            <a-button :loading="testingSmtp" @click="testSmtp">发送测试邮件</a-button>
          </div>
        </a-card>
      </a-tab-pane>
    </a-tabs>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { type StockThreshold } from '../api/client'
import { useAdminStore } from '../stores/admin'

const store = useAdminStore()
const activeTab = ref<'sub2api' | 'security' | 'stock' | 'smtp'>('sub2api')
const saving = ref(false)
const savingTurnstile = ref(false)
const savingStock = ref(false)
const checkingStock = ref(false)
const savingSmtp = ref(false)
const testingSmtp = ref(false)
const loadingGroups = ref(false)
const stockGroupId = ref<string>()
const stockRows = ref<StockThreshold[]>([])
const form = reactive({ base_url: 'http://127.0.0.1:5220', api_key: '' })
const turnstileForm = reactive({ enabled: false, site_key: '', secret_key: '' })
const smtpForm = reactive({
  enabled: false,
  host: '',
  port: 465,
  username: '',
  password: '',
  from_email: '',
  to_email: '',
  use_ssl: true,
  use_tls: false,
})
const stockColumns = [
  { title: '分组', dataIndex: 'group_name' },
  { title: '最低可用账号', key: 'min_available', dataIndex: 'min_available', width: 160 },
  { title: '启用', key: 'enabled', dataIndex: 'enabled', width: 100 },
  { title: '操作', key: 'actions', width: 100 },
]
const groupOptions = computed(() => store.groups.map((group) => ({ value: group.id, label: group.name })))

watch(
  () => store.sub2api.base_url,
  () => {
    form.base_url = store.sub2api.base_url || 'http://127.0.0.1:5220'
  },
  { immediate: true },
)

watch(
  () => store.turnstile,
  () => {
    turnstileForm.enabled = store.turnstile.enabled
    turnstileForm.site_key = store.turnstile.site_key || ''
    turnstileForm.secret_key = ''
  },
  { immediate: true },
)

watch(
  () => store.stockThresholds,
  () => {
    stockRows.value = store.stockThresholds.map((item) => ({ ...item }))
  },
  { immediate: true },
)

watch(
  () => store.smtp,
  () => {
    smtpForm.enabled = store.smtp.enabled
    smtpForm.host = store.smtp.host
    smtpForm.port = store.smtp.port || 465
    smtpForm.username = store.smtp.username
    smtpForm.password = ''
    smtpForm.from_email = store.smtp.from_email
    smtpForm.to_email = store.smtp.to_email
    smtpForm.use_ssl = store.smtp.use_ssl
    smtpForm.use_tls = store.smtp.use_tls
  },
  { immediate: true },
)

async function save() {
  saving.value = true
  try {
    await store.saveSettings(form)
    message.success('设置已保存')
    form.api_key = ''
  } catch (error) {
    message.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveTurnstile() {
  savingTurnstile.value = true
  try {
    await store.saveTurnstileSettings(turnstileForm)
    message.success('Turnstile 防护已保存')
    turnstileForm.secret_key = ''
  } catch (error) {
    message.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    savingTurnstile.value = false
  }
}

async function testGroups() {
  loadingGroups.value = true
  try {
    if (form.api_key || form.base_url !== store.sub2api.base_url) {
      await store.saveSettings(form)
      form.api_key = ''
    }
    await store.loadGroups()
    message.success(`读取到 ${store.groups.length} 个分组`)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '读取失败')
  } finally {
    loadingGroups.value = false
  }
}

function addStockRow() {
  const group = store.groups.find((item) => item.id === stockGroupId.value)
  if (!group) {
    message.warning('请选择分组')
    return
  }
  if (stockRows.value.some((item) => item.group_id === group.id)) {
    message.warning('这个分组已经添加')
    return
  }
  stockRows.value.push({ group_id: group.id, group_name: group.name, min_available: 10, enabled: true })
  stockGroupId.value = undefined
}

function removeStockRow(groupId: string) {
  stockRows.value = stockRows.value.filter((item) => item.group_id !== groupId)
}

async function saveStock() {
  savingStock.value = true
  try {
    await store.saveStockThresholds(stockRows.value)
    message.success('库存预警已保存')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    savingStock.value = false
  }
}

async function checkStock() {
  checkingStock.value = true
  try {
    const stock = await store.checkStock()
    message.success(stock.warnings.length ? `发现 ${stock.warnings.length} 个库存预警` : '库存正常')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '库存检查失败')
  } finally {
    checkingStock.value = false
  }
}

async function saveSmtp() {
  savingSmtp.value = true
  try {
    await store.saveSmtpSettings(smtpForm)
    message.success('邮件通知已保存')
    smtpForm.password = ''
  } catch (error) {
    message.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    savingSmtp.value = false
  }
}

async function testSmtp() {
  testingSmtp.value = true
  try {
    await store.testSmtpSettings()
    message.success('测试邮件已发送')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '发送失败')
  } finally {
    testingSmtp.value = false
  }
}

onMounted(async () => {
  await Promise.allSettled([store.loadStockThresholds(), store.loadSmtpSettings()])
})
</script>
