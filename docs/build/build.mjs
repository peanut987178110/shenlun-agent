// 把 docs/PRD.md、docs/需求分析.md、docs/流程图.md 导出为 PDF，并把流程图导出为 docs/diagrams/*.svg。
//
// 用法（在 docs/build 目录）：npm install && npm run build
// 用本机已安装的 Chrome 渲染（playwright-core 不自带浏览器），Mermaid 从本地 node_modules 加载，不走网络。
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { marked } from 'marked'
import { chromium } from 'playwright-core'

const HERE = dirname(fileURLToPath(import.meta.url))
const DOCS = resolve(HERE, '..')
const DIAGRAMS = join(DOCS, 'diagrams')
const MERMAID = pathToFileURL(join(HERE, 'node_modules/mermaid/dist/mermaid.min.js')).href
const DOCS_TO_PDF = ['PRD.md', '需求分析.md', '流程图.md']

const CHROME = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
].find((p) => p && existsSync(p))
if (!CHROME) throw new Error('找不到 Chrome，请设置 CHROME_PATH')

const CSS = `
@page { size: A4; margin: 16mm 15mm 18mm; }
body { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif; font-size: 10.5pt;
  line-height: 1.7; color: #1b2027; }
h1 { font-size: 20pt; border-bottom: 2px solid #2257c7; padding-bottom: 6px; margin: 0 0 14px; }
h2 { font-size: 14pt; margin: 22px 0 8px; color: #173f94; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 16px 0 6px; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.5pt; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #cfd6df; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #eef3fb; }
code { background: #f2f4f7; padding: 1px 4px; border-radius: 3px; font-size: 9pt; }
pre { background: #f6f8fa; border: 1px solid #e3e7ec; border-radius: 6px; padding: 8px 10px; white-space: pre-wrap;
  font-size: 9pt; break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { margin: 8px 0; padding: 4px 12px; border-left: 3px solid #9fb6e6; color: #444; }
hr { border: 0; border-top: 1px solid #dde1e7; margin: 18px 0; }
a { color: #2257c7; text-decoration: none; }
img, .mermaid { display: block; max-width: 100%; margin: 10px auto; break-inside: avoid; }
/* 每张图最多占一页：竖长的流程图按高度缩，不跨页 */
.mermaid svg, img[src$=".svg"] { max-width: 100% !important; max-height: 240mm; width: auto; height: auto; }
/* 流程图文档：每张图单独一页 */
.diagrams h2 { break-before: page; }
.diagrams h2:first-of-type { break-before: auto; }
.mermaid { text-align: center; }
`

// Mermaid 配置：不用 HTML 标签，SVG 在 GitHub 以 <img> 显示时文字才不会丢
// 节点、层间距收紧：竖长的流程图缩到一页时字才看得清
const MERMAID_INIT = { startOnLoad: false, theme: 'neutral', securityLevel: 'strict',
  flowchart: { htmlLabels: false, curve: 'basis', nodeSpacing: 28, rankSpacing: 30, padding: 6, wrappingWidth: 220 },
  fontFamily: '"Microsoft YaHei", sans-serif', fontSize: 15 }

function toHtml(md) {
  const renderer = new marked.Renderer()
  const code = renderer.code.bind(renderer)
  renderer.code = (tok) => (tok.lang === 'mermaid'
    ? `<pre class="mermaid">${tok.text.replace(/</g, '&lt;')}</pre>` : code(tok))
  // 文档间链接 xxx.md → xxx.pdf，PDF 里点得通
  const link = renderer.link.bind(renderer)
  renderer.link = (tok) => link({ ...tok, href: tok.href.replace(/^([^:#]+)\.md(#|$)/, '$1.pdf$2') })
  return marked.parse(md, { renderer, gfm: true })
}

function page(title, body) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${title}</title>
<style>${CSS}</style><script src="${MERMAID}"></script></head><body>${body}
<script>mermaid.initialize(${JSON.stringify(MERMAID_INIT)});
window.__done = mermaid.run({ querySelector: '.mermaid' }).then(() => true, (e) => String(e));</script></body></html>`
}

const browser = await chromium.launch({ executablePath: CHROME })
const ctx = await browser.newContext()

async function render(file) {
  const md = readFileSync(join(DOCS, file), 'utf8')
  const title = (md.match(/^#\s+(.+)$/m) || [, file])[1]
  const htmlPath = join(HERE, '.tmp-' + file.replace(/\.md$/, '.html'))
  // 图片以 docs 目录为基准解析
  const body = `<base href="${pathToFileURL(DOCS + '/').href}">` + toHtml(md)
  writeFileSync(htmlPath, page(title, file === '流程图.md' ? `<div class="diagrams">${body}</div>` : body))
  const p = await ctx.newPage()
  await p.goto(pathToFileURL(htmlPath).href)
  const ok = await p.evaluate(() => window.__done)
  if (ok !== true) throw new Error(`${file} Mermaid 渲染失败：${ok}`)
  return { p, title }
}

// 1) 流程图 SVG：从 流程图.md 里按「## 图 N 标题」切出每张图
// 注意：Mermaid 布局带随机种子，同一份源码两次导出的路径坐标会略有不同（图形一样）。
// 所以不必每次重建都提交 SVG，改动流程图本身时再重新生成即可。
mkdirSync(DIAGRAMS, { recursive: true })
{
  const { p } = await render('流程图.md')
  const svgs = await p.evaluate(() => [...document.querySelectorAll('.mermaid')].map((el) => {
    let h = el.previousElementSibling
    while (h && h.tagName !== 'H2') h = h.previousElementSibling
    const svg = el.querySelector('svg').cloneNode(true)
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    // Mermaid 只给 viewBox 和 max-width 样式；作为 <img> 引用时没有宽高会显示成 0×0
    const [, , w, h2] = (svg.getAttribute('viewBox') || '0 0 800 600').split(/\s+/).map(Number)
    svg.setAttribute('width', String(Math.round(w)))
    svg.setAttribute('height', String(Math.round(h2)))
    svg.removeAttribute('style')
    // 必须按 XML 序列化：outerHTML 会写出 <br> 这类不闭合标签，独立打开 SVG 时直接报错
    return { title: h ? h.textContent.trim() : 'diagram', svg: new XMLSerializer().serializeToString(svg) }
  }))
  svgs.forEach(({ title, svg }, i) => {
    const m = title.match(/^图\s*(\d+)\s*(.+)$/)
    const name = m ? `${m[1].padStart(2, '0')}-${m[2].replace(/[（）()\s]/g, '')}` : `diagram-${i + 1}`
    // Mermaid 每次渲染给的元素 id 是随机的（mermaid-1699...）。换成稳定 id，
    // 否则每次重新生成，SVG 整行都变，提交里全是噪音。
    const randomId = svg.match(/id="(mermaid-[\w-]+)"/)?.[1]
    const stable = svg.split(randomId).join(`mermaid-${name}`)
    // 独立打开 SVG 时要白底，否则深色模式下看不清
    writeFileSync(join(DIAGRAMS, `${name}.svg`),
      stable.replace(/<svg([^>]*)>/, '<svg$1><rect width="100%" height="100%" fill="#ffffff"/>'))
    console.log('svg ', `diagrams/${name}.svg`)
  })
  await p.close()
}

// 2) 各文档 PDF
for (const f of DOCS_TO_PDF) {
  const { p, title } = await render(f)
  const out = join(DOCS, f.replace(/\.md$/, '.pdf'))
  await p.pdf({
    path: out, format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: `<div style="font-size:8px;color:#8a939d;width:100%;padding:0 15mm;font-family:sans-serif">${title}</div>`,
    footerTemplate: '<div style="font-size:8px;color:#8a939d;width:100%;text-align:center;font-family:sans-serif"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    margin: { top: '16mm', bottom: '18mm', left: '15mm', right: '15mm' },
  })
  console.log('pdf ', f.replace(/\.md$/, '.pdf'))
  await p.close()
}
await browser.close()
