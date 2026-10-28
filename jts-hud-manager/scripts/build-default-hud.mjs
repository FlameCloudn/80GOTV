import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const managerDir = path.resolve(scriptDir, '..')
const ignoredRootFiles = new Set(['hud.json', 'panel.json', 'keybinds.json', 'key', 'thumb.png', 'thumb.jpg'])

const assertBuiltIndex = (sourceDir) => {
  const indexPath = path.join(sourceDir, 'index.html')
  if (!fs.existsSync(indexPath)) throw new Error(`找不到 HUD 构建入口：${indexPath}`)

  const html = fs.readFileSync(indexPath, 'utf8')
  const assetPaths = [...html.matchAll(/(?:src|href)=["']([^"']+\.(?:js|css))["']/g)]
    .map((match) => match[1])
    .filter((asset) => asset.startsWith('./assets/'))
  if (!assetPaths.some((asset) => asset.endsWith('.js')) || !assetPaths.some((asset) => asset.endsWith('.css'))) {
    throw new Error('HUD 构建入口没有同时指向新的 JS 和 CSS 文件')
  }
  for (const asset of assetPaths) {
    if (!fs.existsSync(path.join(sourceDir, asset))) throw new Error(`HUD 构建缺少入口资源：${asset}`)
  }
}

export const syncBuiltHud = ({
  sourceDir = path.resolve(managerDir, '..', 'broadcast_hud', 'build'),
  targetDir = path.join(managerDir, 'resources', 'default-hud'),
  dryRun = false
} = {}) => {
  if (!fs.existsSync(sourceDir) || !fs.statSync(sourceDir).isDirectory()) {
    throw new Error(`找不到 HUD 构建目录：${sourceDir}`)
  }
  assertBuiltIndex(sourceDir)

  const copied = []
  const copyTree = (from, to, relative = '') => {
    for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
      const childRelative = path.join(relative, entry.name)
      if (!relative && ignoredRootFiles.has(entry.name)) continue
      const sourcePath = path.join(from, entry.name)
      const targetPath = path.join(to, entry.name)
      if (entry.isDirectory()) {
        if (!dryRun) fs.mkdirSync(targetPath, { recursive: true })
        copyTree(sourcePath, targetPath, childRelative)
        continue
      }
      if (!entry.isFile()) continue
      copied.push(childRelative)
      if (dryRun) continue
      fs.mkdirSync(path.dirname(targetPath), { recursive: true })
      fs.copyFileSync(sourcePath, targetPath)
    }
  }

  if (!dryRun) fs.mkdirSync(targetDir, { recursive: true })
  copyTree(sourceDir, targetDir)
  return copied
}

const calledDirectly = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url
if (calledDirectly) {
  try {
    const copied = syncBuiltHud()
    console.log(`已同步 HUD 构建文件：${copied.length} 项；旧资源和 HUD 配置均已保留。`)
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  }
}
