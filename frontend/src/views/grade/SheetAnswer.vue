<template>
  <div class="grid grid-2" style="align-items: start">
    <div>
      <MaterialsPanel v-if="sheet.paper" :paper-id="sheet.paper.id" :refs="currentRefs"
                      :sheet-id="sheet.id" :initial-marks="sheet.marks" editable />
      <div v-else class="card">
        <h2 style="margin-bottom: 6px">未选试卷</h2>
        <p class="small muted">上传答卷并识别后，系统按答案内容匹配是哪套卷，你确认后再切分到各题。</p>
      </div>
    </div>

    <div>
      <div class="row" role="tablist" style="margin-bottom: 12px">
        <button class="btn btn-sm" :class="{ 'btn-primary': mode === 'type' }" role="tab" :aria-selected="mode === 'type'"
                :disabled="!sheet.paper" @click="mode = 'type'">在线作答 / 录入</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': mode === 'photo' }" role="tab" :aria-selected="mode === 'photo'"
                @click="mode = 'photo'">拍照上传答卷</button>
      </div>

      <template v-if="mode === 'type' && sheet.paper">
        <div v-for="q in sheet.questions" :key="q.no" class="card" @focusin="focusQ = q.no">
          <div class="card-title">
            <h3>第 {{ q.no }} 题</h3>
            <span class="tag tag-brand">{{ q.qtype_label }}</span>
            <span class="faint">{{ q.full_score }} 分</span>
          </div>
          <p class="small" style="margin-bottom: 8px">{{ q.stem }}</p>
          <textarea v-model="answers[q.no]" class="input" :rows="q.qtype === 'essay' ? 16 : 7"
                    :aria-label="`第 ${q.no} 题答案`" @input="saveDraft" />
          <div class="faint num" :style="{ color: over(q) ? 'var(--danger)' : '' }">
            {{ wc(answers[q.no]) }} 字<span v-if="q.word_max"> / 上限 {{ q.word_max }}</span>
            <span v-if="q.word_min"> · 下限 {{ q.word_min }}</span></div>
        </div>
        <div class="row">
          <span class="faint">已作答 {{ answered }} / {{ sheet.questions.length }} 题，草稿自动保存在本机</span>
          <span style="flex: 1" />
          <button class="btn btn-primary" :disabled="busy || !answered" @click="$emit('submitAnswers', cleaned())">
            提交批改（{{ answered }} 题）</button>
        </div>
      </template>

      <template v-if="mode === 'photo'">
        <div v-if="consentNeeded" class="card">
          <h2 style="margin-bottom: 8px">上传前请确认</h2>
          <p class="small">拍照识别需要把答卷图片发送给视觉模型服务（{{ sys?.llm_provider }}，{{ sys?.models?.vision }}）。
            图片发送前会缩小并去掉拍摄信息（EXIF），但图片内容本身无法在本地脱敏。建议拍照避开姓名、准考证号区域。</p>
          <div class="row">
            <button class="btn btn-primary" @click="$emit('consent', true)">同意并继续</button>
            <button class="btn" @click="$emit('consent', false)">不同意</button>
          </div>
        </div>
        <div v-else class="card">
          <div class="card-title"><h2>上传答卷</h2><span class="faint">JPG / PNG / PDF，最多 {{ sys?.max_pages }} 页，按页序选择</span></div>
          <div v-if="!canVision" class="alert alert-warn">
            {{ !sys?.llm_enabled ? '未配置视觉模型，无法识别手写答卷，请用在线录入。' : '你未同意图片外发，只能在线录入。' }}</div>
          <p class="small muted">一页上写了几道题没关系，识别后会按题号自动切分，你再逐行确认。</p>
          <input ref="fileInput" type="file" multiple accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf"
                 aria-label="选择答卷图片" @change="upload" />
          <div v-for="pg in sheet.pages" :key="pg.page_no" style="margin-top: 10px">
            <div class="row"><b>第 {{ pg.page_no }} 页</b>
              <span class="tag" :class="pg.grade === 'A' ? 'tag-ok' : pg.grade === 'B' ? 'tag-warn' : 'tag-danger'">{{ pg.grade }} 级</span></div>
            <div v-for="(it, i) in pg.issues" :key="i" class="small"
                 :style="{ color: it.level >= 'C' ? 'var(--danger)' : 'var(--warn)' }">· {{ it.message }}</div>
          </div>
          <div v-if="sheet.pages.length" style="margin-top: 12px">
            <div class="alert" :class="sheet.quality_grade >= 'C' ? 'alert-danger' : 'alert-ok'">
              整体 {{ sheet.quality_grade }} 级：{{ sheet.quality_text }}</div>
            <label v-if="sheet.quality_grade === 'C'" class="row small">
              <input v-model="force" type="checkbox" /> 我已了解风险，继续识别并逐行核对</label>
            <div class="row" style="margin-top: 8px">
              <button class="btn btn-primary"
                      :disabled="busy || !canVision || sheet.quality_grade === 'D' || (sheet.quality_grade === 'C' && !force)"
                      @click="$emit('recognize', force)">{{ busy ? '识别中，每页约 20—40 秒…' : '开始识别' }}</button>
              <button class="btn btn-danger btn-sm" @click="$emit('deleteImages')">删除原图</button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { currentUser } from '../../api'
import MaterialsPanel from '../MaterialsPanel.vue'

const props = defineProps<{ sheet: any; sys: any; busy: boolean }>()
const emit = defineEmits<{
  submitAnswers: [answers: Record<number, string>]; upload: [files: File[]]
  recognize: [force: boolean]; consent: [v: boolean]; deleteImages: []
}>()

const mode = ref<'type' | 'photo'>(props.sheet.paper ? 'type' : 'photo')
const force = ref(false)
const focusQ = ref<number | null>(null)
const fileInput = ref<HTMLInputElement>()
const DRAFT_KEY = `sheet-draft-${props.sheet.id}`
const answers = reactive<Record<number, string>>(loadDraft())

const canVision = computed(() => props.sys?.llm_enabled && currentUser.value?.consent_vision === true)
const consentNeeded = computed(() => props.sys?.llm_enabled && currentUser.value?.consent_vision == null)
const currentRefs = computed(() => props.sheet.questions.find((q: any) => q.no === focusQ.value)?.material_refs)
const wc = (s?: string) => (s || '').replace(/\s/g, '').length
const over = (q: any) => q.word_max && wc(answers[q.no]) > q.word_max
const answered = computed(() => props.sheet.questions.filter((q: any) => wc(answers[q.no]) >= 5).length)

function loadDraft(): Record<number, string> {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') } catch { return {} }
}
function saveDraft() {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify(answers)) } catch { /* 隐私模式不可写 */ }
}
function cleaned() {
  const out: Record<number, string> = {}
  for (const q of props.sheet.questions) if (wc(answers[q.no]) >= 5) out[q.no] = answers[q.no]
  try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
  return out
}
function upload() {
  const files = Array.from(fileInput.value?.files || [])
  if (files.length) emit('upload', files)
  if (fileInput.value) fileInput.value.value = ''
}
</script>
