<template>
  <div>
    <div class="page-head">
      <h1>批改</h1>
      <span v-if="sheet?.paper" class="tag" :class="ORIGIN_CLASS[sheet.paper.origin]">{{ sheet.paper.origin_label }}</span>
      <span v-if="sheet?.paper" class="muted">{{ sheet.paper.name }}</span>
    </div>
    <div class="steps" aria-label="批改步骤">
      <div v-for="(s, i) in STEPS" :key="s" class="step"
           :class="{ done: i < stepIndex, current: i === stepIndex }">{{ i + 1 }}. {{ s }}</div>
    </div>
    <div v-if="err" class="alert alert-danger" role="alert">{{ err }}</div>

    <GradeChoose v-if="step === 'choose'" @start="create" />
    <SheetAnswer v-else-if="step === 'answer'" :key="sheet.id + ':' + (sheet.paper?.id || 0)" :sheet="sheet" :sys="sys" :busy="busy"
                 @submit-answers="submitAnswers" @upload="upload" @recognize="recognize"
                 @consent="consent" @delete-images="deleteImages" />
    <SheetConfirm v-else-if="step === 'confirm'" :sheet="sheet" :busy="busy"
                  @set-paper="setPaper" @submit="submitLines" />
    <SheetResult v-else-if="step === 'result'" :sheet="sheet" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, currentUser, ORIGIN_CLASS } from '../api'
import GradeChoose from './grade/GradeChoose.vue'
import SheetAnswer from './grade/SheetAnswer.vue'
import SheetConfirm from './grade/SheetConfirm.vue'
import SheetResult from './grade/SheetResult.vue'

const STEPS = ['选择试卷', '作答或上传', '核对识别与分题', '批改结果']
const route = useRoute()
const router = useRouter()
const sheet = ref<any>(null)
const sys = ref<any>(null)
const err = ref('')
const busy = ref(false)
let timer: number | undefined

const step = computed(() => {
  if (!sheet.value) return 'choose'
  const s = sheet.value.status
  if (s === 'grading' || s === 'graded') return 'result'
  if (s === 'recognized') return 'confirm'
  return 'answer'
})
const stepIndex = computed(() => ({ choose: 0, answer: 1, confirm: 2, result: 3 })[step.value])

async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
  err.value = ''
  busy.value = true
  try { return await fn() } catch (e: any) { err.value = e.friendly || String(e.message || e) } finally { busy.value = false }
}

async function load(id: number) {
  sheet.value = await api.sheet(id)
  if (sheet.value.status === 'grading') poll()
}

onMounted(async () => {
  sys.value = await api.status()
  const id = Number(route.params.id)
  if (id) await run(() => load(id))
})
onUnmounted(() => clearTimeout(timer))

function poll() {
  clearTimeout(timer)
  timer = window.setTimeout(async () => {
    sheet.value = await api.sheet(sheet.value.id)
    if (sheet.value.status === 'grading') poll()
  }, 2000)
}

async function create(paperId: number | null, qids: number[]) {
  const s = await run(() => api.createSheet(paperId, qids))
  if (s) router.replace(`/grade/${s.id}`)
}

async function consent(v: boolean) {
  await run(async () => { currentUser.value = { ...currentUser.value, ...(await api.setPrivacy({ consent_vision: v })) } })
}

async function upload(files: File[]) {
  const r = await run(() => api.uploadPages(sheet.value.id, files))
  if (r) sheet.value = r
}

async function recognize(force: boolean) {
  const r = await run(() => api.recognize(sheet.value.id, force))
  if (r) sheet.value = r
}

async function deleteImages() {
  if (!confirm('删除后无法再识别或回看原图，识别出的文字不受影响。确定删除？')) return
  await run(() => api.deleteImages(sheet.value.id))
  sheet.value = await api.sheet(sheet.value.id)
}

async function setPaper(paperId: number) {
  const r = await run(() => api.setSheetPaper(sheet.value.id, paperId))
  if (r) sheet.value = r
}

async function afterSubmit(r: any) {
  if (!r) return
  sheet.value = r
  poll()
}

async function submitAnswers(answers: Record<number, string>) {
  await afterSubmit(await run(() => api.submitSheet(sheet.value.id, { answers })))
}

async function submitLines(lines: any[]) {
  await afterSubmit(await run(() => api.submitSheet(sheet.value.id, { lines })))
}
</script>
