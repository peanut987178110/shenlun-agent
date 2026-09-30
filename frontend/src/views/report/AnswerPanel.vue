<template>
  <div class="card">
    <div class="card-title">
      <h2>答案批注</h2>
      <span class="faint">{{ review.version.kind_label }} · {{ review.word_count }} 字</span>
    </div>
    <div class="row small" style="margin-bottom: 8px">
      <span v-for="c in LEGEND" :key="c.k" class="row" style="gap: 4px"><i class="dot" :class="`dot-${c.k}`" />{{ c.t }}</span>
    </div>
    <div class="answer" aria-label="答案原文与批注">
      <template v-for="(seg, i) in segments" :key="i">
        <span v-if="seg.ann" class="mk" :class="[`mk-${seg.ann.color}`, { active: active === seg.ann.id }]"
              role="button" tabindex="0" :aria-label="`${seg.ann.type}：${seg.text}`"
              @click="active = seg.ann.id" @keydown.enter="active = seg.ann.id">{{ seg.text }}</span>
        <template v-else>{{ seg.text }}</template>
      </template>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <h2>问题清单</h2>
      <span class="faint">默认只展开影响最大的 5 条</span>
      <button class="btn btn-sm" @click="showAll = !showAll">{{ showAll ? '收起' : `显示全部（${problems.length}）` }}</button>
    </div>
    <div v-if="!problems.length" class="muted small">没有发现明显问题</div>
    <div v-for="a in visible" :key="a.id" class="ann" :class="{ active: active === a.id }" @click="active = a.id">
      <div class="row">
        <i class="dot" :class="`dot-${a.color}`" />
        <b>{{ a.type }}</b>
        <span v-if="a.impact" class="faint">影响约 {{ a.impact }} 分</span>
        <span class="faint">置信度 {{ Math.round(a.confidence * 100) }}%</span>
        <span class="spacer" style="flex: 1" />
        <button v-if="a.appealable && canAppeal" class="btn btn-sm" @click.stop="$emit('appeal', a.point_id)">申诉</button>
      </div>
      <p v-if="a.quote" class="small" style="margin: 6px 0">「{{ a.quote }}」</p>
      <p class="small muted" style="margin: 0">{{ a.why }}</p>
      <p v-if="a.fix" class="small" style="margin: 4px 0 0">改法：{{ a.fix }}</p>
      <p v-if="a.rule" class="faint" style="margin: 2px 0 0">依据：{{ a.rule }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{ review: any; canAppeal: boolean }>()
defineEmits<{ appeal: [pointId: number] }>()

const LEGEND = [{ k: 'red', t: '严重' }, { k: 'orange', t: '明显' }, { k: 'yellow', t: '建议优化' },
  { k: 'blue', t: '表达' }, { k: 'green', t: '得分点' }]
const active = ref<number | null>(null)
const showAll = ref(false)

const problems = computed(() => props.review.annotations.filter((a: any) => a.color !== 'green'))
const visible = computed(() => (showAll.value ? problems.value : problems.value.filter((a: any) => !a.folded)))

/** 把批注引用定位到原文上。按列表顺序（问题在前、得分点在后）占位，重叠的后来者跳过。 */
const segments = computed(() => {
  const text: string = props.review.version.text
  const spans: { s: number; e: number; ann: any }[] = []
  const shown = props.review.annotations.filter((a: any) => a.quote && (showAll.value || !a.folded))
  for (const a of shown) {
    const s = text.indexOf(a.quote)
    if (s < 0) continue
    const e = s + a.quote.length
    if (spans.some((x) => s < x.e && e > x.s)) continue
    spans.push({ s, e, ann: a })
  }
  spans.sort((a, b) => a.s - b.s)
  const out: { text: string; ann?: any }[] = []
  let pos = 0
  for (const sp of spans) {
    if (sp.s > pos) out.push({ text: text.slice(pos, sp.s) })
    out.push({ text: text.slice(sp.s, sp.e), ann: sp.ann })
    pos = sp.e
  }
  if (pos < text.length) out.push({ text: text.slice(pos) })
  return out
})
</script>
