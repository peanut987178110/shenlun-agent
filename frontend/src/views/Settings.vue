<template>
  <div>
    <div class="page-head"><h1>设置</h1></div>
    <div class="grid grid-2">
      <div v-if="!isTeacher" class="card">
        <div class="card-title"><h2>备考目标</h2></div>
        <GoalForm />
      </div>

      <div v-if="!isTeacher" class="card">
        <div class="card-title"><h2>隐私</h2></div>
        <label class="row" style="margin-bottom: 8px; flex-wrap: nowrap; align-items: flex-start">
          <input type="checkbox" :checked="user?.consent_vision === true" @change="setPrivacy('consent_vision', ($event.target as HTMLInputElement).checked)" />
          <span class="small">允许把答卷图片发送给识别服务（{{ sys?.llm_provider }}）。关闭后只能手动录入。</span>
        </label>
        <label class="row" style="flex-wrap: nowrap; align-items: flex-start">
          <input type="checkbox" :checked="user?.allow_training_data" @change="setPrivacy('allow_training_data', ($event.target as HTMLInputElement).checked)" />
          <span class="small">允许把我的作答（已脱敏）用于改进评分。默认关闭。</span>
        </label>
        <p class="faint" style="margin-top: 8px">答案文本在确认时已自动脱敏手机号、身份证号、准考证号。原图可以在每次作答的上传页删除。</p>
      </div>

      <div class="card">
        <div class="card-title"><h2>模型服务</h2></div>
        <template v-if="sys">
          <p v-if="sys.llm_enabled" class="small">已连接：{{ sys.llm_provider }}<br />
            评分 {{ sys.models.medium }} · 复核 {{ sys.models.large }} · 识别 {{ sys.models.vision }}</p>
          <div v-else class="alert alert-warn">未配置。识别只能手动录入，批改由规则引擎完成。
            在 backend/.env 中填写 LLM_BASE_URL 与 LLM_API_KEY 后重启后端即可启用。</div>
          <button v-if="isTeacher" class="btn btn-sm" :disabled="pinging" @click="ping">测试连接</button>
          <p v-if="pingMsg" class="small" style="margin-top: 6px">{{ pingMsg }}</p>
        </template>
        <p class="faint">出于安全考虑，模型地址和密钥只能在服务器的 .env 文件中配置，界面不读写密钥。</p>
      </div>

      <div class="card">
        <div class="card-title"><h2>修改密码</h2></div>
        <form @submit.prevent="changePwd">
          <div class="field"><label for="op">原密码</label><input id="op" v-model="pwd.old" type="password" class="input" autocomplete="current-password" /></div>
          <div class="field"><label for="np">新密码（至少 8 位）</label><input id="np" v-model="pwd.new1" type="password" class="input" autocomplete="new-password" /></div>
          <div class="field"><label for="np2">确认新密码</label><input id="np2" v-model="pwd.new2" type="password" class="input" autocomplete="new-password" /></div>
          <div v-if="pwdErr" class="alert alert-danger">{{ pwdErr }}</div>
          <button class="btn btn-primary">修改</button>
        </form>
      </div>

      <div v-if="isTeacher" class="card">
        <div class="card-title"><h2>创建教师账号</h2></div>
        <form @submit.prevent="newTeacher">
          <div class="field"><label for="tu">用户名</label><input id="tu" v-model.trim="teacher.username" class="input" /></div>
          <div class="field"><label for="tn">姓名</label><input id="tn" v-model.trim="teacher.display_name" class="input" /></div>
          <div class="field"><label for="tp">初始密码（至少 8 位）</label><input id="tp" v-model="teacher.password" type="password" class="input" autocomplete="new-password" /></div>
          <div v-if="teacherErr" class="alert alert-danger">{{ teacherErr }}</div>
          <button class="btn btn-primary">创建</button>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, currentUser } from '../api'
import { toast } from '../toast'
import GoalForm from './GoalForm.vue'

const user = computed(() => currentUser.value)
const isTeacher = computed(() => user.value?.role === 'teacher')
const sys = ref<any>(null)
const pinging = ref(false)
const pingMsg = ref('')
const pwd = reactive({ old: '', new1: '', new2: '' })
const pwdErr = ref('')
const teacher = reactive({ username: '', display_name: '', password: '' })
const teacherErr = ref('')

onMounted(async () => { sys.value = await api.status() })

async function setPrivacy(key: string, v: boolean) {
  currentUser.value = { ...currentUser.value, ...(await api.setPrivacy({ [key]: v })) }
  toast('已保存')
}

async function ping() {
  pinging.value = true
  try { pingMsg.value = (await api.ping()).message } finally { pinging.value = false }
}

async function changePwd() {
  pwdErr.value = ''
  if (pwd.new1 !== pwd.new2) { pwdErr.value = '两次输入的新密码不一致'; return }
  try {
    await api.changePassword(pwd.old, pwd.new1)
    Object.assign(pwd, { old: '', new1: '', new2: '' })
    toast('密码已修改')
  } catch (e: any) { pwdErr.value = e.friendly }
}

async function newTeacher() {
  teacherErr.value = ''
  try {
    await api.createTeacher(teacher)
    toast(`已创建教师账号 ${teacher.username}`)
    Object.assign(teacher, { username: '', display_name: '', password: '' })
  } catch (e: any) { teacherErr.value = e.friendly }
}
</script>
