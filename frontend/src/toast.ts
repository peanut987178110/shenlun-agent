import { ref } from 'vue'

export const toastMsg = ref('')
let timer: number | undefined

export function toast(msg: string, ms = 2600) {
  toastMsg.value = msg
  clearTimeout(timer)
  timer = window.setTimeout(() => (toastMsg.value = ''), ms)
}
