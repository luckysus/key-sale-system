<template>
  <a-modal
    :open="open"
    title="个人中心"
    :width="520"
    :confirm-loading="saving"
    ok-text="保存"
    cancel-text="取消"
    @ok="save"
    @cancel="$emit('update:open', false)"
  >
    <a-form layout="vertical">
      <div class="profile-avatar">
        <a-avatar :size="72" :src="avatar || store.user?.avatar || undefined">{{ store.user?.username?.slice(0, 1).toUpperCase() }}</a-avatar>
        <a-upload :show-upload-list="false" accept="image/png,image/jpeg,image/webp,image/gif" :before-upload="readAvatar">
          <a-button>修改头像</a-button>
        </a-upload>
      </div>
      <a-form-item label="邮箱">
        <a-input v-model:value="email" type="email" placeholder="name@example.com" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { useAdminStore } from '../stores/admin'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()
const store = useAdminStore()
const email = ref('')
const avatar = ref('')
const saving = ref(false)

watch(
  () => store.user,
  () => {
    email.value = store.user?.email || ''
    avatar.value = store.user?.avatar || ''
  },
  { immediate: true },
)

// 允许的头像 MIME 类型白名单，需与后端 avatar 前缀白名单保持一致
const ALLOWED_AVATAR_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']
// 上传文件大小上限：200KB
const MAX_AVATAR_SIZE = 200 * 1024
// 后端 avatar 字段 max_length=300000，DataURL 长度不得超过此值
const MAX_AVATAR_DATAURL_LENGTH = 300000
// 与后端白名单对齐的合法 DataURL 前缀
const VALID_DATAURL_PREFIXES = [
  'data:image/png;',
  'data:image/jpeg;',
  'data:image/webp;',
  'data:image/gif;',
]

function readAvatar(file: File) {
  // 1. 类型白名单校验
  if (!ALLOWED_AVATAR_TYPES.includes(file.type)) {
    message.error('仅支持 PNG/JPEG/WebP/GIF 格式')
    return false
  }
  // 2. 大小限制校验
  if (file.size > MAX_AVATAR_SIZE) {
    message.error('头像大小不能超过 200KB')
    return false
  }
  const reader = new FileReader()
  reader.onload = () => {
    const value = String(reader.result || '')
    // 3. DataURL 二次校验：必须为合法 image DataURL 前缀（与后端白名单一致）
    if (!VALID_DATAURL_PREFIXES.some((prefix) => value.startsWith(prefix))) {
      message.error('仅支持 PNG/JPEG/WebP/GIF 格式')
      return
    }
    // 4. 长度限制校验：后端 avatar 字段限制 300000 字符
    if (value.length > MAX_AVATAR_DATAURL_LENGTH) {
      message.error('图片过大，请换更小的图片')
      return
    }
    avatar.value = value
  }
  reader.readAsDataURL(file)
  return false
}

async function save() {
  saving.value = true
  try {
    await store.saveProfile(email.value, avatar.value)
    message.success('已保存')
    emit('update:open', false)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}
</script>
