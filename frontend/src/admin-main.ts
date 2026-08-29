import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import './styles/app.css'
import AdminApp from './views/AdminApp.vue'

createApp(AdminApp).use(createPinia()).use(Antd).mount('#app')
