import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replaceAll('\\', '/')
          if (moduleId.includes('/node_modules/vuetify/')) return 'vuetify-vendor'
          if (
            moduleId.includes('/node_modules/vue/')
            || moduleId.includes('/node_modules/@vue/')
            || moduleId.includes('/node_modules/vue-router/')
            || moduleId.includes('/node_modules/vue-i18n/')
          ) return 'vue-vendor'
          if (moduleId.includes('/node_modules/markdown-it/') || moduleId.includes('/node_modules/katex/')) return 'rich-text'
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // 上传的图片（chat_message.extra 存 /uploads/... URL）
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    }
  }
})
