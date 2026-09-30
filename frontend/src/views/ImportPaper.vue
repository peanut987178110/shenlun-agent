<template>
  <div>
    <div class="page-head">
      <h1>导入真题</h1>
      <span class="spacer" />
      <button class="btn" @click="router.push('/bank')">返回题库</button>
    </div>
    <div class="alert alert-info">
      在粉笔等网站打开整套真题，全选复制「给定资料」和「作答要求」，粘贴到下面。系统按规则原样切分，
      不经过模型改写；保存前可以检查和修正每道题的题型、分值、字数和引用资料。
    </div>

    <div class="grid grid-2" style="align-items: start">
      <div class="card">
        <div class="row" style="margin-bottom: 12px">
          <select v-model.number="year" class="input" style="width: auto" aria-label="年度">
            <option v-for="y in years" :key="y" :value="y">{{ y }} 年度</option>
          </select>
          <select v-model="code" class="input" style="width: auto" aria-label="卷别">
            <option value="A">A 卷 · 综合类</option>
            <option value="B">B 卷 · 基层类</option>
            <option value="C">C 卷 · 行政执法类</option>
          </select>
          <span class="faint">「2026 年度」省考在 2025 年 12 月考</span>
        </div>
        <textarea v-model="text" class="input" rows="22" aria-label="整套试卷文本"
                  placeholder="资料1&#10;……&#10;资料2&#10;……&#10;作答要求&#10;一、根据资料1，概括……（20分）&#10;要求：……" />
        <div class="row" style="margin-top: 8px">
          <span class="faint num">{{ text.length }} 字</span>
          <span style="flex: 1" />
          <button class="btn btn-primary" :disabled="busy || text.length < 200" @click="preview">切分预览</button>
        </div>
      </div>

      <div v-if="d" class="card">
        <div class="card-title"><h2>预览：{{ d.name }}</h2></div>
        <div v-if="errors.length" class="alert alert-danger">
          <div v-for="e in errors" :key="e">· {{ e }}</div>
        </div>
        <div v-else class="alert alert-ok">格式校验通过</div>
        <div class="field">
          <label for="topic">本卷主题（一句话）</label>
          <input id="topic" v-model="d.topic" class="input" maxlength="120" @input="revalidate" />
        </div>
        <p class="small">给定资料 {{ matNos.length }} 则、{{ d.materials.length }} 段、共 {{ matChars }} 字：
          <span v-for="n in matNos" :key="n" class="tag" style="margin-right: 4px">资料{{ n }} {{ charsOf(n) }}字</span></p>

        <div v-for="q in d.questions" :key="q.no" class="ann" style="cursor: default">
          <div class="row" style="flex-wrap: wrap; gap: 6px">
            <b>第 {{ q.no }} 题</b>
            <select v-model="q.qtype" class="input" style="width: auto" :aria-label="`第${q.no}题题型`" @change="revalidate">
              <option v-for="(v, k) in QTYPES" :key="k" :value="k">{{ v }}</option>
            </select>
            <input v-model.number="q.full_score" type="number" class="input" style="width: 70px" :aria-label="`第${q.no}题分值`" @input="revalidate" /><span class="faint">分</span>
            <input v-model.number="q.word_min" type="number" class="input" style="width: 76px" :aria-label="`第${q.no}题字数下限`" />
            <span class="faint">—</span>
            <input v-model.number="q.word_max" type="number" class="input" style="width: 76px" :aria-label="`第${q.no}题字数上限`" /><span class="faint">字</span>
          </div>
          <div class="row small" style="margin-top: 6px">
            <span class="faint">引用资料（空 = 全部）：</span>
            <label v-for="n in matNos" :key="n" class="row" style="gap: 2px"><input v-model="q.material_refs" type="checkbox" :value="n" @change="revalidate" />{{ n }}</label>
          </div>
          <p class="small pre" style="margin: 6px 0 0">{{ q.stem }}</p>
        </div>

        <div class="field" style="margin-top: 12px">
          <label for="src">来源链接（可选，如粉笔题目页地址）</label>
          <input id="src" v-model.trim="sourceUrl" class="input" placeholder="https://..." />
        </div>
        <label class="row small"><input v-model="replace" type="checkbox" /> 题库里已有这一年这一卷时，替换它</label>
        <div v-if="saveErr" class="alert alert-danger" style="margin-top: 8px">{{ saveErr }}</div>
        <div class="row" style="margin-top: 8px">
          <button class="btn btn-primary" :disabled="busy || errors.length > 0" @click="save">保存到题库</button>
          <span class="faint">保存后写入 backend/app/data/papers/{{ year }}_{{ code }}.json，随项目一起分发</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, QTYPES } from '../api'
import { toast } from '../toast'

const router = useRouter()
const now = new Date().getFullYear()
const years = Array.from({ length: 8 }, (_, i) => now + 1 - i)
const year = ref(now)
const code = ref('C')
const text = ref('')
const d = ref<any>(null)
const errors = ref<string[]>([])
const sourceUrl = ref('')
const replace = ref(false)
const busy = ref(false)
const saveErr = ref('')

const matNos = computed(() => [...new Set((d.value?.materials || []).map((m: any) => m.no))] as number[])
const charsOf = (n: number) => d.value.materials.filter((m: any) => m.no === n).reduce((s: number, m: any) => s + m.text.length, 0)
const matChars = computed(() => (d.value?.materials || []).reduce((s: number, m: any) => s + m.text.length, 0))

async function preview() {
  busy.value = true
  saveErr.value = ''
  try {
    const r = await api.importPreview(year.value, code.value, text.value)
    d.value = r.paper
    errors.value = r.errors
  } catch (e: any) { saveErr.value = e.friendly } finally { busy.value = false }
}

// 前端改了分值、题型后即时重算最常见的问题，最终以后端校验为准
function revalidate() {
  const errs: string[] = []
  const total = d.value.questions.reduce((s: number, q: any) => s + (Number(q.full_score) || 0), 0)
  if (Math.abs(total - 100) > 0.01) errs.push(`各题分值之和 ${total} ≠ 100`)
  if (!d.value.materials.length) errs.push('没有切分出给定资料：检查资料标题是否单独成行（如「资料1」）')
  if (!d.value.questions.length) errs.push('没有切分出题目：检查是否有「作答要求」一行')
  if (!d.value.topic?.trim()) errs.push('请填写本卷主题')
  errors.value = errs
}

async function save() {
  busy.value = true
  saveErr.value = ''
  try {
    const p = await api.importSave(d.value, sourceUrl.value, replace.value)
    toast(`已保存：${p.name}`)
    router.push(`/paper/${p.id}`)
  } catch (e: any) { saveErr.value = e.friendly } finally { busy.value = false }
}
</script>
