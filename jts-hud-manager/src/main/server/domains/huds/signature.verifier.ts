import fs from 'fs'
import path from 'path'
import jwt from 'jsonwebtoken'

/*  WARNING: A lot of this code was create by AI and may contain errors. 
    While I don't love vibe coding, I think protecting hud makers work is more
    important than ensuring I fully understand every line of this code.
*/

/**
 * Verifies JWT-signed HUD files and manages public keys for signed HUDs.
 * Signed HUDs use RS256 algorithm with a public key stored in a 'key' file.
 */
export class SignatureVerifier {
  /**
   * Check if a HUD directory is signed (contains a 'key' file)
   */
  static isHudSigned(hudDir: string): boolean {
    const keyPath = path.join(hudDir, 'key')
    return fs.existsSync(keyPath)
  }

  /**
   * Get the public key for a signed HUD
   * @throws Error if key file doesn't exist or can't be read
   */
  static getPublicKey(hudDir: string): string {
    const keyPath = path.join(hudDir, 'key')
    if (!fs.existsSync(keyPath)) {
      throw new Error(`No public key found for HUD at ${hudDir}`)
    }
    return fs.readFileSync(keyPath, 'utf-8')
  }

  /**
   * Verify a JWT-signed file content
   * @param fileContent - The content of the signed file (should be a JWT string)
   * @param publicKey - The public key to verify with
   * @returns Decoded content if valid
   * @throws Error if signature is invalid
   */
  static verifySignedFile(fileContent: string, publicKey: string): string {
    try {
      const decoded = jwt.verify(fileContent, publicKey, { algorithms: ['RS256'] })
      // JWT payload is the original file content
      return typeof decoded === 'string' ? decoded : JSON.stringify(decoded)
    } catch (error) {
      throw new Error(
        `Signature verification failed: ${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  /**
   * Try to verify a file (returns original if not signed, or verifies if signed)
   * Returns { verified: boolean, content: string, error?: string }
   */
  static tryVerifyFile(
    fileContent: string,
    publicKey: string | null
  ): {
    verified: boolean
    content: string
    error?: string
  } {
    // If no public key, return content as-is
    if (!publicKey) {
      return { verified: false, content: fileContent }
    }

    // Try to verify as signed file
    try {
      const decoded = this.verifySignedFile(fileContent, publicKey)
      return { verified: true, content: decoded }
    } catch (error) {
      return {
        verified: false,
        content: fileContent,
        error: error instanceof Error ? error.message : String(error)
      }
    }
  }

  /**
   * Get file signature status for a HUD
   * @returns Object with isSigned flag and publicKey if available
   */
  static getHudSignatureStatus(hudDir: string): {
    isSigned: boolean
    publicKey?: string
  } {
    if (this.isHudSigned(hudDir)) {
      try {
        return {
          isSigned: true,
          publicKey: this.getPublicKey(hudDir)
        }
      } catch {
        return { isSigned: true } // Has key file but couldn't read
      }
    }
    return { isSigned: false }
  }

  /**
   * Verify hud.json file content and return parsed JSON
   * Handles both signed (JWT) and unsigned JSON files
   */
  static verifyAndParseHudJson(hudJsonPath: string): {
    data: Record<string, any>
    isSigned: boolean
    error?: string
  } {
    try {
      const fileContent = fs.readFileSync(hudJsonPath, 'utf-8')
      const hudDir = path.dirname(hudJsonPath)
      const signatureStatus = this.getHudSignatureStatus(hudDir)

      // If HUD is signed, try to verify
      if (signatureStatus.isSigned && signatureStatus.publicKey) {
        try {
          const decoded = this.verifySignedFile(fileContent, signatureStatus.publicKey)
          const data = JSON.parse(decoded)
          return { data, isSigned: true }
        } catch (error) {
          return {
            data: {},
            isSigned: true,
            error: `Failed to verify hud.json signature: ${error instanceof Error ? error.message : String(error)}`
          }
        }
      }

      // Not signed, try to parse as JSON
      try {
        const data = JSON.parse(fileContent)
        return { data, isSigned: false }
      } catch (parseError) {
        return {
          data: {},
          isSigned: false,
          error: `Invalid JSON in hud.json: ${parseError instanceof Error ? parseError.message : String(parseError)}`
        }
      }
    } catch (readError) {
      return {
        data: {},
        isSigned: false,
        error: `Failed to read hud.json: ${readError instanceof Error ? readError.message : String(readError)}`
      }
    }
  }
}
