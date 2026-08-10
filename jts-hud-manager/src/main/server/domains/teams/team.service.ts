import { TeamRepository } from './team.repository'
import { CreateTeamDTO, UpdateTeamDTO } from './team.types'

export class TeamService {
  private repo = new TeamRepository()

  async getTeams() {
    return this.repo.getTeams()
  }

  async getTeamById(id: string) {
    return this.repo.getTeamById(id)
  }

  async getTeamLogoPath(id: string): Promise<string | null> {
    const team = await this.repo.getTeamById(id)
    if (!team || !team.logo) return null
    // logo is stored as "/api/uploads/<filename>" - extract just the filename
    return team.logo.split('/').pop() ?? null
  }

  async createTeam(data: CreateTeamDTO) {
    return this.repo.createTeam(data)
  }

  async updateTeam(id: string, data: UpdateTeamDTO) {
    return this.repo.updateTeam(id, data)
  }

  async setTeamPlayers(id: string, playerIds: string[]) {
    return this.repo.setTeamPlayers(id, playerIds)
  }

  async deleteTeam(id: string) {
    return this.repo.deleteTeam(id)
  }

  async deleteTeamWithPlayers(id: string) {
    return this.repo.deleteTeamWithPlayers(id)
  }
}
