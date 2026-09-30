<template>
  <div>
    <div class="page-head">
      <h1>复核队列</h1>
      <span class="spacer" />
      <div class="row" role="tablist">
        <button class="btn btn-sm" :class="{ 'btn-primary': status === 'queued' }" @click="status = 'queued'">待复核</button>
        <button class="btn btn-sm" :class="{ 'btn-primary': status === 'reviewed' }" @click="status = 'reviewed'">已复核</button>
      </div>
    </div>
    <p class="muted small">队列只包含低置信度和被申诉的批改，按置信度从低到高排列。学员身份已脱敏。</p>
    <div class="card">
      <div v-if="!list.length" class="empty">队列为空</div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead><tr><th>学员</th><th>题目</th><th>原因</th><th>AI 评分</th><th>置信度</th><th>方式</th><th>时间</th><th /></tr></thead>
          <tbody>
            <tr v-for="x in list" :key="x.review_id">
              <td>{{ x.student }}</td>
              <td>{{ x.question }}</td>
              <td><span class="tag" :class="x.open_appeals ? 'tag-danger' : 'tag-warn'">{{ x.reason }}</span></td>
              <td class="num">{{ x.score }} / {{ x.full_score }}</td>
              <td class="num">{{ Math.round(x.confidence * 100) }}%</td>
              <td>{{ x.method === 'llm' ? '模型' : '规则' }}</td>
              <td class="faint">{{ x.created_at }}</td>
              <td><button class="btn btn-sm btn-primary" @click="router.push(`/teacher/${x.review_id}`)">
                {{ status === 'queued' ? '复核' : '查看' }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const status = ref('queued')
const list = ref<any[]>([])
watch(status, async (s) => { list.value = await api.queue(s) }, { immediate: true })
</script>
