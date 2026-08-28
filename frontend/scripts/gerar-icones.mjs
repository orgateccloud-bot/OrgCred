/**
 * Gera os PNGs de public/icons/ a partir de public/favicon.svg.
 *
 * Renderiza com o Chromium do Playwright (que a suíte E2E já instala) em vez
 * de acrescentar sharp/resvg às dependências: é uma ferramenta de build
 * rodada à mão quando a marca mudar, não um passo do bundle. Os PNGs gerados
 * são commitados — o deploy não roda isto.
 *
 * Uso:  node scripts/gerar-icones.mjs
 *
 * Três variantes:
 * - icone-{192,512}.png     — o SVG como é (cantos arredondados transparentes)
 * - icone-maskable-512.png  — sangria total (rx=0): o launcher do Android
 *   aplica a própria máscara, e cantos transparentes virariam buracos. O anel
 *   ocupa ~53% da largura, dentro da zona segura de 80% da spec de maskable.
 * - apple-touch-icon.png    — 180px, sangria total: o iOS arredonda sozinho.
 */
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const raiz = join(dirname(fileURLToPath(import.meta.url)), '..')
const svg = await readFile(join(raiz, 'public', 'favicon.svg'), 'utf8')
const svgSangriaTotal = svg.replace('rx="14"', 'rx="0"')

const ALVOS = [
  { arquivo: 'icone-192.png', tamanho: 192, svg, transparente: true },
  { arquivo: 'icone-512.png', tamanho: 512, svg, transparente: true },
  { arquivo: 'icone-maskable-512.png', tamanho: 512, svg: svgSangriaTotal, transparente: false },
  { arquivo: 'apple-touch-icon.png', tamanho: 180, svg: svgSangriaTotal, transparente: false },
]

const destino = join(raiz, 'public', 'icons')
await mkdir(destino, { recursive: true })

const navegador = await chromium.launch()
try {
  for (const alvo of ALVOS) {
    const pagina = await navegador.newPage({
      viewport: { width: alvo.tamanho, height: alvo.tamanho },
      deviceScaleFactor: 1,
    })
    await pagina.setContent(
      `<!doctype html><style>html,body{margin:0}svg{display:block;width:${alvo.tamanho}px;height:${alvo.tamanho}px}</style>${alvo.svg}`,
    )
    const png = await pagina.screenshot({ omitBackground: alvo.transparente })
    await writeFile(join(destino, alvo.arquivo), png)
    await pagina.close()
    console.log(`public/icons/${alvo.arquivo} (${alvo.tamanho}px)`)
  }
} finally {
  await navegador.close()
}
