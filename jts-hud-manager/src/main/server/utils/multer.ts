import { app as electronApp } from 'electron'
import path from 'path'
import fs from 'fs'
import multer from 'multer'

// Store uploads in userData directory
const uploadsPath = path.join(electronApp.getPath('userData'), 'uploads')

// Ensure the directory exists
if (!fs.existsSync(uploadsPath)) {
  fs.mkdirSync(uploadsPath, { recursive: true })
}

// Setup Multer storage
const storage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    cb(null, uploadsPath)
  },
  filename: (_req, file, cb) => {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1e9)
    cb(null, uniqueSuffix + path.extname(file.originalname))
  }
})

/**
 * Delete a file that was stored via the global uploads multer.
 * Accepts the stored path value e.g. "/api/uploads/player.png" or just a filename
 */
export const deleteUploadedFile = (urlOrFilename: string | null | undefined): void => {
  if (!urlOrFilename) return
  // Extract filename from /api/uploads/<filename>
  const filename = path.basename(urlOrFilename)
  const filePath = path.join(uploadsPath, filename)
  // Only delete if it lives inside uploadsPath
  if (!filePath.startsWith(uploadsPath)) return
  try {
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath)
  } catch {
    /* Silent ignore */
  }
}

// Export the middleware and the path for static serving
export const upload = multer({ storage })
export { uploadsPath }
