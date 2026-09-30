<template>
  <div>
    <div class="page-head">
      <h1>你好，{{ user?.display_name }}</h1>
      <span class="spacer" />
      <button class="btn btn-primary" @click="router.push('/grade')">开始批改</button>
    </div>

    <!-- 首次进入：目标设置（PRD 8.1） -->
    <div v-if="user && !user.goal_set" class="card">
      <div class="card-title"><h2>先设置备考目标</h2><span class="faint">约 30 秒，之后可在设置里修改</span></div>
      <GoalForm @saved="load" />
    </div>

    <div v-if="d" class="grid grid-3">
      <div class="card">
        <div class="faint">目标</div>
        <div class="stat">{{ d.goal.target_score ?? '—' }}<small> 分</small></div>
        <div class="small muted">浙江省考 {{ d.goal.year || '' }} {{ d.goal.category || '未设置类别' }}
          <span v-if="d.goal.exam_date">· {{ d.goal.exam_date }}</span></div>
      </div>
      <div class="card">
        <div class="faint">平均得分率（每题取最新版本）</div>
        <div class="stat num">{{ d.avg_rate ?? '—' }}<small>%</small></div>
        <div class="small muted">共批改 {{ d.count }} 题</div>
      </div>
      <div class="card">
        <div class="faint">最近一次</div>
        <div v-if="d.last" class="stat num">{{ d.last.score }}<small> / {{ d.last.full_score }}</small></div>
        <div v-else class="stat">—</div>
        <button v-if="d.last" class="btn-link small" @click="router.push(`/report/${d.last.review_id}`)">查看报告</button>
      </div>
    </div>

    <div v-if="d" class="grid grid-2">
      <div class="card">
        <div class="card-title"><h2>今日训练处方</h2></div>
        <template v-if="d.today_prescription">
          <p><b>{{ d.today_prescription.goal }}</b>
            <span class="tag tag-warn">{{ d.today_prescription.error_type }} · 出现 {{ d.today_prescription.frequency }} 次</span></p>
          <ol class="small" style="padding-left: 18px; margin: 0 0 8px">
            <li v-for="s in d.today_prescription.steps" :key="s">{{ s }}</li>
          </ol>
          <button class="btn btn-sm" @click="router.push('/profile')">查看处方与复测</button>
        </template>
        <p v-else class="muted small">同一类错误出现两次后，这里会生成有步骤、有通过标准的训练处方。</p>
      </div>

      <div class="card">
        <div class="card-title"><h2>高频错误</h2></div>
        <div v-if="!d.top_errors.length" class="muted small">暂无记录</div>
        <div v-for="e in d.top_errors" :key="e.error_type" class="row" style="margin-bottom: 6px">
          <span style="flex: 1">{{ e.error_type }}</span>
          <span class="faint num">{{ e.frequency }} 次</span>
          <span class="tag" :class="e.mastery_status === 'mastered' ? 'tag-ok' : 'tag-warn'">
            {{ MASTERY[e.mastery_status] }}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title"><h2>待复盘</h2><span class="faint">得分率低于 80% 且还没改过</span></div>
        <div v-if="!d.pending_review.length" class="muted small">暂无</div>
        <div v-for="p in d.pending_review" :key="p.submission_id" class="row" style="margin-bottom: 6px">
          <span style="flex: 1">{{ p.question }}</span>
          <span class="num">{{ p.score }}/{{ p.full_score }}</span>
          <button class="btn btn-sm" @click="router.push(`/report/${p.review_id}`)">去修改</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title"><h2>得分率趋势</h2></div>
        <div v-if="!d.trend.length" class="muted small">完成批改后显示</div>
        <div v-else class="row" style="align-items: flex-end; height: 120px; gap: 6px" role="img"
             :aria-label="'最近得分率：' + d.trend.map((t: any) => t.rate + '%').join('，')">
          <div v-for="(t, i) in d.trend" :key="i" style="flex: 1; text-align: center">
            <div :style="{ height: t.rate + 'px', background: 'var(--brand)', borderRadius: '3px 3px 0 0', opacity: 0.8 }" />
            <div class="faint">{{ t.date }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="err" class="alert alert-danger">{{ err }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, currentUser } from '../api'
import GoalForm from './GoalForm.vue'

const router = useRouter()
const user = computed(() => currentUser.value)
const d = ref<any>(null)
const err = ref('')
const MASTERY: Record<string, string> = { not_mastered: '未掌握', unstable: '不稳定', mastered: '已掌握' }

async function load() {
  try {
    d.value = await api.dashboard()
    currentUser.value = await api.me()
  } catch (e: any) {
    err.value = e.friendly
  }
}
onMounted(load)
</script>
