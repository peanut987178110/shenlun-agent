import axios from 'axios'
import { ref } from 'vue'

export const currentUser = ref<any>(null)

const TOKEN_KEY = 'shenlun_token'

export const auth = {
  get token(): string {
    try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
  },
  set(token: string) {
    try { localStorage.setItem(TOKEN_KEY, token) } catch { /* 隐私模式下不可写，本次会话内仍可用 */ }
  },
  clear() {
    try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
    currentUser.value = null
  },
}

const http = axios.create({ baseURL: '/api', timeout: 180000 })

http.interceptors.request.use((cfg) => {
  if (auth.token) cfg.headers.Authorization = `Bearer ${auth.token}`
  return cfg
})

http.interceptors.response.use(
  (r) => r,
  (e) => {
    e.friendly = friendlyError(e)
    if (e?.response?.status === 401 && !location.hash.startsWith('#/login')) {
      auth.clear()
      location.hash = '#/login'
    }
    return Promise.reject(e)
  },
)

/** 把后端错误转成一句人能看懂的话。FastAPI 的 422 detail 是数组，要逐项取 msg。 */
export function friendlyError(e: any): string {
  const res = e?.response
  if (!res) return e?.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : '网络请求失败，请确认后端已启动'
  const d = res.data?.detail
  if (typeof d === 'string' && d) return d
  if (Array.isArray(d) && d.length) {
    return '输入有误：' + d.slice(0, 3).map((x: any) => x?.msg || '校验失败').join('；')
  }
  if (res.status === 403) return '无权执行该操作'
  if (res.status === 404) return '内容不存在'
  return `请求失败（HTTP ${res.status}）`
}

const get = (url: string, params?: any) => http.get(url, { params }).then((r) => r.data)
const post = (url: string, body?: any) => http.post(url, body).then((r) => r.data)
const put = (url: string, body?: any) => http.put(url, body).then((r) => r.data)

export const api = {
  // 账号
  login: (username: string, password: string) => post('/auth/login', { username, password }),
  register: (username: string, password: string, display_name: string) =>
    post('/auth/register', { username, password, display_name }),
  me: () => get('/auth/me'),
  setGoal: (g: any) => put('/auth/me/goal', g),
  setPrivacy: (p: any) => put('/auth/me/privacy', p),
  changePassword: (old_password: string, new_password: string) =>
    put('/auth/me/password', { old_password, new_password }),
  createTeacher: (p: any) => post('/auth/teachers', p),

  // 题库
  papers: (params?: { year?: number; code?: string; origin?: string }) => get('/bank/papers', params),
  paper: (id: number) => get(`/bank/papers/${id}`),
  importPreview: (year: number, code: string, text: string) => post('/bank/import/preview', { year, code, text }),
  importSave: (paper: any, source_url: string, replace: boolean) => post('/bank/import', { paper, source_url, replace }),

  // 答卷（整卷或部分题目）
  mySheets: () => get('/sheets'),
  createSheet: (paper_id: number | null, question_ids: number[] = []) => post('/sheets', { paper_id, question_ids }),
  sheet: (id: number) => get(`/sheets/${id}`),
  uploadPages: (id: number, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return http.post(`/sheets/${id}/pages`, form).then((r) => r.data)
  },
  pageImageUrl: async (id: number, page: number) => {
    // 原图走鉴权接口，<img> 带不了令牌，所以取成 blob 再生成本地地址
    const r = await http.get(`/sheets/${id}/pages/${page}/image`, { responseType: 'blob' })
    return URL.createObjectURL(r.data)
  },
  deleteImages: (id: number) => http.delete(`/sheets/${id}/images`).then((r) => r.data),
  saveMarks: (id: number, marks: any[]) => put(`/sheets/${id}/marks`, { marks }),
  recognize: (id: number, force = false) => post(`/sheets/${id}/recognize`, { force }),
  setSheetPaper: (id: number, paper_id: number, question_ids: number[] = []) =>
    post(`/sheets/${id}/paper`, { paper_id, question_ids }),
  submitSheet: (id: number, body: { lines?: any[]; answers?: Record<number, string> }) =>
    post(`/sheets/${id}/submit`, body),

  // 单题作答
  submission: (id: number) => get(`/submissions/${id}`),
  revise: (id: number, text: string, kind = 'self_revised') => post(`/submissions/${id}/revise`, { text, kind }),

  // 助手与出题
  chat: (message: string, history: { role: string; content: string }[]) =>
    post('/assistant/chat', { message, history }),
  generate: (code: string, theme: string) => post('/generate', { code, theme }),
  myGenerated: () => get('/generate'),

  // 批改结果
  review: (id: number) => get(`/reviews/${id}`),
  unlockHint: (id: number, level: number) => post(`/reviews/${id}/hints/${level}`),
  compare: (id: number, other: number) => get(`/reviews/${id}/compare/${other}`),
  appeal: (id: number, point_id: number, reason: string) => post(`/reviews/${id}/appeals`, { point_id, reason }),

  // 画像
  dashboard: () => get('/profile/dashboard'),
  abilities: () => get('/profile/abilities'),
  errors: () => get('/profile/errors'),
  prescriptions: () => get('/profile/prescriptions'),
  startRetest: (id: number) => post(`/profile/prescriptions/${id}/retest`),

  // 教师
  queue: (status = 'queued') => get('/teacher/queue', { status }),
  teacherReview: (id: number) => get(`/teacher/reviews/${id}`),
  submitTeacherReview: (id: number, body: any) => post(`/teacher/reviews/${id}`, body),

  // 系统
  status: () => get('/system/status'),
  ping: () => post('/system/ping'),
}

export const ORIGIN_CLASS: Record<string, string> = { real: 'tag-ok', generated: 'tag-brand', sample: 'tag-warn' }

/** 轮询单题作答直到批改结束（修改复评用）。 */
export async function waitGraded(id: number, onTick?: (s: any) => void): Promise<any> {
  for (let i = 0; i < 240; i++) {
    const s = await api.submission(id)
    onTick?.(s)
    if (s.status === 'graded' || s.status === 'failed') return s
    await new Promise((r) => setTimeout(r, 1500))
  }
  throw new Error('批改超时，请稍后在「我的作答」里查看')
}

export const QTYPES: Record<string, string> = {
  summary: '归纳概括', analysis: '综合分析', countermeasure: '提出对策', official: '应用文', essay: '大作文',
}

export const MATCH_LABEL: Record<string, string> = {
  exact: '精确匹配', similar: '相似匹配', generic: '通用规则',
}
