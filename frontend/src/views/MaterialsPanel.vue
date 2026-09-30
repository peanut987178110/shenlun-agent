<template>
  <div class="card mat-panel">
    <div class="card-title">
      <h2>给定资料</h2>
      <span v-if="paper" class="faint">{{ paper.name }}</span>
      <span class="spacer" style="flex: 1" />
      <button v-if="paper" class="btn btn-sm" @click="exportPdf">导出 PDF</button>
    </div>
    <div v-if="err" class="alert alert-danger">{{ err }}</div>
    <div v-else-if="!paper" class="muted small">加载中…</div>
    <template v-else>
      <div v-if="paper.status === 'questions_only'" class="alert alert-warn">
        这套卷只收录了题目，材料全文暂缺。</div>

      <div v-if="editable" class="row small toolbar" role="toolbar" aria-label="资料标记工具">
        <span class="faint">标记：</span>
        <button v-for="t in MARK_TOOLS" :key="t.style" class="btn btn-sm" :class="{ 'btn-primary': tool === t.style }"
                :aria-pressed="tool === t.style" @click="tool = tool === t.style ? null : t.style">
          <span v-if="t.style !== 'underline'" class="pen-dot" :class="`mk-hl-${t.style}`" />
          <span v-else class="mk-ul">下划线</span>
          <template v-if="t.style !== 'underline'">{{ t.label }}</template>
        </button>
        <button class="btn btn-sm" :class="{ 'btn-primary': tool === 'erase' }" :aria-pressed="tool === 'erase'"
                @click="tool = tool === 'erase' ? null : 'erase'">橡皮擦</button>
        <button class="btn btn-sm" :disabled="!marks.length" @click="undo">撤销</button>
        <button class="btn btn-sm btn-danger" :disabled="!marks.length" @click="clearAll">清空</button>
        <span class="faint">{{ hint }}</span>
        <span class="small" aria-live="polite" :style="{ color: saveState === 'error' ? 'var(--danger)' : 'var(--text-2)', marginLeft: 'auto' }">
          {{ { saving: '保存中…', saved: '已保存', error: '保存失败，稍后自动重试', '': '' }[saveState] }}</span>
      </div>

      <div class="row small" style="margin-bottom: 8px">
        <button v-for="g in grouped" :key="g.no" class="btn btn-sm"
                :class="{ 'btn-primary': refs?.includes(g.no) }" @click="jump(g.no)">资料{{ g.no }}
          <span v-if="countOf(g.no)" class="faint">·{{ countOf(g.no) }}</span></button>
        <label v-if="refs?.length" class="row small" style="margin-left: auto">
          <input v-model="onlyRefs" type="checkbox" /> 只看本题相关资料</label>
      </div>
      <div ref="scroller" class="mat-scroll" :class="{ marking: tool && tool !== 'erase', erasing: tool === 'erase' }"
           @mouseup="onSelect" @touchend="onSelect">
        <section v-for="g in shown" :id="`mat-${uid}-${g.no}`" :key="g.no" style="margin-bottom: 16px">
          <h3>给定资料 {{ g.no }}</h3>
          <p v-for="m in g.items" :key="m.paragraph" class="small para" :data-no="m.no" :data-para="m.paragraph"
             style="text-indent: 2em; line-height: 1.9"><span v-for="(s, i) in segments(m.text, marks, m.no, m.paragraph)" :key="i"
               :class="segClass(s)" @click="erase(s)">{{ s.text }}</span></p>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { MARK_TOOLS, offsetsIn, segClass, segments, type Mark, type MarkStyle, type Seg } from '../marks'

const props = defineProps<{ paperId: number; refs?: number[]; sheetId?: number; initialMarks?: Mark[]; editable?: boolean }>()
const router = useRouter()
const paper = ref<any>(null)
const err = ref('')
const onlyRefs = ref(true)
const uid = Math.random().toString(36).slice(2, 7)
const marks = ref<Mark[]>([...(props.initialMarks || [])])
const tool = ref<MarkStyle | 'erase' | null>(null)
const saveState = ref<'' | 'saving' | 'saved' | 'error'>('')
const scroller = ref<HTMLElement>()
let timer: number | undefined

watch(() => props.paperId, async (id) => {
  paper.value = null
  try { paper.value = await api.paper(id) } catch (e: any) { err.value = e.friendly }
}, { immediate: true })

const grouped = computed(() => {
  const out: { no: number; items: any[] }[] = []
  for (const m of paper.value?.materials || []) {
    let g = out.find((x) => x.no === m.no)
    if (!g) out.push((g = { no: m.no, items: [] }))
    g.items.push(m)
  }
  return out
})
const shown = computed(() => (onlyRefs.value && props.refs?.length
  ? grouped.value.filter((g) => props.refs!.includes(g.no)) : grouped.value))
const countOf = (no: number) => marks.value.filter((m) => m.no === no).length
const hint = computed(() => {
  if (tool.value === 'erase') return '点击已标记的文字即可擦除'
  if (tool.value) return '在资料上拖选文字即可标记'
  return '先选一支笔，再拖选文字'
})

function jump(no: number) {
  if (onlyRefs.value && props.refs?.length && !props.refs.includes(no)) onlyRefs.value = false
  setTimeout(() => document.getElementById(`mat-${uid}-${no}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

function onSelect() {
  if (!props.editable || !tool.value || tool.value === 'erase') return
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || !sel.rangeCount) return
  const range = sel.getRangeAt(0)
  const added: Mark[] = []
  // 选区可能跨好几段：逐段算出在该段内的起止位置。只认本面板里的段落
  scroller.value?.querySelectorAll<HTMLElement>('.para').forEach((el) => {
    const off = offsetsIn(el, range)
    if (off) added.push({ no: Number(el.dataset.no), paragraph: Number(el.dataset.para), start: off[0], end: off[1], style: tool.value as MarkStyle })
  })
  sel.removeAllRanges()
  if (!added.length) return
  marks.value = [...marks.value, ...added]
  scheduleSave()
}

function erase(s: Seg) {
  if (tool.value !== 'erase' || !s.ids.length) return
  const drop = new Set(s.ids)
  marks.value = marks.value.filter((_, i) => !drop.has(i))
  scheduleSave()
}
function undo() { marks.value = marks.value.slice(0, -1); scheduleSave() }
function clearAll() {
  if (!confirm('清空这份答卷上的全部资料标记？')) return
  marks.value = []
  scheduleSave()
}

function scheduleSave() {
  if (!props.sheetId) return
  clearTimeout(timer)
  timer = window.setTimeout(save, 600)
}
async function save() {
  clearTimeout(timer)
  timer = undefined
  if (!props.sheetId) return
  saveState.value = 'saving'
  try {
    await api.saveMarks(props.sheetId, marks.value)
    saveState.value = 'saved'
  } catch {
    saveState.value = 'error'
    timer = window.setTimeout(save, 5000)
  }
}
onBeforeUnmount(() => { if (timer) save() })

async function exportPdf() {
  if (timer) await save()  // 先把没保存的标记存上，导出才带得上
  const q = props.sheetId ? `?sheet=${props.sheetId}&auto=1` : '?auto=1'
  window.open(router.resolve(`/print/${props.paperId}${q}`).href, '_blank')
}
</script>

<style scoped>
.mat-scroll { max-height: 70vh; overflow-y: auto; padding-right: 4px; }
.mat-scroll.marking { cursor: text; }
.mat-scroll.marking ::selection { background: var(--pen-yellow); }
.mat-scroll.erasing span[class*="mk-"] { cursor: pointer; outline: 1px dashed var(--text-2); }
.toolbar { margin-bottom: 8px; gap: 4px; }
@media (max-width: 760px) { .mat-scroll { max-height: 50vh; } }
</style>
