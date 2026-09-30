<template>
  <form class="grid grid-3" style="gap: 0 16px" @submit.prevent="save">
    <div class="field">
      <label for="g-year">考试年份</label>
      <input id="g-year" v-model.number="g.exam_year" type="number" class="input" min="2024" max="2100" />
    </div>
    <div class="field">
      <label for="g-cat">考试类别</label>
      <select id="g-cat" v-model="g.exam_category" class="input" required>
        <option value="">请选择</option>
        <option v-for="c in CATS" :key="c">{{ c }}</option>
      </select>
    </div>
    <div class="field">
      <label for="g-region">目标地区</label>
      <input id="g-region" v-model.trim="g.target_region" class="input" placeholder="如：杭州" maxlength="32" />
    </div>
    <div class="field">
      <label for="g-score">目标分数（申论总分）</label>
      <input id="g-score" v-model.number="g.target_score" type="number" class="input" min="0" max="200" required />
    </div>
    <div class="field">
      <label for="g-level">当前基础</label>
      <select id="g-level" v-model="g.current_level" class="input">
        <option value="">请选择</option>
        <option v-for="l in LEVELS" :key="l">{{ l }}</option>
      </select>
    </div>
    <div class="field">
      <label for="g-date">预计考试时间</label>
      <input id="g-date" v-model="g.exam_date" type="month" class="input" />
    </div>
    <div class="row">
      <button class="btn btn-primary" :disabled="busy">保存目标</button>
      <span v-if="err" class="small" style="color: var(--danger)">{{ err }}</span>
    </div>
  </form>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api, currentUser } from '../api'
import { toast } from '../toast'

const emit = defineEmits<{ saved: [] }>()
const CATS = ['省级机关', '市县机关', '乡镇机关', '行政执法类']
const LEVELS = ['刚开始准备', '做过一些真题', '冲刺阶段']
const u = currentUser.value || {}
const g = reactive({
  exam_year: u.exam_year || new Date().getFullYear() + 1, exam_category: u.exam_category || '',
  target_region: u.target_region || '', target_score: u.target_score ?? null,
  current_level: u.current_level || '', exam_date: u.exam_date || '',
})
const busy = ref(false)
const err = ref('')

async function save() {
  busy.value = true
  err.value = ''
  try {
    currentUser.value = { ...currentUser.value, ...(await api.setGoal(g)) }
    toast('目标已保存')
    emit('saved')
  } catch (e: any) {
    err.value = e.friendly
  } finally {
    busy.value = false
  }
}
</script>
