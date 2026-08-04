import { createApp, watch } from 'vue'
import App from './App.vue'
import router from './router'
import vuetify from './plugins/vuetify'
import i18n, { VUETIFY_LOCALE_MAP } from './i18n'
import '@mdi/font/css/materialdesignicons.css'
import './assets/style.css'

// 语言切换时同步 Vuetify 内置组件文案（如日期选择器等）
watch(() => i18n.global.locale.value, (val) => {
  vuetify.locale.current.value = VUETIFY_LOCALE_MAP[val] || 'en'
}, { immediate: true })

const app = createApp(App)
app.use(router)
app.use(vuetify)
app.use(i18n)
app.mount('#app')
