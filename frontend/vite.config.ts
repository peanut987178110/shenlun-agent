import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 端口避开 8000 / 5173：同机器上的招聘平台默认占用这两个端口
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    strictPort: true,
    host: '127.0.0.1',
    proxy: {
      '/api': { target: 'http://127.0.0.1:8100', changeOrigin: true },
    },
  },
  build: { outDir: 'dist' },
})
