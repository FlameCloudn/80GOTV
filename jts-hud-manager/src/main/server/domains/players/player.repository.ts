import { dbAll, dbGet, dbRun } from '../../database/sqlite'
import { Player, CreatePlayerDTO, UpdatePlayerDTO } from './player.types'
import crypto from 'crypto'

export class PlayerRepository {
  // Helper function to map a database row to the TypeScript interface
  private mapRowToPlayer(row: any): Player {
    return {
      _id: row._id,
      firstName: row.firstName || '',
      lastName: row.lastName || '',
      username: row.username || '',
      avatar: row.avatar || '',
      country: row.country || '',
      steamid: row.steamid || '',
      team: row.team || null,
      isCoach: row.isCoach === 1,
      extra: row.extra ? JSON.parse(row.extra) : {}
    }
  }

  // Get all players, optionally filtered by an array of steamids
  async getPlayers(steamids?: string[]): Promise<Player[]> {
    if (steamids && steamids.length > 0) {
      // Create ?,?,? placeholders based on array length
      const placeholders = steamids.map(() => '?').join(',')
      const rows = await dbAll(`SELECT * FROM players WHERE steamid IN (${placeholders})`, steamids)
      return rows.map(this.mapRowToPlayer)
    }

    const rows = await dbAll('SELECT * FROM players')
    return rows.map(this.mapRowToPlayer)
  }

  // Get by steamid
  async getPlayerBySteamId(steamid: string): Promise<Player | null> {
    const row = await dbGet('SELECT * FROM players WHERE steamid = ?', [steamid])
    return row ? this.mapRowToPlayer(row) : null
  }

  // Get by ID
  async getPlayerById(id: string): Promise<Player | null> {
    const row = await dbGet('SELECT * FROM players WHERE _id = ?', [id])
    return row ? this.mapRowToPlayer(row) : null
  }

  // Create
  async createPlayer(data: CreatePlayerDTO): Promise<Player> {
    const _id = crypto.randomUUID()

    await dbRun(
      `
      INSERT INTO players (
        _id, firstName, lastName, username, avatar, country, steamid, team, isCoach, extra
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
      [
        _id,
        data.firstName || null,
        data.lastName || null,
        data.username || null,
        data.avatar || null,
        data.country || null,
        data.steamid || null,
        data.team || null,
        data.isCoach ? 1 : 0,
        data.extra ? JSON.stringify(data.extra) : null
      ]
    )

    return this.getPlayerById(_id) as Promise<Player>
  }

  // Update
  async updatePlayer(id: string, data: UpdatePlayerDTO): Promise<Player | null> {
    const existing = await this.getPlayerById(id)
    if (!existing) return null

    // Merge existing data with new data
    const updated = { ...existing, ...data }

    await dbRun(
      `
      UPDATE players SET 
        firstName = ?, 
        lastName = ?, 
        username = ?, 
        avatar = ?, 
        country = ?, 
        steamid = ?, 
        team = ?, 
        isCoach = ?,
        extra = ?
      WHERE _id = ?
    `,
      [
        updated.firstName || null,
        updated.lastName || null,
        updated.username || null,
        updated.avatar || null,
        updated.country || null,
        updated.steamid || null,
        updated.team || null,
        updated.isCoach ? 1 : 0,
        updated.extra ? JSON.stringify(updated.extra) : null,
        id
      ]
    )

    return this.getPlayerById(id)
  }

  // Delete
  async deletePlayer(id: string): Promise<boolean> {
    await dbRun('DELETE FROM players WHERE _id = ?', [id])
    return true
  }
}
