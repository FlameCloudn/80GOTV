import { Request, Response, NextFunction } from 'express'
import fs from 'fs'
import path from 'path'
import { SignatureVerifier } from '../domains/huds/signature.verifier'
import { getHudsDir, getBuiltinHudDir } from '../../paths'

/*  WARNING: A lot of this code was create by AI and may contain errors. 
    While I don't love vibe coding, I think protecting hud makers work is more
    important than ensuring I fully understand every line of this code.
*/

/**
 * Middleware that handles signed HUD files.
 * For signed HUDs, decodes JWT-signed files (.js, .css, hud.json) on-the-fly before serving.
 * For unsigned HUDs or non-signed files, passes through to the next handler (static file serving).
 */
export function signedHudMiddleware(req: Request, res: Response, next: NextFunction) {
  const url = req.url

  // Only process file requests (not directories, not /api routes, etc.)
  if (!url.includes('.')) {
    return next()
  }

  // Extract HUD ID from path: /huds/hudId/... or /huds/default/...
  const hudIdMatch = url.match(/^\/huds\/([^/]+)\//)
  if (!hudIdMatch) {
    return next()
  }

  const hudId = hudIdMatch[1]
  const hudDir = hudId === 'default' ? getBuiltinHudDir() : path.join(getHudsDir(), hudId)

  // The built-in HUD is shipped with the app and uses normal compiled assets.
  // Its legacy key file is kept for compatibility, but re-reading every JS/CSS
  // file and trying to decode it as JWT only adds synchronous work and log spam.
  if (hudId === 'default') {
    return next()
  }

  // Check if HUD is signed
  if (!SignatureVerifier.isHudSigned(hudDir)) {
    return next()
  }

  // Only verify specific file types that are actually signed
  const filesToVerify = ['.js', '.css', 'hud.json']
  const shouldVerify = filesToVerify.some((ext) => url.endsWith(ext) || url.includes(ext + '?'))

  // If file type is not signed, pass through to static serving
  if (!shouldVerify) {
    return next()
  }

  try {
    // Get the public key
    const publicKey = SignatureVerifier.getPublicKey(hudDir)

    // Construct the full file path
    const relativePath = url.replace(/^\/huds\/[^/]+\//, '').split('?')[0] // Remove query params
    const filePath = path.join(hudDir, relativePath)

    // Security: prevent path traversal
    if (!filePath.startsWith(hudDir) || !fs.existsSync(filePath)) {
      return next()
    }

    // Read the file
    const fileContent = fs.readFileSync(filePath, 'utf-8')

    // Check if content looks like a JWT (should have format: header.payload.signature)
    const jwtPattern = /^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
    if (!jwtPattern.test(fileContent.trim())) {
      // Not a JWT token, serve as-is
      console.warn(
        `[SignedHUD] File ${relativePath} in signed HUD is not a valid JWT, serving as-is`
      )
      return next()
    }

    // Try to verify and decode the file
    try {
      const decoded = SignatureVerifier.verifySignedFile(fileContent, publicKey)

      // Determine content type
      let contentType = 'application/octet-stream'
      if (filePath.endsWith('.js')) contentType = 'application/javascript'
      else if (filePath.endsWith('.css')) contentType = 'text/css'
      else if (filePath.endsWith('.json')) contentType = 'application/json'

      res.setHeader('Content-Type', contentType)
      return res.send(decoded)
    } catch (verifyError) {
      // Signature verification failed
      console.error(`[SignedHUD] Signature verification failed for ${filePath}:`, verifyError)
      return res.status(403).json({
        error: 'Signature verification failed. This HUD may have been tampered with.',
        details: verifyError instanceof Error ? verifyError.message : String(verifyError)
      })
    }
  } catch (error) {
    console.error(`[SignedHUD] Error processing signed HUD file:`, error)
    return next()
  }
}
