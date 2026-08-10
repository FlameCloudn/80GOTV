export interface Team {
  _id: string
  name: string
  country: string
  shortName: string
  logo: string
  extra: Record<string, string>
}

export type CreateTeamDTO = Omit<Team, '_id'>
export type UpdateTeamDTO = Partial<CreateTeamDTO>
