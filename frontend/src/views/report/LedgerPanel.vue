<template>
  <div class="card">
    <div class="card-title"><h2>分项得分</h2></div>
    <div v-for="d in review.dimensions" :key="d.key" style="margin-bottom: 10px">
      <div class="row">
        <span style="flex: 1">{{ d.name }} <span class="faint">{{ d.mode === 'points' ? '要点型' : '等级型' }}</span></span>
        <b class="num">{{ d.got }}</b><span class="faint num">/ {{ d.max }}</span>
      </div>
      <div class="bar"><i :style="{ width: (d.max ? (100 * d.got) / d.max : 0) + '%' }" /></div>
      <div class="faint">{{ d.reason }}</div>
    </div>
    <div v-if="review.word_penalty" class="small" style="color: var(--danger)">字数扣分 −{{ review.word_penalty }}</div>
  </div>

  <div v-if="review.suggestions.length" class="card">
    <div class="card-title"><h2>先改哪里最划算</h2></div>
    <table class="table">
      <thead><tr><th>修改</th><th>耗时</th><th>预计提升</th><th>优先级</th></tr></thead>
      <tbody>
        <tr v-for="(s, i) in review.suggestions" :key="i">
          <td>{{ s.action }}</td>
          <td class="num">{{ s.minutes }} 分钟</td>
          <td class="num">{{ s.gain_low }}—{{ s.gain_high }} 分</td>
          <td><span class="tag" :class="s.priority === '高' ? 'tag-danger' : s.priority === '中' ? 'tag-warn' : ''">{{ s.priority }}</span></td>
        </tr>
      </tbody>
    </table>
    <p class="faint" style="margin-top: 6px">增分预测用于确定修改优先级，不等同于考试实际得分变化。</p>
  </div>

  <div v-if="review.points.length" class="card">
    <div class="card-title"><h2>评分账本</h2><span class="faint">每个得分点的材料依据与判断</span></div>
    <div v-for="p in review.points" :key="p.id" class="ann" style="cursor: default">
      <div class="row">
        <span class="tag" :class="STATUS_CLASS[p.status]">{{ p.status_label }}</span>
        <b style="flex: 1">{{ p.label }}</b>
        <span class="num">{{ p.got }} / {{ p.max }}</span>
      </div>
      <div class="small" style="margin-top: 6px">
        <div><span class="faint">你的答案：</span>{{ p.quote ? `「${p.quote}」` : '（未找到对应表述）' }}</div>
        <div class="muted"><span class="faint">判断：</span>{{ p.reason }}
          <span v-if="p.rechecked" class="tag">已复核</span>
          <span v-if="p.teacher_fixed" class="tag tag-brand">教师改判（AI 原判 {{ p.ai_status }}）</span></div>
        <details v-if="p.material_text">
          <summary class="faint" style="cursor: pointer">材料依据：{{ p.material_ref }}</summary>
          <p class="small muted pre" style="margin: 4px 0 0">{{ p.material_text }}</p>
        </details>
        <div v-else-if="p.material_ref" class="faint">材料依据：{{ p.material_ref }}</div>
      </div>
      <button v-if="canAppeal && p.status !== 'hit'" class="btn btn-sm" style="margin-top: 6px"
              @click="$emit('appeal', p.id)">我认为判错了</button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ review: any; canAppeal: boolean }>()
defineEmits<{ appeal: [pointId: number] }>()
const STATUS_CLASS: Record<string, string> = {
  hit: 'tag-ok', partial: 'tag-warn', disputed: 'tag-warn', miss: 'tag-danger', beyond: 'tag-danger', duplicate: '',
}
</script>
