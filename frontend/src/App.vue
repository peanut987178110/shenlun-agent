<template>
  <router-view v-if="route.meta.public || route.meta.bare" />
  <div v-else class="layout">
    <aside class="sidebar">
      <div class="brand">
        <b>浙考申论智阅</b>
        <small>证据化评分 · 能力增分</small>
      </div>
      <nav>
        <button v-for="it in nav" :key="it.path" class="nav-item"
                :class="{ active: isActive(it.path) }" @click="router.push(it.path)">
          {{ it.label }}
        </button>
      </nav>
      <div class="sidebar-foot">
        <div>{{ user?.display_name }}（{{ user?.role === 'teacher' ? '教师' : '学员' }}）</div>
        <div v-if="user && !user.llm_enabled" class="tag tag-warn" style="margin: 6px 0">规则评分模式</div>
        <button class="btn-link small" @click="logout">退出登录</button>
      </div>
    </aside>
    <main class="main">
      <router-view :key="route.fullPath" />
    </main>
  </div>
  <div v-if="toastMsg" class="toast" role="status">{{ toastMsg }}</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, currentUser } from './api'
import { toastMsg } from './toast'

const route = useRoute()
const router = useRouter()
const user = computed(() => currentUser.value)

const nav = computed(() => user.value?.role === 'teacher'
  ? [{ path: '/teacher', label: '复核队列' }, { path: '/bank', label: '题库' },
     { path: '/assistant', label: '申论助手' }, { path: '/settings', label: '设置' }]
  : [{ path: '/', label: '首页' }, { path: '/grade', label: '开始批改' },
     { path: '/bank', label: '真题题库' }, { path: '/generate', label: 'AI 出题' },
     { path: '/assistant', label: '申论助手' }, { path: '/history', label: '我的作答' },
     { path: '/profile', label: '能力画像' }, { path: '/settings', label: '设置' }])

function isActive(p: string) {
  if (p === '/') return route.path === '/'
  return route.path === p || route.path.startsWith(p + '/')
}

function logout() {
  auth.clear()
  router.push('/login')
}
</script>
