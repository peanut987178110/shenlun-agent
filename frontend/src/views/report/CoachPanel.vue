<template>
  <div v-if="review.diagnosis.length" class="card">
    <div class="card-title"><h2>为什么失分</h2></div>
    <div v-for="d in review.diagnosis" :key="d.error_type" style="margin-bottom: 12px">
      <b>{{ d.error_type }}</b>
      <div class="small" style="margin: 4px 0">{{ d.chain.join(' → ') }}</div>
      <div class="faint">建议训练：{{ d.recommended_training.join('；') }}</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><h2>修改提示</h2><span class="faint">逐级解锁，先自己改</span></div>
    <div v-for="lv in LEVELS" :key="lv.n" style="margin-bottom: 10px">
      <div class="row">
        <b>第 {{ lv.n }} 级 · {{ lv.t }}</b>
        <button v-if="level < lv.n" class="btn btn-sm" :disabled="lv.n > level + 1 || busy"
                @click="unlock(lv.n)">查看</button>
      </div>
      <template v-if="hints[`L${lv.n}`]">
        <p v-if="lv.n === 1" class="small">{{ hints.L1.summary }}</p>
        <ul v-else-if="lv.n === 2" class="small" style="margin: 4px 0; padding-left: 18px">
          <li v-for="h in hints.L2" :key="h.point_id">{{ h.hint }}</li>
        </ul>
        <ul v-else-if="lv.n === 3" class="small" style="margin: 4px 0; padding-left: 18px">
          <li v-for="h in hints.L3" :key="h.point_id">{{ h.label }}<span v-if="h.demo">：{{ h.demo }}</span></li>
        </ul>
        <div v-else>
          <p class="small pre">{{ hints.L4.reference_answer || '本题没有参考答案' }}</p>
          <p class="faint">{{ hints.L4.note }}</p>
        </div>
      </template>
    </div>
    <p v-if="level >= 3" class="faint">看过局部示范后提交的修改会记为「AI 指导版」。</p>
  </div>

  <div v-if="isOwner" class="card">
    <div class="card-title"><h2>二次修改</h2></div>
    <textarea v-model="draft" class="input" rows="10" aria-label="修改后的答案" />
    <div class="row" style="margin-top: 8px">
      <span class="faint num">{{ draft.replace(/\s/g, '').length }} 字</span>
      <label class="row small"><input v-model="timed" type="checkbox" /> 这是限时重写</label>
      <span style="flex: 1" />
      <button class="btn btn-primary" :disabled="busy || draft.trim() === review.version.text.trim()" @click="$emit('revise', draft, timed)">
        提交并复评</button>
    </div>
  </div>

  <div v-if="versions.length > 1" class="card">
    <div class="card-title"><h2>版本对比</h2>
      <select v-model.number="other" class="input" style="width: auto" aria-label="对比的版本">
        <option :value="0">选择要对比的版本</option>
        <option v-for="v in versions.filter((x: any) => x.review_id && x.review_id !== review.id)" :key="v.id" :value="v.review_id">
          第 {{ v.version_no }} 版（{{ v.score }} 分）</option>
      </select>
    </div>
    <template v-if="cmp">
      <p>得分 {{ cmp.old_score }} → <b>{{ cmp.new_score }}</b>
        <span class="tag" :class="cmp.score_delta > 0 ? 'tag-ok' : cmp.score_delta < 0 ? 'tag-danger' : ''">
          {{ cmp.score_delta > 0 ? '+' : '' }}{{ cmp.score_delta }}</span>
        <span class="faint">字数 {{ cmp.word_delta > 0 ? '+' : '' }}{{ cmp.word_delta }}</span></p>
      <p v-if="cmp.method_changed" class="alert alert-warn">两个版本的评分方式不同（模型 / 规则），分差不完全可比。</p>
      <p v-if="cmp.gained_points.length" class="small">新增得分点：{{ cmp.gained_points.join('；') }}</p>
      <p v-if="cmp.lost_points.length" class="small" style="color: var(--danger)">丢失得分点：{{ cmp.lost_points.join('；') }}</p>
      <p v-if="cmp.fixed_issues.length" class="small">修复问题：{{ cmp.fixed_issues.join('、') }}</p>
      <p v-if="cmp.new_issues.length" class="small" style="color: var(--danger)">新增问题：{{ cmp.new_issues.join('、') }}</p>
      <div class="answer small">
        <span v-for="(d, i) in cmp.diff" :key="i" :class="{ 'diff-add': d.op === 'add', 'diff-del': d.op === 'del' }">{{ d.text }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '../../api'

const props = defineProps<{ review: any; versions: any[]; isOwner: boolean }>()
defineEmits<{ revise: [text: string, timed: boolean] }>()

const LEVELS = [{ n: 1, t: '只看问题' }, { n: 2, t: '看提示' }, { n: 3, t: '局部示范' }, { n: 4, t: '参考答案' }]
const level = ref(0)
const hints = ref<any>({})
const busy = ref(false)
const draft = ref(props.review.version.text)
const timed = ref(false)
const other = ref(0)
const cmp = ref<any>(null)

async function unlock(n: number) {
  busy.value = true
  try {
    const r = await api.unlockHint(props.review.id, n)
    level.value = r.hint_level
    hints.value = r.hints
  } finally { busy.value = false }
}

// 已解锁过的级别，进页面时恢复显示
if (props.review.hint_level > 0) unlock(props.review.hint_level)

watch(other, async (v) => { cmp.value = v ? await api.compare(props.review.id, v) : null })
</script>
