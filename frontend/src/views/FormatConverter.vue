<template>
  <section class="format-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">格式转换</h1>
      </div>
      <a-space>
        <a-button @click="copyResult" :disabled="!result.text"><CopyOutlined />复制结果</a-button>
        <a-button type="primary" @click="downloadResult" :disabled="!result.text"><DownloadOutlined />下载结果</a-button>
      </a-space>
    </div>

    <a-row :gutter="[16, 16]">
      <a-col :xs="24" :lg="12">
        <a-card class="tool-card pull-card">
          <template #title>
            <a-space>
              <CloudDownloadOutlined />
              <span>从 sub2api 拉取账号</span>
            </a-space>
          </template>
          <template #extra>
            <a-tag color="default">{{ store.groups.length ? `${store.groups.length} 个分组` : '未读取分组' }}</a-tag>
          </template>

          <div class="pull-panel">
            <div class="pull-panel-head">
              <div>
                <strong>账号来源</strong>
                <span>选择分组后拉取账号，并直接转换成目标平台上架格式。</span>
              </div>
              <a-button :loading="loadingGroups" @click="loadGroups">
                <ReloadOutlined />
                读取分组
              </a-button>
            </div>

            <a-form layout="vertical">
              <a-form-item label="账号分组">
                <a-select
                  v-model:value="groupId"
                  :options="groupOptions"
                  placeholder="请选择要转换的分组"
                  show-search
                  :filter-option="filterGroup"
                />
              </a-form-item>
              <a-button type="primary" block size="large" :loading="converting" @click="convertGroup">拉取账号并转换格式</a-button>
            </a-form>
          </div>
        </a-card>
      </a-col>

      <a-col :xs="24" :lg="12">
        <a-card title="上传文件转换" class="tool-card upload-tool-card">
          <a-upload-dragger class="upload-picker" :show-upload-list="false" accept=".json,.jsonl,.txt,application/json,text/plain" :before-upload="readFile">
            <div class="upload-panel">
              <UploadOutlined />
              <strong>选择或拖入 JSON / TXT 文件</strong>
              <span>{{ fileName || '文件只在浏览器中读取并转换' }}</span>
            </div>
          </a-upload-dragger>
        </a-card>
      </a-col>
    </a-row>

    <a-card class="mt16">
      <template #title>
        <a-space>
          <span>转换结果</span>
          <a-tag :color="statusColor">{{ statusText }}</a-tag>
        </a-space>
      </template>
      <a-row :gutter="[12, 12]" class="result-meta">
        <a-col :xs="24" :sm="8">
          <div class="metric">
            <span>账号数</span>
            <strong>{{ result.count || '-' }}</strong>
          </div>
        </a-col>
        <a-col :xs="24" :sm="8">
          <div class="metric">
            <span>最长行</span>
            <strong>{{ result.maxLineLength || '-' }}</strong>
          </div>
        </a-col>
        <a-col :xs="24" :sm="8">
          <div class="metric">
            <span>大小</span>
            <strong>{{ result.sizeText || '-' }}</strong>
          </div>
        </a-col>
      </a-row>
      <a-textarea v-model:value="result.text" class="result-output" :rows="11" readonly placeholder="转换后的内容会显示在这里" />
    </a-card>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { CloudDownloadOutlined, CopyOutlined, DownloadOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { accountsToJsonl, formatBytes, parseAccountsText, safeOutputName } from '../api/client'
import { useAdminStore } from '../stores/admin'

const store = useAdminStore()
const groupId = ref('')
const fileName = ref('')
const outputName = ref('converted.full.jsonl.txt')
const loadingGroups = ref(false)
const converting = ref(false)
const status = ref<'ready' | 'working' | 'done' | 'error'>('ready')
const result = reactive({ text: '', count: 0, maxLineLength: 0, sizeText: '' })

const groupOptions = computed(() => store.groups.map((group) => ({ value: group.id, label: group.name })))
const statusText = computed(() => ({ ready: 'Ready', working: 'Working', done: 'Done', error: 'Error' }[status.value]))
const statusColor = computed(() => ({ ready: 'default', working: 'processing', done: 'green', error: 'red' }[status.value]))

function filterGroup(input: string, option?: { label?: string; value?: string }) {
  return String(option?.label || option?.value || '').toLowerCase().includes(input.toLowerCase())
}

function setResult(accounts: Record<string, unknown>[], name: string) {
  const next = accountsToJsonl(accounts)
  result.text = next.text
  result.count = next.count
  result.maxLineLength = next.maxLineLength
  result.sizeText = formatBytes(next.size)
  outputName.value = safeOutputName(name)
  status.value = 'done'
}

function setError(error: unknown) {
  result.text = error instanceof Error ? error.message : String(error)
  result.count = 0
  result.maxLineLength = 0
  result.sizeText = ''
  status.value = 'error'
}

async function loadGroups() {
  loadingGroups.value = true
  status.value = 'working'
  try {
    await store.loadGroups()
    status.value = 'ready'
    message.success(`读取到 ${store.groups.length} 个分组`)
  } catch (error) {
    setError(error)
    message.error(error instanceof Error ? error.message : '读取分组失败')
  } finally {
    loadingGroups.value = false
  }
}

async function convertGroup() {
  if (!groupId.value) {
    message.warning('请先选择 sub2api 分组')
    return
  }
  converting.value = true
  status.value = 'working'
  try {
    const accounts = await store.loadAccounts(groupId.value)
    const group = store.groups.find((item) => item.id === groupId.value)
    setResult(accounts, group?.name || groupId.value)
  } catch (error) {
    setError(error)
    message.error(error instanceof Error ? error.message : '转换失败')
  } finally {
    converting.value = false
  }
}

async function readFile(file: File) {
  fileName.value = file.name
  status.value = 'working'
  try {
    setResult(parseAccountsText(await file.text()), file.name.replace(/\.[^.]+$/, '') || 'uploaded')
  } catch (error) {
    setError(error)
    message.error(error instanceof Error ? error.message : '转换失败')
  }
  return false
}

async function copyResult() {
  if (!result.text) return
  await navigator.clipboard.writeText(result.text)
  message.success('已复制')
}

function downloadResult() {
  if (!result.text) return
  const blob = new Blob([result.text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = outputName.value
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
</script>
