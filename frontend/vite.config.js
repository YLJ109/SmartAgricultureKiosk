import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 双入口：index.html = 终端端（一体机大屏），admin.html = 管理后台。
// 两者代码不共享主 chunk，各自按需加载自己的依赖（Element Plus 只会进 admin 的包）。
export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@kiosk': fileURLToPath(new URL('./src/kiosk', import.meta.url)),
      '@admin': fileURLToPath(new URL('./src/admin', import.meta.url)),
    },
  },

  server: {
    // 固定 5189：5173 与 5188 已被本机其它项目占用，避免被自动顺延到别人的端口
    port: 5189,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/uploads': { target: 'http://127.0.0.1:8002', changeOrigin: true },
    },
  },

  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        kiosk: fileURLToPath(new URL('./index.html', import.meta.url)),
        admin: fileURLToPath(new URL('./admin.html', import.meta.url)),
      },
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('element-plus')) return 'element-plus'
          if (id.includes('vue') || id.includes('pinia') || id.includes('axios')) return 'vue-vendor'
          return 'vendor'
        },
      },
    },
  },
})
