export interface Player {
  _id: string;
  firstName: string;
  lastName: string;
  username: string;
  avatar: string;
  country: string;
  steamid: string;
  team: string; // ID of the team
  isCoach: boolean;
  extra: Record<string, string>;
}

export type CreatePlayerDTO = Omit<Player, '_id'>;