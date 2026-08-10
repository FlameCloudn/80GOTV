import { dbAll, dbGet, dbRun } from '../../database/sqlite'
import { Team, CreateTeamDTO, UpdateTeamDTO } from './team.types'
import crypto from 'crypto'

export class TeamRepository {
  // Helper to map DB row to TypeScript object
  private mapRowToTeam(row: any): Team {
    return {
      _id: row._id,
      name: row.name || '',
      country: row.country || '',
      shortName: row.shortName || '',
      logo: row.logo || '',
      extra: row.extra ? JSON.parse(row.extra) : {}
    }
  }

  // Get all teams
  async getTeams(): Promise<Team[]> {
    const rows = await dbAll('SELECT * FROM teams')
    return rows.map(this.mapRowToTeam)
  }

  // Get team by ID
  async getTeamById(id: string): Promise<Team | null> {
    const row = await dbGet('SELECT * FROM teams WHERE _id = ?', [id])
    return row ? this.mapRowToTeam(row) : null
  }

  // Create
  async createTeam(data: CreateTeamDTO): Promise<Team> {
    const _id = crypto.randomUUID()

    await dbRun(
      `
      INSERT INTO teams (
        _id, name, country, shortName, logo, extra
      ) VALUES (?, ?, ?, ?, ?, ?)
    `,
      [
        _id,
        data.name || null,
        data.country || null,
        data.shortName || null,
        data.logo || null,
        data.extra ? JSON.stringify(data.extra) : null
      ]
    )

    return this.getTeamById(_id) as Promise<Team>
  }

  // Update
  async updateTeam(id: string, data: UpdateTeamDTO): Promise<Team | null> {
    const existing = await this.getTeamById(id)
    if (!existing) return null

    const updated = { ...existing, ...data }

    await dbRun(
      `
      UPDATE teams SET 
        name = ?, 
        country = ?, 
        shortName = ?, 
        logo = ?, 
        extra = ?
      WHERE _id = ?
    `,
      [
        updated.name || null,
        updated.country || null,
        updated.shortName || null,
        updated.logo || null,
        updated.extra ? JSON.stringify(updated.extra) : null,
        id
      ]
    )

    return this.getTeamById(id)
  }

  async setTeamPlayers(id: string, playerIds: string[]): Promise<void> {
    const uniquePlayerIds = [...new Set(playerIds.filter(Boolean))]

    await dbRun('BEGIN TRANSACTION')
    try {
      await dbRun('UPDATE players SET team = NULL WHERE team = ?', [id])

      if (uniquePlayerIds.length > 0) {
        const placeholders = uniquePlayerIds.map(() => '?').join(',')
        await dbRun(`UPDATE players SET team = ? WHERE _id IN (${placeholders})`, [
          id,
          ...uniquePlayerIds
        ])
      }

      await dbRun('COMMIT')
    } catch (error) {
      await dbRun('ROLLBACK')
      throw error
    }
  }

  // Delete
  async deleteTeam(id: string): Promise<boolean> {
    await dbRun('DELETE FROM teams WHERE _id = ?', [id])
    return true
  }

  // Delete team and all its players
  async deleteTeamWithPlayers(id: string): Promise<boolean> {
    await dbRun('DELETE FROM players WHERE team = ?', [id])
    await dbRun('DELETE FROM teams WHERE _id = ?', [id])
    return true
  }
}
