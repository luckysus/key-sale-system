import { Modal } from 'ant-design-vue'
import type { ModalFuncProps } from 'ant-design-vue'

export function confirmDanger(options: {
  title: string
  content?: string
  okText?: string
  cancelText?: string
  onOk: ModalFuncProps['onOk']
}) {
  Modal.confirm({
    title: options.title,
    content: options.content,
    okText: options.okText ?? '删除',
    okType: 'danger',
    cancelText: options.cancelText ?? '取消',
    centered: true,
    onOk: options.onOk,
  })
}
