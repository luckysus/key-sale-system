/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CARD_REDEEM_URL?: string
  readonly VITE_FORMAT_CONVERTER_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
