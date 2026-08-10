import { app } from 'electron'
import fs from 'fs'
import os from 'os'
import path from 'path'
import util from 'util'

let installed = false

export const getLogDirectory = (): string => path.join(app.getPath('userData'), 'logs')

const getLogFilePath = (): string => {
  const day = new Date().toISOString().slice(0, 10)
  return path.join(getLogDirectory(), `director-${day}.log`)
}

const redact = (value: string): string =>
  value
    .replace(/(authorization\s*[:=]\s*)([^\s,}]+)/gi, '$1[REDACTED]')
    .replace(/((?:gsi|api)[_-]?(?:token|key)|password|secret)(["']?\s*[:=]\s*["']?)([^\s,"'}]+)/gi, '$1$2[REDACTED]')
    .replace(/(bearer\s+)[a-z0-9._~+/=-]+/gi, '$1[REDACTED]')

const formatArg = (value: unknown): string => {
  if (value instanceof Error) return `${value.name}: ${value.message}\n${value.stack || ''}`.trim()
  if (typeof value === 'string') return redact(value)
  return redact(util.inspect(value, { depth: 6, breakLength: 160, maxArrayLength: 80 }))
}

const append = (level: string, args: unknown[]): void => {
  try {
    const directory = getLogDirectory()
    fs.mkdirSync(directory, { recursive: true })
    const timestamp = new Date().toISOString()
    fs.appendFileSync(getLogFilePath(), `${timestamp} [${level}] ${args.map(formatArg).join(' ')}\n`, 'utf8')
  } catch {
    // Logging must never interrupt a broadcast.
  }
}

export const installFileLogging = (): void => {
  if (installed) return
  installed = true

  const originalLog = console.log.bind(console)
  const originalWarn = console.warn.bind(console)
  const originalError = console.error.bind(console)

  console.log = (...args: unknown[]) => {
    append('INFO', args)
    originalLog(...args)
  }
  console.warn = (...args: unknown[]) => {
    append('WARN', args)
    originalWarn(...args)
  }
  console.error = (...args: unknown[]) => {
    append('ERROR', args)
    originalError(...args)
  }

  process.on('uncaughtExceptionMonitor', (error) => append('FATAL', [error]))
  process.on('unhandledRejection', (reason) => append('UNHANDLED', [reason]))

  console.log(
    `[App] Logging started; version=${app.getVersion()} packaged=${app.isPackaged} platform=${process.platform} arch=${process.arch} os=${os.release()}`
  )
}
