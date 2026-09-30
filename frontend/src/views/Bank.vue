<template>
  <div>
    <div class="page-head">
      <h1>题库</h1>
      <span class="spacer" />
      <button class="btn" @click="router.push('/import')">导入真题</button>
      <button class="btn" @click="router.push('/generate')">AI 出题</button>
    </div>
    <div v-if="origin === 'real' && missing.length" class="alert alert-warn">
      题库还缺：{{ missing.join('、') }}。可以在粉笔上复制整套卷，用「导入真题」补进来。</div>
    <p class="muted small">浙江省考申论分 A（综合类，县级以上机关）、B（基层类，乡镇街道）、C（行政执法类）三类试卷，
      每套 100 分、150 分钟。D 类（村干部）考《综合应用能力》，不收录。</p>
    <div class="row" style="margin-bottom: 12px">
      <select v-model="origin" class="input" style="width: auto" aria-label="来源">
        <option value="real">真题</option>
        <option value="generated">我的 AI 模拟卷</option>
      </select>
      <select v-model="code" class="input" style="width: auto" aria-label="卷别">
        <option value="">全部卷别</option>
        <option value="A">A 卷 · 综合类</option>
        <option value="B">B 卷 · 基层类</option>
        <option value="C">C 卷 · 行政执法类</option>
      </select>
    </div>
    <div v-if="err" class="alert alert-danger">{{ err }}</div>
    <div v-if="loaded && !groups.length" class="empty">
      {{ origin === 'real' ? '题库里还没有真题' : '还没有生成过模拟卷' }}</div>

    <div v-for="g in groups" :key="g.year" style="margin-bottom: 8px">
      <h2 style="margin: 16px 0 8px">{{ origin === 'real' ? `${g.year} 年度` : '' }}</h2>
      <div class="grid grid-3">
        <div v-for="p in g.papers" :key="p.id" class="card" style="margin: 0">
          <div class="row" style="margin-bottom: 6px">
            <b style="font-size: 16px">{{ p.code }} 卷</b>
            <span class="faint">{{ p.category }}</span>
            <span class="spacer" style="flex: 1" />
            <span v-if="p.status === 'questions_only'" class="tag tag-warn">缺材料</span>
            <span v-else-if="p.status === 'generating'" class="tag">生成中</span>
            <span v-else-if="p.status === 'failed'" class="tag tag-danger">生成失败</span>
          </div>
          <p class="small">{{ p.topic }}</p>
          <div class="faint" style="margin-bottom: 8px">
            {{ p.questions.length }} 道题：{{ p.questions.map((q: any) => `${q.qtype_label}${q.full_score}`).join(' · ') }}</div>
          <div class="row">
            <button class="btn btn-sm" :disabled="p.status === 'generating' || p.status === 'failed'"
                    @click="router.push(`/paper/${p.id}`)">看材料与题目</button>
            <button class="btn btn-sm" :disabled="p.status !== 'complete'"
                    @click="openPrint(p.id)">导出 PDF</button>
            <button v-if="!isTeacher" class="btn btn-sm btn-primary"
                    :disabled="p.status !== 'complete'" @click="start(p.id)">作答整卷</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, currentUser } from '../api'

const router = useRouter()
const papers = ref<any[]>([])
const origin = ref('real')
const code = ref('')
const err = ref('')
const loaded = ref(false)
const isTeacher = computed(() => currentUser.value?.role === 'teacher')

watch(origin, async (o) => {
  loaded.value = false
  try { papers.value = await api.papers({ origin: o }) } catch (e: any) { err.value = e.friendly }
  loaded.value = true
}, { immediate: true })

const groups = computed(() => {
  const out: { year: number; papers: any[] }[] = []
  for (const p of papers.value.filter((x) => !code.value || x.code === code.value)) {
    let g = out.find((x) => x.year === p.year)
    if (!g) out.push((g = { year: p.year, papers: [] }))
    g.papers.push(p)
  }
  return out
})

// 已收录年份范围内缺了哪些卷
const missing = computed(() => {
  const real = papers.value.filter((p) => p.origin === 'real')
  if (!real.length) return []
  const ys = real.map((p) => p.year)
  const out: string[] = []
  for (let y = Math.max(...ys); y >= Math.min(...ys); y--)
    for (const c of ['A', 'B', 'C'])
      if (!real.some((p) => p.year === y && p.code === c)) out.push(`${y} 年 ${c} 卷`)
  return out
})

async function start(paperId: number) {
  try {
    const s = await api.createSheet(paperId)
    router.push(`/grade/${s.id}`)
  } catch (e: any) { err.value = e.friendly }
}

function openPrint(id: number) {
  window.open(router.resolve(`/print/${id}`).href, '_blank')
}
</script>
