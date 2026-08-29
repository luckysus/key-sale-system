<template>
  <BuyerRedeem v-if="isBuyerHost" />
  <AdminApp v-else />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AdminApp from './views/AdminApp.vue'
import BuyerRedeem from './views/BuyerRedeem.vue'

const isBuyerHost = computed(() => location.hostname.startsWith('key.'))
document.title = isBuyerHost.value ? '卡密提取' : '卡密管理后台'
</script>
