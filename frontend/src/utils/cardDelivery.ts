const publicEnv = import.meta.env || {}

function publicUrl(value: unknown, fallback: string) {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

export const CARD_REDEEM_URL = publicUrl(publicEnv.VITE_CARD_REDEEM_URL, 'https://buyer.example.com/')
export const FORMAT_CONVERTER_URL = publicUrl(publicEnv.VITE_FORMAT_CONVERTER_URL, 'https://converter.example.com/')

export function formatCardDeliveryInfo(codes: string[]) {
  return codes
    .map((code) => `卡密：${code}\n卡密提取网址：${CARD_REDEEM_URL}\n格式转换网站：${FORMAT_CONVERTER_URL}`)
    .join('\n\n')
}
