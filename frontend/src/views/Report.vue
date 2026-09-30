<template>
  <div v-if="r">
    <div class="page-head">
      <h1>批改报告</h1>
      <span class="tag" :class="r.method === 'llm' ? 'tag-brand' : 'tag-warn'">{{ r.method_label }}</span>
      <span class="faint">{{ r.created_at }} · 第 {{ r.version.version_no }} 版（{{ r.version.kind_label }}）</span>
      <span class="spacer" />
      <button v-if="sub?.sheet_id && isOwner" class="btn" @click="router.push(`/grade/${sub.sheet_id}`)">整卷结果</button>
      <button class="btn" @click="router.push('/history')">我的作答</button>
    </div>

    <div v-if="sub?.question" class="card" style="padding: 10px 16px">
      <div class="row">
        <b>第 {{ sub.question.no }} 题</b>
        <span class="tag tag-brand">{{ sub.question.qtype_label }}</span>
        <span class="faint">{{ sub.question.full_score }} 分</span>
        <span class="spacer" style="flex: 1" />
        <button class="btn btn-sm" @click="showMat = !showMat">{{ showMat ? '收起材料' : '看给定资料' }}</button>
      </div>
      <p class="small" style="margin: 6px 0 0">{{ sub.question.stem }}</p>
    </div>
    <MaterialsPanel v-if="showMat && sub?.question" :paper-id="sub.question.paper_id" :refs="sub.question.material_refs" />

    <div class="card">
      <div class="row" style="gap: 32px; align-items: flex-end">
        <div>
          <div class="faint">预计得分</div>
          <div class="stat num">{{ r.score }}<small> / {{ r.full_score }}</small></div>
        </div>
        <div>
          <div class="faint">合理区间</div>
          <div class="num" style="font-size: 18px">{{ r.score_low }}—{{ r.score_high }}</div>
        </div>
        <div>
          <div class="faint">评分置信度</div>
          <div style="font-size: 18px">
            <span class="tag" :class="BAND_CLASS[r.confidence_band]">{{ r.confidence_band }}</span>
            <span class="num"> {{ Math.round(r.confidence * 100) }}%</span>
          </div>
        </div>
        <div v-if="r.teacher_score !== null">
          <div class="faint">教师复核分</div>
          <div class="stat num">{{ r.teacher_score }}</div>
        </div>
      </div>
      <details style="margin-top: 8px">
        <summary class="faint" style="cursor: pointer">置信度怎么算的</summary>
        <p class="small muted" style="margin: 6px 0 0">
          题目匹配 {{ r.confidence_factors.match }} × 识别质量 {{ r.confidence_factors.ocr }} ×
          证据通过率 {{ r.confidence_factors.evidence }} × 复核一致 {{ r.confidence_factors.agreement }}。
          这是系统对本次评分稳定性的自评，不是统计意义上的概率。
        </p>
      </details>
      <div v-for="n in noticeLines" :key="n" class="alert alert-warn" style="margin: 8px 0 0">{{ n }}</div>
      <div v-if="r.review_status === 'queued'" class="alert alert-info" style="margin: 8px 0 0">
        已进入教师复核队列（低置信度或有申诉），复核后这里会显示教师结论。</div>
      <div v-if="r.teacher_note" class="alert alert-ok" style="margin: 8px 0 0">教师意见：{{ r.teacher_note }}</div>
      <p class="faint" style="margin: 8px 0 0">{{ r.disclaimer }}</p>
    </div>

    <div class="grid grid-2">
      <div><AnswerPanel :review="r" :can-appeal="isOwner" @appeal="openAppeal" /></div>
      <div><LedgerPanel :review="r" :can-appeal="isOwner" @appeal="openAppeal" /></div>
    </div>

    <div v-if="r.appeals.length" class="card">
      <div class="card-title"><h2>我的申诉</h2></div>
      <div v-for="a in r.appeals" :key="a.id" class="small" style="margin-bottom: 8px">
        <b>{{ a.point_label }}</b>
        <span class="tag" :class="a.status === 'resolved' ? 'tag-ok' : 'tag-warn'">{{ a.status === 'resolved' ? '已处理' : '待教师复核' }}</span>
        <div class="muted">理由：{{ a.reason }}</div>
        <div class="faint">自动重检：{{ a.recheck.note }}</div>
        <div v-if="a.decision">教师结论：{{ a.decision }}</div>
      </div>
    </div>

    <CoachPanel v-if="sub" :review="r" :versions="sub.versions" :is-owner="isOwner" @revise="revise" />

    <details class="card">
      <summary style="cursor: pointer"><b>批改过程</b> <span class="faint">智能体各环节的执行记录</span></summary>
      <table class="table" style="margin-top: 8px">
        <tbody>
          <tr v-for="(t, i) in r.trace" :key="i"><td style="width: 90px">{{ t.node }}</td><td>{{ t.detail }}</td>
            <td class="faint num" style="width: 70px">{{ t.ms }} ms</td></tr>
        </tbody>
      </table>
      <p class="faint">{{ r.model ? `模型 ${r.model}，提示词版本 ${r.prompt_version}` : '规则引擎' }}
        <span v-if="r.rubric_version">；评分配置 v{{ r.rubric_version }}</span></p>
    </details>

    <div v-if="appealFor" class="modal-mask" @click.self="appealFor = null">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="appeal-title">
        <h2 id="appeal-title">评分申诉</h2>
        <p class="small">评分点：<b>{{ appealPoint?.label }}</b>（当前判为{{ appealPoint?.status_label }}）</p>
        <p class="faint">说明你认为判错的理由。引用自己答案原文时用「」括起来，系统会先核对原文，再交给教师复核。</p>
        <textarea v-model="appealReason" class="input" rows="4" aria-label="申诉理由" />
        <div v-if="appealErr" class="alert alert-danger" style="margin-top: 8px">{{ appealErr }}</div>
        <div class="modal-foot">
          <button class="btn" @click="appealFor = null">取消</button>
          <button class="btn btn-primary" :disabled="appealReason.trim().length < 4" @click="submitAppeal">提交申诉</button>
        </div>
      </div>
    </div>

    <div v-if="regrading" class="modal-mask">
      <div class="modal" aria-live="polite"><h2>正在复评…</h2><p class="muted small">完成后自动跳转到新版本的报告。</p></div>
    </div>
  </div>
  <div v-else-if="err" class="alert alert-danger">{{ err }}</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, currentUser, waitGraded } from '../api'
import { toast } from '../toast'
import AnswerPanel from './report/AnswerPanel.vue'
import CoachPanel from './report/CoachPanel.vue'
import LedgerPanel from './report/LedgerPanel.vue'
import MaterialsPanel from './MaterialsPanel.vue'

const showMat = ref(false)

const route = useRoute()
const router = useRouter()
const r = ref<any>(null)
const sub = ref<any>(null)
const err = ref('')
const regrading = ref(false)
const appealFor = ref<number | null>(null)
const appealReason = ref('')
const appealErr = ref('')
const BAND_CLASS: Record<string, string> = { 高: 'tag-ok', 中: 'tag-warn', 低: 'tag-danger' }

// 学员只能看到自己的报告；教师从复核队列进来时不显示申诉和修改入口
const isOwner = computed(() => currentUser.value?.role !== 'teacher')
const noticeLines = computed(() => (r.value?.notice || '').split('\n').filter(Boolean))
const appealPoint = computed(() => r.value?.points.find((p: any) => p.id === appealFor.value))

async function load() {
  try {
    r.value = await api.review(Number(route.params.id))
    sub.value = await api.submission(r.value.submission_id)
  } catch (e: any) { err.value = e.friendly }
}
onMounted(load)

function openAppeal(pid: number) {
  appealFor.value = pid
  appealReason.value = ''
  appealErr.value = ''
}

async function submitAppeal() {
  try {
    const res = await api.appeal(r.value.id, appealFor.value!, appealReason.value)
    toast(res.message)
    appealFor.value = null
    await load()
  } catch (e: any) { appealErr.value = e.friendly }
}

async function revise(text: string, timed: boolean) {
  try {
    await api.revise(r.value.submission_id, text, timed ? 'timed_rewrite' : 'self_revised')
    regrading.value = true
    const s = await waitGraded(r.value.submission_id)
    regrading.value = false
    if (s.status === 'failed') { err.value = `复评失败：${s.error}`; return }
    router.push(`/report/${s.latest_review_id}`)
  } catch (e: any) {
    regrading.value = false
    toast(e.friendly || e.message)
  }
}
</script>
