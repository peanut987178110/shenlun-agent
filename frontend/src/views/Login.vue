<template>
  <div style="max-width: 380px; margin: 10vh auto; padding: 0 16px">
    <div class="card">
      <h1 style="margin-bottom: 4px">浙考申论智阅</h1>
      <p class="muted small">浙江省考申论的证据化评分、失分诊断与能力增分</p>
      <div class="row" style="margin: 16px 0" role="tablist">
        <button class="btn btn-sm" :class="{ 'btn-primary': mode === 'login' }" role="tab"
                :aria-selected="mode === 'login'" @click="mode = 'login'">登录</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': mode === 'register' }" role="tab"
                :aria-selected="mode === 'register'" @click="mode = 'register'">注册学员账号</button>
      </div>
      <form @submit.prevent="submit">
        <div class="field">
          <label for="u">用户名</label>
          <input id="u" v-model.trim="username" class="input" autocomplete="username"
                 placeholder="字母、数字、下划线，3—32 位" required />
        </div>
        <div v-if="mode === 'register'" class="field">
          <label for="n">昵称</label>
          <input id="n" v-model.trim="displayName" class="input" maxlength="32" />
        </div>
        <div class="field">
          <label for="p">密码</label>
          <input id="p" v-model="password" type="password" class="input" required
                 :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                 :placeholder="mode === 'register' ? '至少 8 位' : ''" />
        </div>
        <div v-if="err" class="alert alert-danger" role="alert">{{ err }}</div>
        <button class="btn btn-primary" style="width: 100%; justify-content: center" :disabled="busy">
          {{ busy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
        </button>
      </form>
      <p class="faint" style="margin-top: 12px">
        首次启动时，演示账号的密码打印在后端启动日志里。教师账号不能自助注册，需由已有教师创建。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, auth, currentUser } from '../api'

const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const displayName = ref('')
const err = ref('')
const busy = ref(false)

async function submit() {
  err.value = ''
  busy.value = true
  try {
    const r = mode.value === 'login'
      ? await api.login(username.value, password.value)
      : await api.register(username.value, password.value, displayName.value)
    auth.set(r.token)
    currentUser.value = await api.me()
    router.push(currentUser.value.role === 'teacher' ? '/teacher' : '/')
  } catch (e: any) {
    err.value = e.friendly || '登录失败'
  } finally {
    busy.value = false
  }
}
</script>
