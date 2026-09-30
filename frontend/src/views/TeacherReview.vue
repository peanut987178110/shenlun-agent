<template>
  <div v-if="r">
    <div class="page-head">
      <h1>教师复核 · {{ r.student }}</h1>
      <span class="tag" :class="r.method === 'llm' ? 'tag-brand' : 'tag-warn'">{{ r.method_label }}</span>
      <span class="spacer" />
      <button class="btn" @click="router.push('/teacher')">返回队列</button>
    </div>

    <div class="grid grid-2">
      <div>
        <div class="card">
          <h2 style="margin-bottom: 8px">题目</h2>
          <p class="small">{{ r.question?.stem || r.custom_stem }}</p>
          <details v-if="r.question?.reference_answer">
            <summary class="faint" style="cursor: pointer">参考答案</summary>
            <p class="small pre">{{ r.question.reference_answer }}</p>
          </details>
        </div>
        <AnswerPanel :review="r" :can-appeal="false" />
      </div>

      <div>
        <div v-if="r.appeals.length" class="card">
          <h2 style="margin-bottom: 8px">学员申诉</h2>
          <div v-for="a in r.appeals" :key="a.id" class="ann" style="cursor: default">
            <b>{{ a.point_label }}</b>
            <div class="small">理由：{{ a.reason }}</div>
            <div class="faint">自动重检：原判 {{ a.recheck.original_status }}，规则重匹配 {{ a.recheck.rule_status || '—' }}。{{ a.recheck.note }}</div>
            <div v-if="a.recheck.quoted_found?.length" class="faint">学员引用的原文已在答案中找到：{{ a.recheck.quoted_found.join('；') }}</div>
            <input v-if="a.status !== 'resolved'" v-model="decisions[a.id]" class="input" style="margin-top: 6px"
                   placeholder="复核结论（必填）" :aria-label="`对「${a.point_label}」的复核结论`" />
            <div v-else class="small">结论：{{ a.decision }}</div>
          </div>
        </div>

        <div class="card">
          <h2 style="margin-bottom: 8px">逐点复核</h2>
          <div v-for="p in r.points" :key="p.id" class="ann" style="cursor: default">
            <div class="row" style="flex-wrap: nowrap">
              <b style="flex: 1" class="small">{{ p.label }}</b>
              <span class="faint num">{{ p.max }} 分</span>
              <select v-model="fixes[p.id]" class="input" style="width: 110px" :aria-label="`${p.label}的判定`">
                <option v-for="(v, k) in STATUS" :key="k" :value="k">{{ v }}</option>
              </select>
            </div>
            <div class="faint">AI：{{ p.status_label }}。{{ p.reason }}</div>
            <div v-if="p.quote" class="small">「{{ p.quote }}」</div>
          </div>
          <div class="field" style="margin-top: 12px">
            <label for="ts">最终分数（满分 {{ r.full_score }}，AI 评 {{ r.score }}）</label>
            <input id="ts" v-model.number="score" type="number" class="input" min="0" :max="r.full_score" step="0.5" />
          </div>
          <div class="field">
            <label for="tn">给学员的意见</label>
            <textarea id="tn" v-model="note" class="input" rows="3" />
          </div>
          <div v-if="err" class="alert alert-danger">{{ err }}</div>
          <button class="btn btn-primary" :disabled="busy || r.review_status === 'reviewed'" @click="submit">
            {{ r.review_status === 'reviewed' ? '已复核' : '提交复核' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { toast } from '../toast'
import AnswerPanel from './report/AnswerPanel.vue'

const route = useRoute()
const router = useRouter()
const r = ref<any>(null)
const fixes = reactive<Record<number, string>>({})
const decisions = reactive<Record<number, string>>({})
const score = ref(0)
const note = ref('')
const err = ref('')
const busy = ref(false)
const STATUS: Record<string, string> = {
  hit: '完整命中', partial: '部分命中', disputed: '表达争议', miss: '未命中', beyond: '材料外推', duplicate: '重复',
}

onMounted(async () => {
  r.value = await api.teacherReview(Number(route.params.id))
  for (const p of r.value.points) fixes[p.id] = p.status
  score.value = r.value.teacher_score ?? r.value.score
  note.value = r.value.teacher_note || ''
})

async function submit() {
  const open = r.value.appeals.filter((a: any) => a.status !== 'resolved')
  if (open.some((a: any) => !(decisions[a.id] || '').trim())) {
    err.value = '请为每条申诉填写复核结论'
    return
  }
  busy.value = true
  err.value = ''
  try {
    await api.submitTeacherReview(r.value.id, {
      points: r.value.points.filter((p: any) => fixes[p.id] !== p.status).map((p: any) => ({ id: p.id, status: fixes[p.id] })),
      teacher_score: score.value, note: note.value,
      appeals: open.map((a: any) => ({ id: a.id, decision: decisions[a.id] })),
    })
    toast('复核已提交')
    router.push('/teacher')
  } catch (e: any) { err.value = e.friendly } finally { busy.value = false }
}
</script>
