<template>
  <div>
    <div class="page-head"><h1>能力画像</h1></div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-title"><h2>能力维度</h2><span class="faint">按题型得分率累积，规则评分按一半权重计入</span></div>
        <div v-for="a in abilities" :key="a.dimension" class="row" style="margin-bottom: 8px; flex-wrap: nowrap">
          <span style="width: 80px">{{ a.dimension }}</span>
          <div class="bar" style="flex: 1"><i :style="{ width: (a.score ?? 0) + '%' }" /></div>
          <span class="num" style="width: 36px; text-align: right">{{ a.score ?? '—' }}</span>
          <span class="tag" style="width: 72px; text-align: center">{{ a.mastery }}</span>
          <span class="faint" style="width: 16px">{{ TREND[a.trend] || '' }}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title"><h2>错误模式库</h2></div>
        <div v-if="!errors.length" class="muted small">暂无记录</div>
        <div v-for="e in errors" :key="e.error_type" class="ann" style="cursor: default">
          <div class="row">
            <b style="flex: 1">{{ e.error_type }}</b>
            <span class="tag" :class="e.severity === 'high' ? 'tag-danger' : 'tag-warn'">{{ e.severity === 'high' ? '高影响' : '中影响' }}</span>
            <span class="tag" :class="e.mastery_status === 'mastered' ? 'tag-ok' : ''">{{ MASTERY[e.mastery_status] }}</span>
          </div>
          <div class="small muted">累计 {{ e.frequency }} 次，最近 5 次批改中 {{ e.recent_frequency }} 次 · 最近 {{ e.last_seen_at }}</div>
          <div class="faint">常在：{{ e.trigger_conditions.join('、') }}</div>
          <div v-if="e.example" class="faint">例：{{ e.example }}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><h2>训练处方</h2><span class="faint">同一错误出现 2 次后生成</span></div>
      <div v-if="!rx.length" class="muted small">暂无处方</div>
      <div v-for="p in rx" :key="p.id" class="ann" style="cursor: default">
        <div class="row">
          <b style="flex: 1">{{ p.goal }}</b>
          <span class="tag">{{ p.error_type }} · {{ p.frequency }} 次</span>
          <span class="tag" :class="p.status === 'passed' ? 'tag-ok' : p.status === 'failed' ? 'tag-danger' : 'tag-brand'">
            {{ RX_STATUS[p.status] }}</span>
        </div>
        <div class="grid grid-2" style="margin-top: 8px; gap: 8px">
          <div class="small">
            <div class="faint">训练步骤（约 {{ p.est_minutes }} 分钟）</div>
            <ol style="margin: 4px 0; padding-left: 18px"><li v-for="s in p.steps" :key="s">{{ s }}</li></ol>
          </div>
          <div class="small">
            <div class="faint">通过标准</div>
            <ul style="margin: 4px 0; padding-left: 18px"><li v-for="s in p.pass_criteria" :key="s">{{ s }}</li></ul>
            <div class="faint">建议复测时间：{{ p.retest_after }}</div>
          </div>
        </div>
        <div v-if="p.retest_question" class="small" style="margin-top: 6px">
          <span class="faint">复测题（换主题）：</span>{{ p.retest_question.stem.slice(0, 60) }}…
        </div>
        <div v-if="p.result?.verdict" class="alert alert-warn" style="margin: 8px 0 0">{{ p.result.verdict }}</div>
        <button v-if="p.status === 'active' && p.retest_question_id" class="btn btn-sm btn-primary" style="margin-top: 8px"
                @click="retest(p.id)">开始复测</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const abilities = ref<any[]>([])
const errors = ref<any[]>([])
const rx = ref<any[]>([])
const TREND: Record<string, string> = { up: '↑', down: '↓', flat: '→' }
const MASTERY: Record<string, string> = { not_mastered: '未掌握', unstable: '不稳定', mastered: '已掌握' }
const RX_STATUS: Record<string, string> = { active: '进行中', passed: '已通过', failed: '未通过' }

onMounted(async () => {
  [abilities.value, errors.value, rx.value] = await Promise.all([api.abilities(), api.errors(), api.prescriptions()])
})

async function retest(id: number) {
  const r = await api.startRetest(id)
  router.push(`/grade/${r.sheet_id}`)
}
</script>
