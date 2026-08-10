import { dbAll, dbGet, dbRun } from '../../database/sqlite'
import { Match, CreateMatchDTO, UpdateMatchDTO } from './match.types'
import crypto from 'crypto'

export class MatchRepository {
  // Helper to map a flat database row back into the nested Match interface
  private mapRowToMatch(row: any): Match {
    return {
      id: row.id,
      current: row.current === 1,
      left: {
        id: row.left_id || null,
        wins: row.left_wins || 0
      },
      right: {
        id: row.right_id || null,
        wins: row.right_wins || 0
      },
      matchType: row.matchType || 'bo1',
      vetos: row.vetos ? JSON.parse(row.vetos) : null
    }
  }

  // Get all matches
  async getAllMatches(): Promise<Match[]> {
    const rows = await dbAll('SELECT * FROM matches')
    return rows.map(this.mapRowToMatch)
  }

  // Get current match
  async getCurrentMatch(): Promise<Match | null> {
    const row = await dbGet('SELECT * FROM matches WHERE current = 1 LIMIT 1')
    return row ? this.mapRowToMatch(row) : null
  }

  // Get by ID
  async getMatchById(id: string): Promise<Match | null> {
    const row = await dbGet('SELECT * FROM matches WHERE id = ?', [id])
    return row ? this.mapRowToMatch(row) : null
  }

  // Create
  async createMatch(data: CreateMatchDTO): Promise<Match> {
    const id = crypto.randomUUID()

    // Flatten the nested DTO into variables for the query
    const current = data.current ? 1 : 0
    const leftId = data.left?.id || null
    const leftWins = data.left?.wins || 0
    const rightId = data.right?.id || null
    const rightWins = data.right?.wins || 0
    const matchType = data.matchType || 'bo1'
    const vetos = data.vetos ? JSON.stringify(data.vetos) : null

    await dbRun(
      `
      INSERT INTO matches (
        id, current, left_id, left_wins, right_id, right_wins, matchType, vetos
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
      [id, current, leftId, leftWins, rightId, rightWins, matchType, vetos]
    )

    return this.getMatchById(id) as Promise<Match>
  }

  // Update
  async updateMatch(id: string, data: UpdateMatchDTO): Promise<Match | null> {
    const existing = await this.getMatchById(id)
    if (!existing) return null

    // Merge existing data with new data (deep merge for nested left/right objects)
    const updated: Match = {
      ...existing,
      ...data,
      left: { ...existing.left, ...data.left },
      right: { ...existing.right, ...data.right }
    }

    await dbRun(
      `
      UPDATE matches SET 
        current = ?, 
        left_id = ?, 
        left_wins = ?, 
        right_id = ?, 
        right_wins = ?, 
        matchType = ?, 
        vetos = ?
      WHERE id = ?
    `,
      [
        updated.current ? 1 : 0,
        updated.left.id || null,
        updated.left.wins || 0,
        updated.right.id || null,
        updated.right.wins || 0,
        updated.matchType,
        updated.vetos ? JSON.stringify(updated.vetos) : null,
        id
      ]
    )

    return this.getMatchById(id)
  }

  // Unset current flag on all matches (used before setting a new one)
  async setAllMatchesNotCurrent(): Promise<void> {
    await dbRun('UPDATE matches SET current = 0')
  }

  // Toggle reverseSide on the veto matching mapName in the current match
  async toggleVetoReverseSide(mapName: string): Promise<Match | null> {
    const match = await this.getCurrentMatch()
    if (!match || !match.vetos) return null

    const target = match.vetos.find((v) => v.mapName === mapName)
    if (target?.openingCtTeamId || ['website_bp', 'tgpro_stable_gsi'].includes(target?.sideSource || '')) {
      throw new Error('Opening sides are locked by website BP or stable TGPro data')
    }

    const vetos = match.vetos.map((v) =>
      v.mapName === mapName ? { ...v, reverseSide: !v.reverseSide } : v
    )

    await dbRun('UPDATE matches SET vetos = ? WHERE current = 1', [JSON.stringify(vetos)])
    return this.getCurrentMatch()
  }

  // Delete
  async deleteMatch(id: string): Promise<boolean> {
    await dbRun('DELETE FROM matches WHERE id = ?', [id])
    return true
  }
}
