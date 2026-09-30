<template>
  <div class="card" aria-live="polite">
    <div class="card-title">
      <h2>{{ grading ? '正在批改…' : '批改完成' }}</h2>
      <span v-if="sheet.paper" class="faint">{{ sheet.paper.name }}</span>
    </div>
    <div v-if="!grading && total" class="row" style="gap: 24px; margin-bottom: 12px">
      <div><div class="faint">本次合计</div>
        <div class="stat num">{{ total.score }}<small> / {{ total.full }}</small></div></div>
      <div v-if="!sheet.scope_all" class="faint" style="align-self: flex-end">只作答了部分题目，合计只算已作答的题</div>
    </div>
    <p v-if="grading" class="muted small">每道题单独批改，并行进行，一般 1—2 分钟。可以离开此页，之后在「我的作答」里查看。</p>
    <table class="table">
      <thead><tr><th>题号</th><th>题型</th><th>得分</th><th>置信度</th><th>状态</th><th /></tr></thead>
      <tbody>
        <tr v-for="it in sheet.items" :key="it.submission_id">
          <td>第 {{ it.question_no }} 题</td>
          <td>{{ QTYPES[it.qtype] }}</td>
          <td class="num">{{ it.score !== null ? `${it.score} / ${it.full_score}` : '—' }}
            <span v-if="it.method === 'rule'" class="tag tag-warn">规则</span></td>
          <td class="num">{{ it.confidence !== null ? Math.round(it.confidence * 100) + '%' : '—' }}</td>
          <td>
            <span v-if="it.status === 'grading'" class="tag">批改中</span>
            <span v-else-if="it.status === 'failed'" class="tag tag-danger" :title="it.error">失败</span>
            <span v-else class="tag tag-ok">已批改</span>
          </td>
          <td><button v-if="it.review_id" class="btn btn-sm btn-primary" @click="router.push(`/report/${it.review_id}`)">看报告</button></td>
        </tr>
      </tbody>
    </table>
    <div v-for="it in sheet.items.filter((x: any) => x.status === 'failed')" :key="'e' + it.submission_id"
         class="alert alert-danger" style="margin-top: 8px">第 {{ it.question_no }} 题批改失败：{{ it.error }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { QTYPES } from '../../api'

const props = defineProps<{ sheet: any }>()
const router = useRouter()
const grading = computed(() => props.sheet.items.some((i: any) => i.status === 'grading'))
const total = computed(() => {
  const done = props.sheet.items.filter((i: any) => i.score !== null)
  if (!done.length) return null
  return { score: Math.round(done.reduce((s: number, i: any) => s + i.score, 0) * 10) / 10,
           full: done.reduce((s: number, i: any) => s + i.full_score, 0) }
})
</script>
