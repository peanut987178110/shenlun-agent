import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'

import App from './App.vue'
import './styles.css'
import { api, auth, currentUser } from './api'

import Login from './views/Login.vue'
import Home from './views/Home.vue'
import Bank from './views/Bank.vue'
import PaperView from './views/PaperView.vue'
import Grade from './views/Grade.vue'
import Report from './views/Report.vue'
import History from './views/History.vue'
import Profile from './views/Profile.vue'
import TeacherQueue from './views/TeacherQueue.vue'
import TeacherReview from './views/TeacherReview.vue'
import Settings from './views/Settings.vue'
import Assistant from './views/Assistant.vue'
import Generate from './views/Generate.vue'
import ImportPaper from './views/ImportPaper.vue'
import PrintPaper from './views/PrintPaper.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/', component: Home, meta: { title: '首页' } },
    { path: '/bank', component: Bank, meta: { title: '题库' } },
    { path: '/paper/:id', component: PaperView, meta: { title: '试卷' } },
    { path: '/grade/:id?', component: Grade, meta: { title: '批改' } },
    { path: '/report/:id', component: Report, meta: { title: '批改报告' } },
    { path: '/history', component: History, meta: { title: '我的作答' } },
    { path: '/profile', component: Profile, meta: { title: '能力画像' } },
    { path: '/teacher', component: TeacherQueue, meta: { title: '复核队列', teacher: true } },
    { path: '/teacher/:id', component: TeacherReview, meta: { title: '教师复核', teacher: true } },
    { path: '/settings', component: Settings, meta: { title: '设置' } },
    { path: '/assistant', component: Assistant, meta: { title: '申论助手' } },
    { path: '/generate', component: Generate, meta: { title: 'AI 出题' } },
    { path: '/import', component: ImportPaper, meta: { title: '导入真题' } },
    { path: '/print/:id', component: PrintPaper, meta: { title: '导出 PDF', bare: true } },
  ],
})

// 前端拦截只是体验优化，真正的权限边界在后端，每个接口都校验令牌与角色
router.beforeEach(async (to) => {
  if (to.meta.public) return auth.token && to.path === '/login' ? '/' : true
  if (!auth.token) return '/login'
  if (!currentUser.value) {
    try {
      currentUser.value = await api.me()
    } catch {
      auth.clear()
      return '/login'
    }
  }
  if (to.meta.teacher && currentUser.value.role !== 'teacher') return '/'
  if (currentUser.value.role === 'teacher' && to.path === '/') return '/teacher'
  return true
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || ''} · 浙考申论智阅`
})

createApp(App).use(router).mount('#app')
