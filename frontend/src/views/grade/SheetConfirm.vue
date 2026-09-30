<template>
  <!-- 核对识别结果：逐行确认文字、行类型、所属题号 -->
  <div v-if="!sheet.paper" class="card">
    <div class="card-title"><h2>这是哪套卷？</h2><span class="faint">按答案内容与各卷材料的重合度自动匹配</span></div>
    <label v-for="g in sheet.paper_guess" :key="g.paper_id" class="row"
           style="padding: 8px; border: 1px solid var(--border); border-radius: 6px; margin-bottom: 6px">
      <input v-model="guess" type="radio" :value="g.paper_id" />
      <b>{{ g.name }}</b>
      <span class="tag" :class="g.score >= 0.4 ? 'tag-ok' : g.score >= 0.2 ? 'tag-warn' : ''">
        匹配度 {{ Math.round(g.score * 100) }}%</span>
      <span class="faint">答案用词与材料重合 {{ Math.round(g.material_cover * 100) }}%</span>
    </label>
    <div v-if="!sheet.paper_guess?.length" class="muted small">没有可匹配的试卷，请在题库中选择。</div>
    <p v-else-if="sheet.paper_guess[0].score < 0.2" class="small" style="color: var(--warn)">
      匹配度都很低，这份答卷可能不是题库里的卷，请确认。</p>
    <button class="btn btn-primary" :disabled="!guess || busy" @click="$emit('setPaper', guess)">确认是这套卷</button>
  </div>

  <div v-else class="grid grid-2">
    <div class="card">
      <div class="card-title"><h2>原图</h2>
        <select v-if="sheet.pages.length" v-model.number="viewPage" class="input" style="width: auto" aria-label="选择页">
          <option v-for="pg in sheet.pages" :key="pg.page_no" :value="pg.page_no">第 {{ pg.page_no }} 页</option>
        </select>
      </div>
      <img v-if="imgUrl" :src="imgUrl" :alt="`答卷第 ${viewPage} 页原图`" style="width: 100%; border-radius: 6px" />
      <p v-else class="muted small">无原图（PDF 文字层或已删除）</p>
    </div>

    <div class="card">
      <div class="card-title"><h2>核对识别结果</h2><span class="faint">{{ sheet.ocr_note }}</span></div>
      <p class="small muted">黄色波浪线是识别把握较低的行。每行选好所属题号；只有「答案」行参与批改。
        在某一行点「以下归第 N 题」可以一次改掉后面所有行。</p>
      <div class="row small" style="margin-bottom: 8px">
        <span v-for="q in sheet.questions" :key="q.no" class="tag" :class="counts[q.no] ? 'tag-ok' : 'tag-warn'">
          第 {{ q.no }} 题 {{ counts[q.no] || 0 }} 字</span>
        <span v-if="counts[0]" class="tag tag-danger">未分配 {{ counts[0] }} 字</span>
      </div>
      <div class="lines">
        <div v-for="(ln, i) in lines" :key="i" class="row" style="margin-bottom: 4px; flex-wrap: nowrap">
          <span class="faint num" style="width: 40px">{{ ln.page }}-{{ ln.line }}</span>
          <input v-model="ln.text" class="input" :class="{ 'low-conf': ln.confidence < sheet.low_conf && !ln.edited }"
                 :aria-label="`第 ${ln.page} 页第 ${ln.line} 行`" @input="ln.edited = true; ln.confidence = 1"
                 @focus="viewPage = ln.page" />
          <select v-model="ln.kind" class="input" style="width: 70px" aria-label="行类型">
            <option value="answer">答案</option><option value="question">题目</option><option value="draft">草稿</option>
          </select>
          <select v-model="ln.qno" class="input" style="width: 84px" aria-label="所属题号">
            <option :value="null">未分配</option>
            <option v-for="q in sheet.questions" :key="q.no" :value="q.no">第 {{ q.no }} 题</option>
          </select>
          <select class="input" style="width: 40px; padding: 7px 2px" aria-label="从这一行起全部归到某题" title="从这一行起全部归到…"
                  @change="fillFrom(i, ($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).value = ''">
            <option value="">↓</option>
            <option v-for="q in sheet.questions" :key="q.no" :value="q.no">以下归第 {{ q.no }} 题</option>
          </select>
        </div>
      </div>
      <div class="row" style="margin-top: 8px">
        <button class="btn btn-sm" @click="lines.push({ page: 1, line: lines.length + 1, text: '', confidence: 1, kind: 'answer', qno: lines.at(-1)?.qno ?? null })">加一行</button>
        <span style="flex: 1" />
        <button class="btn btn-primary" :disabled="busy || !Object.keys(counts).some((k) => k !== '0' && counts[+k] >= 5)"
                @click="$emit('submit', lines)">确认并批改</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../../api'

const props = defineProps<{ sheet: any; busy: boolean }>()
defineEmits<{ setPaper: [paperId: number]; submit: [lines: any[]] }>()

const guess = ref<number | null>(props.sheet.paper_guess?.[0]?.paper_id ?? null)
const lines = ref<any[]>((props.sheet.ocr_lines || []).map((l: any) => ({ ...l })))
const viewPage = ref(props.sheet.pages[0]?.page_no || 1)
const imgUrl = ref('')

watch(() => props.sheet.ocr_lines, (v) => { lines.value = (v || []).map((l: any) => ({ ...l })) })

const counts = computed(() => {
  const c: Record<number, number> = {}
  for (const ln of lines.value) {
    if (ln.kind !== 'answer') continue
    const k = ln.qno ?? 0
    c[k] = (c[k] || 0) + ln.text.replace(/\s/g, '').length
  }
  return c
})

function fillFrom(i: number, v: string) {
  if (!v) return
  for (let j = i; j < lines.value.length; j++) lines.value[j].qno = Number(v)
}

watch(viewPage, async (p) => {
  if (imgUrl.value) URL.revokeObjectURL(imgUrl.value)
  imgUrl.value = ''
  const pg = props.sheet.pages.find((x: any) => x.page_no === p)
  if (pg?.has_image) imgUrl.value = await api.pageImageUrl(props.sheet.id, p).catch(() => '')
}, { immediate: true })
</script>

<style scoped>
.lines { max-height: 60vh; overflow-y: auto; }
</style>
