<template>
  <a-modal v-model:open="open" title="卡密批次" width="860px" :footer="null" destroy-on-close>
    <a-table
      size="small"
      :columns="columns"
      :data-source="store.batches"
      :pagination="tablePagination"
      :row-key="(row: any) => row.id"
      :loading="loading"
      :scroll="{ x: 760, y: 360 }"
      @change="onTableChange"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'created_at'">{{ formatTime(record.created_at) }}</template>
        <template v-else-if="column.key === 'actions'">
          <a-button size="small" danger :loading="deletingOne === record.id" @click="askDeleteOne(record.id)">删除</a-button>
        </template>
      </template>
    </a-table>
  </a-modal>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { formatTime } from '../api/client'
import { useAdminStore } from '../stores/admin'
import { confirmDanger } from '../utils/confirm'

const open = defineModel<boolean>('open', { default: false })
const store = useAdminStore()
const loading = ref(false)
const deletingOne = ref<number | null>(null)

const columns = [
  { title: 'ID', dataIndex: 'id', width: 80 },
  { title: '批次名称', dataIndex: 'name', width: 220 },
  { title: '备注', dataIndex: 'note', width: 220 },
  { title: '创建时间', key: 'created_at', dataIndex: 'created_at', width: 180 },
  { title: '操作', key: 'actions', fixed: 'right', width: 90 },
]
const tablePagination = reactive({
  current: 1,
  pageSize: 10,
  showSizeChanger: true,
  showTotal: (total: number) => `共 ${total} 条`,
})

function onTableChange(pagination: { current?: number; pageSize?: number }) {
  tablePagination.current = pagination.current || 1
  tablePagination.pageSize = pagination.pageSize || tablePagination.pageSize
}

async function load() {
  loading.value = true
  try {
    await store.loadBatches()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '读取批次失败')
  } finally {
    loading.value = false
  }
}

async function deleteOne(id: number) {
  deletingOne.value = id
  try {
    await store.deleteBatch(id)
    message.success('批次已删除')
    await load()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '删除失败')
    throw error
  } finally {
    deletingOne.value = null
  }
}

function askDeleteOne(id: number) {
  confirmDanger({
    title: '确定删除这个批次？',
    content: '卡密不会被删除，只会解除批次归属。',
    async onOk() {
      await deleteOne(id)
    },
  })
}

watch(open, (value) => {
  if (value) {
    tablePagination.current = 1
    void load()
  }
})
</script>
