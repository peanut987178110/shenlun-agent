<template>
  <div class="card">
    <div class="card-title"><h2>选择试卷</h2></div>
    <div class="row" style="margin-bottom: 12px">
      <select v-model.number="year" class="input" style="width: auto" aria-label="年份">
        <option :value="0">全部年份</option>
        <option v-for="y in years" :key="y" :value="y">{{ y }} 年度</option>
      </select>
      <select v-model="code" class="input" style="width: auto" aria-label="卷别">
        <option value="">全部卷别</option>
        <option value="A">A 卷 · 综合类</option>
        <option value="B">B 卷 · 基层类</option>
        <option value="C">C 卷 · 行政执法类</option>
      </select>
      <select v-model="origin" class="input" style="width: auto" aria-label="来源">
        <option value="">真题 + 模拟卷</option>
        <option value="real">只看真题</option>
        <option value="generated">只看我的 AI 模拟卷</option>
      </select>
      <span class="spacer" style="flex: 1" />
      <button class="btn btn-sm" @click="router.push('/generate')">AI 出一套新卷</button>
    </div>
    <div v-if="!shown.length" class="empty">没有符合条件的试卷</div>
    <div v-for="p in shown" :key="p.id" class="ann" style="cursor: default" :class="{ active: picked?.id === p.id }">
      <div class="row">
        <span class="tag" :class="ORIGIN_CLASS[p.origin]">{{ p.origin_label }}</span>
        <b style="flex: 1">{{ p.name }}</b>
        <span v-if="p.status === 'questions_only'" class="tag tag-warn">缺材料</span>
        <button class="btn btn-sm" :class="{ 'btn-primary': picked?.id !== p.id }" @click="pick(p)">
          {{ picked?.id === p.id ? '已选' : '选这套' }}</button>
      </div>
      <div class="faint">{{ p.topic }}</div>
      <div v-if="picked?.id === p.id" style="margin-top: 8px">
        <div class="small muted" style="margin-bottom: 4px">作答哪些题（默认整卷）：</div>
        <label v-for="q in p.questions" :key="q.id" class="row small" style="flex-wrap: nowrap; align-items: flex-start; margin-bottom: 4px">
          <input v-model="qids" type="checkbox" :value="q.id" />
          <span><b>第 {{ q.no }} 题</b> <span class="tag tag-brand">{{ q.qtype_label }}</span> {{ q.full_score }} 分 ·
            {{ q.stem.slice(0, 60) }}…</span>
        </label>
        <div class="row" style="margin-top: 8px">
          <button class="btn btn-primary" :disabled="!qids.length || p.status === 'questions_only'"
                  @click="$emit('start', p.id, qids.length === p.questions.length ? [] : qids)">
            开始作答（{{ qids.length === p.questions.length ? '整卷' : qids.length + ' 道题' }}）</button>
          <span v-if="p.status === 'questions_only'" class="small" style="color: var(--danger)">缺材料的卷无法批改</span>
        </div>
      </div>
    </div>
    <div class="row" style="margin-top: 12px">
      <button class="btn" @click="$emit('start', null, [])">不选试卷，直接上传答卷</button>
      <span class="faint">上传识别后按答案内容自动匹配是哪套卷，你再确认。</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ORIGIN_CLASS } from '../../api'

defineEmits<{ start: [paperId: number | null, questionIds: number[]] }>()
const router = useRouter()
const papers = ref<any[]>([])
const year = ref(0)
const code = ref('')
const origin = ref('')
const picked = ref<any>(null)
const qids = ref<number[]>([])

onMounted(async () => {
  papers.value = (await api.papers()).filter((p: any) => p.origin !== 'sample' && p.status !== 'generating' && p.status !== 'failed')
})
const years = computed(() => [...new Set(papers.value.map((p) => p.year))].sort((a, b) => b - a))
const shown = computed(() => papers.value.filter((p) => (!year.value || p.year === year.value)
  && (!code.value || p.code === code.value) && (!origin.value || p.origin === origin.value)))

function pick(p: any) {
  picked.value = p
  qids.value = p.questions.map((q: any) => q.id)
}
</script>
