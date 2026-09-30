/** 资料标记：按「资料编号 + 段号 + 字符偏移」定位，答题页和打印页共用同一套切分逻辑。 */

export type MarkStyle = 'yellow' | 'green' | 'pink' | 'underline'
export interface Mark { no: number; paragraph: number; start: number; end: number; style: MarkStyle }
export interface Seg { text: string; styles: MarkStyle[]; ids: number[] }

export const MARK_TOOLS: { style: MarkStyle; label: string }[] = [
  { style: 'yellow', label: '黄色' }, { style: 'green', label: '绿色' },
  { style: 'pink', label: '粉色' }, { style: 'underline', label: '下划线' },
]

/** 把一段文字按标记切成若干片段。标记可以重叠（如黄色高亮 + 下划线），每片带上覆盖它的所有标记。 */
export function segments(text: string, marks: Mark[], no: number, paragraph: number): Seg[] {
  const mine = marks.map((m, i) => ({ ...m, i }))
    .filter((m) => m.no === no && m.paragraph === paragraph && m.end > m.start)
  if (!mine.length) return [{ text, styles: [], ids: [] }]
  const cuts = new Set([0, text.length])
  for (const m of mine) {
    cuts.add(Math.max(0, Math.min(text.length, m.start)))
    cuts.add(Math.max(0, Math.min(text.length, m.end)))
  }
  const pts = [...cuts].sort((a, b) => a - b)
  const out: Seg[] = []
  for (let k = 0; k < pts.length - 1; k++) {
    const a = pts[k], b = pts[k + 1]
    if (a === b) continue
    const on = mine.filter((m) => m.start <= a && m.end >= b)
    out.push({ text: text.slice(a, b), styles: [...new Set(on.map((m) => m.style))], ids: on.map((m) => m.i) })
  }
  return out
}

export function segClass(s: Seg): string[] {
  const hl = s.styles.filter((x) => x !== 'underline').at(-1)
  return [hl ? `mk-hl-${hl}` : '', s.styles.includes('underline') ? 'mk-ul' : ''].filter(Boolean)
}

/** 选区在某个段落元素里的起止偏移。段落内部可能已被标记切成多个 span，所以用 Range 量文字长度。 */
export function offsetsIn(el: HTMLElement, range: Range): [number, number] | null {
  if (!range.intersectsNode(el)) return null
  const pre = document.createRange()
  pre.selectNodeContents(el)
  const total = pre.toString().length
  let start = 0
  let end = total
  if (el.contains(range.startContainer)) {
    pre.setEnd(range.startContainer, range.startOffset)
    start = pre.toString().length
  }
  if (el.contains(range.endContainer)) {
    pre.selectNodeContents(el)
    pre.setEnd(range.endContainer, range.endOffset)
    end = pre.toString().length
  }
  return end > start ? [start, end] : null
}
