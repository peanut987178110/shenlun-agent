<template>
  <div>
    <div class="page-head"><h1>我的作答</h1><span class="spacer" />
      <button class="btn btn-primary" @click="router.push('/grade')">开始批改</button></div>
    <div class="card">
      <div v-if="!list.length" class="empty">还没有作答记录</div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead><tr><th>时间</th><th>试卷</th><th>题数</th><th>得分</th><th>状态</th><th /></tr></thead>
          <tbody>
            <tr v-for="s in list" :key="s.id">
              <td class="faint num">{{ s.created_at }}</td>
              <td>{{ s.paper }}</td>
              <td class="num">{{ s.questions || '—' }}</td>
              <td class="num">{{ s.score !== null ? `${s.score} / ${s.full_score}` : '—' }}</td>
              <td><span class="tag" :class="s.status === 'graded' ? 'tag-ok' : ''">{{ STATUS[s.status] || s.status }}</span></td>
              <td><button class="btn btn-sm" @click="router.push(`/grade/${s.id}`)">
                {{ s.status === 'graded' ? '看结果' : '继续' }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const list = ref<any[]>([])
const STATUS: Record<string, string> = { draft: '待作答', recognized: '待核对', grading: '批改中', graded: '已批改' }
onMounted(async () => { list.value = await api.mySheets() })
</script>
