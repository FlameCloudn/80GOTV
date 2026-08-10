import { PlayerRepository } from './player.repository'
import { CreatePlayerDTO, UpdatePlayerDTO } from './player.types'

export class PlayerService {
  private repo = new PlayerRepository()

  async getPlayers(steamidsString?: string) {
    // The HUD sends steamids as a semicolon-separated string: "steamids=id1;id2"
    let steamidsArray: string[] | undefined = undefined

    if (steamidsString) {
      steamidsArray = steamidsString.split(';').filter((id) => id.trim() !== '')
    }

    return this.repo.getPlayers(steamidsArray)
  }

  async getPlayerAvatar(steamid: string) {
    const player = await this.repo.getPlayerBySteamId(steamid)
    if (!player) {
      return { custom: '', steam: '' } // If player doesnt exist
    }

    return {
      custom: player.avatar || '',
      steam: player.avatar || ''
    }
  }

  async getPlayerById(id: string) {
    return this.repo.getPlayerById(id)
  }

  async createPlayer(data: CreatePlayerDTO) {
    return this.repo.createPlayer(data)
  }

  async updatePlayer(id: string, data: UpdatePlayerDTO) {
    return this.repo.updatePlayer(id, data)
  }

  async deletePlayer(id: string) {
    return this.repo.deletePlayer(id)
  }
}
