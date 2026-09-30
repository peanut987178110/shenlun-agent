<template>
  <div class="print-root">
    <div class="no-print bar">
      <b>导出 PDF</b>
      <label class="row small"><input v-model="withMarks" type="checkbox" :disabled="!marks.length" />
        带上我的资料标记<span v-if="!marks.length" class="faint">（这份没有标记）</span></label>
      <label class="row small"><input v-model="withSheet" type="checkbox" /> 附方格答题纸</label>
      <span style="flex: 1" />
      <button class="btn btn-primary" :disabled="!paper" @click="print">打印 / 另存为 PDF</button>
      <span class="faint">在打印窗口的「目标打印机」里选「另存为 PDF」</span>
    </div>
    <div v-if="err" class="no-print alert alert-danger">{{ err }}</div>

    <article v-if="paper" class="paper">
      <header class="head">
        <h1>{{ paper.name }}</h1>
        <p>{{ paper.category }}<template v-if="paper.origin === 'generated'"> · AI 模拟卷（材料为虚构情境）</template></p>
        <p>满分 100 分　时限 150 分钟</p>
      </header>

      <section class="notice">
        <h2>注意事项</h2>
        <p>1. 本题本由给定资料与作答要求两部分构成。考试时限为 150 分钟，其中阅读给定资料参考时限为 40 分钟，作答参考时限为 110 分钟。</p>
        <p>2. 请在答题卡上指定位置作答，未按要求作答的，不得分。</p>
      </section>

      <section>
        <h2>给定资料</h2>
        <div v-for="g in grouped" :key="g.no" class="mat">
          <h3>资料 {{ g.no }}</h3>
          <p v-for="m in g.items" :key="m.paragraph"><span v-for="(s, i) in segments(m.text, shownMarks, m.no, m.paragraph)" :key="i"
               :class="segClass(s)">{{ s.text }}</span></p>
        </div>
      </section>

      <section class="questions">
        <h2>作答要求</h2>
        <div v-for="q in paper.questions" :key="q.id" class="q">
          <p class="pre">{{ /^\s*([一二三四五六七八九十]|\d+)\s*[、.．]/.test(q.stem) ? q.stem : `${CN[q.no]}、${q.stem}` }}</p>
        </div>
      </section>

      <template v-if="withSheet">
        <section v-for="q in paper.questions" :key="'s' + q.id" class="sheet">
          <h2>答题纸 · 第 {{ q.no }} 题（{{ q.full_score }} 分）</h2>
          <div class="grid-paper" :style="{ height: rowsFor(q) * CELL + 'mm' }" />
          <p class="small">每行 25 格{{ q.word_max ? `，本题字数上限 ${q.word_max}` : '' }}</p>
        </section>
      </template>
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { segClass, segments, type Mark } from '../marks'

const CN = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
const CELL = 7.2 // mm，25 格正好铺满 A4 版心宽度（180mm）
const route = useRoute()
const paper = ref<any>(null)
const marks = ref<Mark[]>([])
const withMarks = ref(true)
const withSheet = ref(false)
const err = ref('')

const shownMarks = computed(() => (withMarks.value ? marks.value : []))
const grouped = computed(() => {
  const out: { no: number; items: any[] }[] = []
  for (const m of paper.value?.materials || []) {
    let g = out.find((x) => x.no === m.no)
    if (!g) out.push((g = { no: m.no, items: [] }))
    g.items.push(m)
  }
  return out
})
// 按字数上限留格子，多留 20%；没写字数的按 400 字
const rowsFor = (q: any) => Math.ceil(((q.word_max || 400) * 1.2) / 25)

onMounted(async () => {
  try {
    paper.value = await api.paper(Number(route.params.id))
    const sid = Number(route.query.sheet)
    if (sid) marks.value = (await api.sheet(sid)).marks || []
    document.title = paper.value.name  // 另存为 PDF 时的默认文件名
    if (route.query.auto) {
      await nextTick()
      setTimeout(print, 300)
    }
  } catch (e: any) { err.value = e.friendly }
})

function print() { window.print() }
</script>

<style scoped>
.print-root { background: #e9ecef; min-height: 100vh; padding: 16px; color-scheme: light; }
.bar { position: sticky; top: 0; z-index: 5; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  background: #fff; color: #1b2027; border: 1px solid #dde1e7; border-radius: 8px; padding: 10px 14px; margin: 0 auto 16px; max-width: 210mm; }
.paper { background: #fff; color: #111; max-width: 210mm; margin: 0 auto; padding: 18mm 15mm;
  font-family: "SimSun", "Songti SC", "Noto Serif SC", serif; font-size: 11pt; line-height: 1.85;
  /* 屏幕预览也用浅色，打印出来是什么样就看到什么样 */
  --pen-yellow: #fff08a; --pen-green: #c7f0c2; --pen-pink: #ffd0e0; --pen-line: #d32f2f; }
.head { text-align: center; margin-bottom: 8mm; }
.head h1 { font-size: 18pt; margin-bottom: 2mm; font-family: "SimHei", "Microsoft YaHei", sans-serif; }
.head p { margin: 0; font-size: 10pt; }
h2 { font-size: 13pt; margin: 6mm 0 3mm; font-family: "SimHei", "Microsoft YaHei", sans-serif; }
h3 { font-size: 11.5pt; margin: 4mm 0 1mm; font-family: "SimHei", "Microsoft YaHei", sans-serif; }
.mat p, .notice p { text-indent: 2em; margin: 0 0 1.5mm; }
.notice p { text-indent: 0; font-size: 10pt; }
.q { margin-bottom: 4mm; break-inside: avoid; }
.sheet { break-before: page; }
.grid-paper { width: 180mm; border: 1px solid #c33;
  background-image: linear-gradient(#e7a7a7 1px, transparent 1px), linear-gradient(90deg, #e7a7a7 1px, transparent 1px);
  background-size: 7.2mm 7.2mm; }
@media (max-width: 760px) { .paper { padding: 8mm 5mm; } .grid-paper { width: 100%; } }
</style>

<style>
@media print {
  @page { size: A4; margin: 15mm 15mm 18mm; }
  html, body, #app { background: #fff !important; }
  .no-print { display: none !important; }
  .print-root { padding: 0 !important; background: #fff !important; }
  .print-root .paper { padding: 0 !important; max-width: none !important; box-shadow: none !important; }
  /* 高亮、方格线默认不会被打印，强制保留 */
  .print-root * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
</style>
