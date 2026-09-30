<template>
  <div v-if="p">
    <div class="page-head">
      <h1>{{ p.name }}</h1>
      <span class="tag" :class="ORIGIN_CLASS[p.origin]">{{ p.origin_label }}</span>
      <span class="spacer" />
      <button class="btn" @click="exportPdf">导出 PDF</button>
      <button v-if="!isTeacher && p.status === 'complete'" class="btn btn-primary" @click="start([])">作答整卷</button>
      <button class="btn" @click="router.back()">返回</button>
    </div>
    <p class="muted small">{{ p.category }} · {{ p.topic }}<span v-if="p.exam_date"> · 考试日期 {{ p.exam_date }}</span></p>
    <div v-if="p.origin === 'generated'" class="alert alert-info">
      AI 模拟卷：材料为虚构情境，人物、地名、数据不是真实信息。{{ p.status_note }}</div>
    <details v-if="p.sources?.length" class="small" style="margin-bottom: 12px">
      <summary class="faint" style="cursor: pointer">来源（{{ p.sources.length }}）</summary>
      <ul style="margin: 4px 0; padding-left: 18px">
        <li v-for="s in p.sources" :key="s.url"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.url }}</a>
          <span class="faint"> {{ s.note }}</span></li>
      </ul>
    </details>

    <div class="grid grid-2" style="align-items: start">
      <MaterialsPanel :paper-id="p.id" />
      <div>
        <div v-for="q in p.questions" :key="q.id" class="card">
          <div class="card-title">
            <h3>第 {{ q.no }} 题</h3>
            <span class="tag tag-brand">{{ q.qtype_label }}</span>
            <span class="faint">{{ q.full_score }} 分 · 资料 {{ q.material_refs.join('、') }}</span>
          </div>
          <p class="small">{{ q.stem }}</p>
          <p v-if="q.rubric" class="faint">评分配置 v{{ q.rubric.version }}（{{ q.rubric.source }}）</p>
          <p v-else class="faint">评分点将在第一次批改时由模型按材料生成</p>
          <button v-if="!isTeacher && p.status === 'complete'" class="btn btn-sm" @click="start([q.id])">只做这道题</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else-if="err" class="alert alert-danger">{{ err }}</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, currentUser, ORIGIN_CLASS } from '../api'
import MaterialsPanel from './MaterialsPanel.vue'

const route = useRoute()
const router = useRouter()
const p = ref<any>(null)
const err = ref('')
const isTeacher = computed(() => currentUser.value?.role === 'teacher')

onMounted(async () => {
  try { p.value = await api.paper(Number(route.params.id)) } catch (e: any) { err.value = e.friendly }
})

function exportPdf() {
  window.open(router.resolve(`/print/${p.value.id}`).href, '_blank')
}

async function start(qids: number[]) {
  try {
    const s = await api.createSheet(p.value.id, qids)
    router.push(`/grade/${s.id}`)
  } catch (e: any) { err.value = e.friendly }
}
</script>
