import { MatchRepository } from './match.repository'
import { CreateMatchDTO, UpdateMatchDTO } from './match.types'

export class MatchService {
  private repo = new MatchRepository()

  async getAllMatches() {
    return this.repo.getAllMatches()
  }

  async getCurrentMatch() {
    const match = await this.repo.getCurrentMatch()
    if (!match) {
      throw new Error('No current match found')
    }
    return match
  }

  async getMatchById(id: string) {
    const match = await this.repo.getMatchById(id)
    if (!match) throw new Error('Match not found')
    return match
  }

  async createMatch(data: CreateMatchDTO) {
    if (data.current) {
      await this.repo.setAllMatchesNotCurrent()
    }
    return this.repo.createMatch(data)
  }

  async updateMatch(id: string, data: UpdateMatchDTO) {
    if (data.vetos) {
      const existing = await this.getMatchById(id)
      const isLocked = (veto: (typeof existing.vetos)[number]) =>
        Boolean(veto.openingCtTeamId) ||
        veto.sideSource === 'website_bp' ||
        veto.sideSource === 'tgpro_stable_gsi'
      const nextVetos = data.vetos.map((next) => {
        const current = existing.vetos.find((veto) => veto.mapName === next.mapName)
        if (!current || !isLocked(current)) return next
        return {
          ...next,
          reverseSide: false,
          openingCtTeamId: current.openingCtTeamId,
          sideSource: current.sideSource
        }
      })
      for (const current of existing.vetos.filter(isLocked)) {
        if (!nextVetos.some((veto) => veto.mapName === current.mapName)) nextVetos.push(current)
      }
      data = { ...data, vetos: nextVetos }
    }
    if (data.current) {
      await this.repo.setAllMatchesNotCurrent()
    }
    const match = await this.repo.updateMatch(id, data)
    if (!match) throw new Error('Match not found to update')
    return match
  }

  async deleteMatch(id: string) {
    return this.repo.deleteMatch(id)
  }

  async toggleVetoReverseSide(mapName: string) {
    const match = await this.repo.toggleVetoReverseSide(mapName)
    if (!match) throw new Error('No current match or map not found in vetos')
    return match
  }
}
