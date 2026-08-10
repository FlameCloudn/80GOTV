import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const assetsDir = path.join(projectRoot, 'resources', 'default-hud', 'assets')

const sourceCssPath = path.join(assetsDir, 'index-de4c93c0.css')
const sourceJsPath = path.join(assetsDir, 'index-a37809f8.js')
const fallbackCssPath = path.join(assetsDir, 'obs-color-fallback.css')
const outputCssPath = path.join(assetsDir, 'index-obs-compatible.css')
const outputJsPath = path.join(assetsDir, 'index-obs-compatible.js')

const decodeSignedAsset = (filePath) => {
  const token = fs.readFileSync(filePath, 'utf8').trim()
  const parts = token.split('.')
  if (parts.length !== 3) throw new Error(`${path.basename(filePath)} is not a signed asset`)

  const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
  return Buffer.from(payload, 'base64').toString('utf8')
}

const clamp = (value) => Math.min(1, Math.max(0, value))

const linearToSrgb = (value) => {
  const converted = value <= 0.0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055
  return Math.round(clamp(converted) * 255)
}

const absoluteOklchToRgba = (body) => {
  const match = body
    .trim()
    .match(/^([\d.]+)%?\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+)%?)?$/)
  if (!match) return null

  const lightness = Number(match[1]) / (body.trim().startsWith(match[1] + '%') ? 100 : 1)
  const chroma = Number(match[2])
  const hue = (Number(match[3]) * Math.PI) / 180
  const alphaRaw = match[4] === undefined ? 1 : Number(match[4])
  const alpha = body.includes(`/${match[4]}%`) ? alphaRaw / 100 : alphaRaw

  const a = chroma * Math.cos(hue)
  const b = chroma * Math.sin(hue)
  const lRoot = lightness + 0.3963377774 * a + 0.2158037573 * b
  const mRoot = lightness - 0.1055613458 * a - 0.0638541728 * b
  const sRoot = lightness - 0.0894841775 * a - 1.291485548 * b
  const l = lRoot ** 3
  const m = mRoot ** 3
  const s = sRoot ** 3

  const red = linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)
  const green = linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)
  const blue = linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)

  return alpha < 1
    ? `rgba(${red}, ${green}, ${blue}, ${Number(alpha.toFixed(3))})`
    : `rgb(${red}, ${green}, ${blue})`
}

const replaceOklch = (source) => {
  let result = ''
  let cursor = 0

  while (true) {
    const start = source.indexOf('oklch(', cursor)
    if (start < 0) {
      result += source.slice(cursor)
      break
    }

    result += source.slice(cursor, start)
    let depth = 1
    let end = start + 'oklch('.length
    while (end < source.length && depth > 0) {
      if (source[end] === '(') depth += 1
      if (source[end] === ')') depth -= 1
      end += 1
    }
    if (depth !== 0) throw new Error('Unclosed oklch() value')

    const body = source.slice(start + 'oklch('.length, end - 1)
    let replacement
    if (body.includes('var(--color-ct)')) replacement = 'var(--color-ct, #5d79ae)'
    else if (body.includes('var(--color-t)')) replacement = 'var(--color-t, #d4a452)'
    else replacement = absoluteOklchToRgba(body)

    if (!replacement) throw new Error(`Unsupported oklch() value: ${body}`)
    result += replacement
    cursor = end
  }

  return result
}

const sourceCss = decodeSignedAsset(sourceCssPath)
const sourceJs = decodeSignedAsset(sourceJsPath)
const fallbackCss = fs.readFileSync(fallbackCssPath, 'utf8').trim()

const stripGoogleFontImports = (text) =>
  text.replace(/@import["']?https?:\/\/fonts\.(?:googleapis|gstatic)\.com[^;]+;/g, '')

const compatibleCss = `${replaceOklch(stripGoogleFontImports(sourceCss))}\n\n/* OBS compatibility overrides */\n${fallbackCss}\n`
const compatibleJs = replaceOklch(stripGoogleFontImports(sourceJs))

if (compatibleCss.includes('oklch(') || compatibleJs.includes('oklch(')) {
  throw new Error('OBS-compatible assets still contain oklch() colors')
}

fs.writeFileSync(outputCssPath, compatibleCss)
fs.writeFileSync(outputJsPath, compatibleJs)

console.log(`Generated ${path.relative(projectRoot, outputCssPath)}`)
console.log(`Generated ${path.relative(projectRoot, outputJsPath)}`)
