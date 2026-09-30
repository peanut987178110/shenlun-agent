<template>
  <div>
    <div class="page-head"><h1>AI 出题</h1></div>
    <div class="grid grid-2" style="align-items: start">
      <div class="card">
        <div class="card-title"><h2>生成一套模拟卷</h2></div>
        <p class="small muted">题型、分值、字数照搬同卷别最近一年的真题结构；材料和题干由模型按浙江省考风格新命制，
          地名人物用虚构代号。生成后和真题一样可以作答、批改，评分点在第一次批改时按材料生成。</p>
        <div class="field">
          <label>卷别</label>
          <div class="row">
            <label v-for="(v, k) in CODES" :key="k" class="row small" style="margin-right: 12px">
              <input v-model="code" type="radio" :value="k" /> {{ k }} 卷 · {{ v }}</label>
          </div>
        </div>
        <div class="field">
          <label for="theme">主题（可不填，由模型选浙江近年基层工作重点）</label>
          <input id="theme" v-model.trim="theme" class="input" maxlength="60"
                 placeholder="例如：县域医共体建设、老旧小区加装电梯、山区海岛县共同富裕" />
        </div>
        <div v-if="err" class="alert alert-danger">{{ err }}</div>
        <button class="btn btn-primary" :disabled="busy || generating" @click="start">
          {{ generating ? '正在生成，请稍候…' : '开始生成' }}</button>
        <p class="faint" style="margin-top: 8px">一套卷约需 2—4 分钟，可以离开此页，生成好后在这里和题库里都能看到。</p>
      </div>

      <div class="card">
        <div class="card-title"><h2>我生成的模拟卷</h2></div>
        <div v-if="!list.length" class="muted small">还没有</div>
        <div v-for="p in list" :key="p.id" class="ann" style="cursor: default">
          <div class="row">
            <b style="flex: 1">{{ p.name }}</b>
            <span class="tag" :class="STATUS_CLASS[p.status]">{{ STATUS[p.status] }}</span>
          </div>
          <div class="faint">{{ p.created_at }} · {{ p.status_note }}</div>
          <div v-if="p.status === 'complete'" class="row" style="margin-top: 6px">
            <button class="btn btn-sm" @click="router.push(`/paper/${p.id}`)">看材料与题目</button>
            <button class="btn btn-sm btn-primary" @click="answer(p.id)">作答整卷</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const CODES = { A: '综合类（县级以上机关）', B: '基层类（乡镇街道）', C: '行政执法类' }
const STATUS: Record<string, string> = { generating: '生成中', complete: '已完成', failed: '失败' }
const STATUS_CLASS: Record<string, string> = { generating: '', complete: 'tag-ok', failed: 'tag-danger' }
const code = ref('A')
const theme = ref('')
const list = ref<any[]>([])
const err = ref('')
const busy = ref(false)
let timer: number | undefined

const generating = computed(() => list.value.some((p) => p.status === 'generating'))

async function refresh() {
  list.value = (await api.myGenerated()).papers
  clearTimeout(timer)
  if (generating.value) timer = window.setTimeout(refresh, 3000)
}
onMounted(refresh)
onUnmounted(() => clearTimeout(timer))

async function start() {
  err.value = ''
  busy.value = true
  try {
    await api.generate(code.value, theme.value)
    await refresh()
  } catch (e: any) { err.value = e.friendly } finally { busy.value = false }
}

async function answer(id: number) {
  const s = await api.createSheet(id)
  router.push(`/grade/${s.id}`)
}
</script>
