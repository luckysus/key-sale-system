import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import './styles/app.css'
import App from './App.vue'

createApp(App).use(createPinia()).use(Antd).mount('#app')
