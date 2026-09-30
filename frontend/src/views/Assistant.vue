<template>
  <div class="chat">
    <div class="page-head">
      <h1>申论助手</h1>
      <span class="faint">查真题与材料、问题型方法、分析自己的薄弱点</span>
      <span class="spacer" />
      <button v-if="msgs.length" class="btn btn-sm" @click="clear">清空对话</button>
    </div>
    <div ref="box" class="chat-box card" aria-live="polite">
      <div v-if="!msgs.length" class="stack">
        <p class="muted small">可以这样问：</p>
        <button v-for="s in SUGGEST" :key="s" class="btn btn-sm" style="display: block" @click="send(s)">{{ s }}</button>
      </div>
      <div v-for="(m, i) in msgs" :key="i" class="msg" :class="m.role">
        <div class="bubble pre">{{ m.content }}</div>
        <details v-if="m.steps?.length" class="faint small" style="margin-top: 4px">
          <summary style="cursor: pointer">查了 {{ m.steps.length }} 次资料</summary>
          <div v-for="(s, j) in m.steps" :key="j">· {{ TOOL_LABEL[s.tool] || s.tool }} {{ fmtArgs(s.args) }}</div>
        </details>
      </div>
      <div v-if="busy" class="msg assistant"><div class="bubble muted">正在查资料并思考…</div></div>
    </div>
    <form class="row" style="flex-wrap: nowrap" @submit.prevent="send(input)">
      <textarea v-model="input" class="input" rows="2" aria-label="输入问题" placeholder="输入问题，Enter 发送，Shift+Enter 换行"
                @keydown.enter.exact.prevent="send(input)" />
      <button class="btn btn-primary" :disabled="busy || !input.trim()">发送</button>
    </form>
    <p class="faint">助手只能查阅题库和你自己的学习记录，不能批改或改分。回答里的题目、材料都来自题库，题库没有的内容它会直说。</p>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { api } from '../api'

const SUGGEST = ['浙江省考申论 A、B、C 卷有什么区别？', '2025 年 B 卷考的是什么主题，有哪几道题？',
  '题库里哪些材料讲到了「千万工程」？', '根据我最近的批改，我最该练什么？', '提出对策题怎么写才不空泛？']
const TOOL_LABEL: Record<string, string> = {
  search_papers: '查试卷', get_paper: '看试卷', search_materials: '搜材料', exam_guide: '查考试常识',
  my_learning: '看我的学习记录', get_review: '看批改详情',
}
const KEY = 'shenlun-chat'
const msgs = ref<{ role: string; content: string; steps?: any[] }[]>(load())
const input = ref('')
const busy = ref(false)
const box = ref<HTMLElement>()

function load() {
  try { return JSON.parse(sessionStorage.getItem(KEY) || '[]') } catch { return [] }
}
function save() {
  try { sessionStorage.setItem(KEY, JSON.stringify(msgs.value.slice(-40))) } catch { /* ignore */ }
}
function clear() { msgs.value = []; save() }
const fmtArgs = (a: any) => Object.entries(a || {}).filter(([, v]) => v !== '' && v !== 0).map(([k, v]) => `${k}=${v}`).join(' ')

async function send(text: string) {
  text = text.trim()
  if (!text || busy.value) return
  const history = msgs.value.map(({ role, content }) => ({ role, content }))
  msgs.value.push({ role: 'user', content: text })
  input.value = ''
  busy.value = true
  await scroll()
  try {
    const r = await api.chat(text, history)
    msgs.value.push({ role: 'assistant', content: r.reply, steps: r.steps })
  } catch (e: any) {
    msgs.value.push({ role: 'assistant', content: `出错了：${e.friendly || e.message}` })
  } finally {
    busy.value = false
    save()
    await scroll()
  }
}
async function scroll() {
  await nextTick()
  box.value?.scrollTo({ top: box.value.scrollHeight, behavior: 'smooth' })
}
</script>

<style scoped>
.chat { display: flex; flex-direction: column; height: calc(100vh - 72px); }
.chat-box { flex: 1; overflow-y: auto; min-height: 200px; }
.msg { margin-bottom: 12px; display: flex; flex-direction: column; }
.msg.user { align-items: flex-end; }
.bubble { max-width: 80%; padding: 8px 12px; border-radius: 10px; background: var(--bg-2); line-height: 1.8; }
.msg.user .bubble { background: var(--brand-bg); }
@media (max-width: 760px) { .chat { height: auto; } .chat-box { max-height: 60vh; } .bubble { max-width: 95%; } }
</style>
