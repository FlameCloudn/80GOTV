type RatingInput = {
  rating?: unknown;
  kills?: unknown;
  deaths?: unknown;
  assists?: unknown;
  damage?: unknown;
  adr?: unknown;
  roundsPlayed?: unknown;
  kast?: unknown;
  kastRounds?: unknown;
};

export type RatedMap = { rating: number; rounds: number };

const finiteNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

export const mapRating = (player: RatingInput, fallbackRounds = 1): number => {
  const existingRating = finiteNumber(player.rating);
  if (existingRating !== null && existingRating >= 0) return existingRating;

  const recordedRounds = finiteNumber(player.roundsPlayed);
  const roundsFallback = finiteNumber(fallbackRounds);
  const rounds = Math.max(
    1,
    recordedRounds !== null && recordedRounds > 0
      ? recordedRounds
      : roundsFallback !== null && roundsFallback > 0
        ? roundsFallback
        : 1,
  );
  const kills = Math.max(0, finiteNumber(player.kills) ?? 0);
  const deaths = Math.max(0, finiteNumber(player.deaths) ?? 0);
  const assists = Math.max(0, finiteNumber(player.assists) ?? 0);
  const damage = finiteNumber(player.damage);
  const adr = Math.max(0, finiteNumber(player.adr) ?? (damage !== null ? damage / rounds : 0));
  const minimumKastRounds = Math.min(rounds, Math.max(kills, assists, rounds - deaths));
  const storedKastRounds = Math.max(0, finiteNumber(player.kastRounds) ?? 0);
  const storedKast = Math.min(100, Math.max(0, finiteNumber(player.kast) ?? 0));
  const kastRounds = Math.min(
    rounds,
    Math.max(minimumKastRounds, storedKastRounds, (storedKast * rounds) / 100),
  );
  const kast = (kastRounds * 100) / rounds;
  const kpr = kills / rounds;
  const dpr = deaths / rounds;
  const apr = assists / rounds;
  const impact = 2.13 * kpr + 0.42 * apr - 0.41;
  const rating = 0.0073 * kast + 0.3591 * kpr - 0.5329 * dpr
    + 0.2372 * impact + 0.0032 * adr + 0.1587;
  return Number(Math.max(0, rating).toFixed(2));
};

export const weightedSeriesRating = (maps: readonly RatedMap[]): number => {
  const ratedMaps = maps.filter(
    (map) => Number.isFinite(map.rating) && map.rating >= 0 && Number.isFinite(map.rounds) && map.rounds > 0,
  );
  const rounds = ratedMaps.reduce((total, map) => total + map.rounds, 0);
  if (!rounds) return 0;
  const rating = ratedMaps.reduce((total, map) => total + map.rating * map.rounds, 0) / rounds;
  return Number(rating.toFixed(2));
};
