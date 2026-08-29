import { createApp } from 'vue'
import { Alert, Button, ConfigProvider, Form, Input } from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import './styles/buyer.css'
import BuyerRedeem from './views/BuyerRedeem.vue'

createApp(BuyerRedeem)
  .use(ConfigProvider)
  .use(Form)
  .use(Input)
  .use(Button)
  .use(Alert)
  .mount('#app')
