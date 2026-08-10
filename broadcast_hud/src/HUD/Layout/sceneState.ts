export type DirectorScene =
  | "auto"
  | "game"
  | "pause_current"
  | "pause_technical"
  | "halftime"
  | "map_end"
  | "series_end";

export type PauseKind = "technical" | "tactical_t" | "tactical_ct" | null;

type SceneGame = {
  map?: {
    phase?: string;
    team_ct?: { score?: number };
    team_t?: { score?: number };
  };
  phase_countdowns?: {
    phase?: string;
  };
};

const normalizedPhase = (value?: string) => String(value || "").trim().toLowerCase();

export const getPauseKind = (phase?: string): PauseKind => {
  switch (normalizedPhase(phase)) {
    case "timeout_t":
    case "timeout_terrorist":
      return "tactical_t";
    case "timeout_ct":
    case "timeout_counterterrorist":
      return "tactical_ct";
    case "paused":
    case "pause":
    case "technical":
    case "technical_pause":
    case "timeout_technical":
      return "technical";
    default:
      return null;
  }
};

export const isRegulationHalftime = (game?: SceneGame | null): boolean => {
  if (!game?.map) return false;
  const totalScore =
    (Number(game.map.team_ct?.score) || 0) + (Number(game.map.team_t?.score) || 0);
  const mapPhase = normalizedPhase(game.map.phase);
  const countdownPhase = normalizedPhase(game.phase_countdowns?.phase);
  return totalScore === 12 && (
    mapPhase === "intermission" ||
    countdownPhase === "halftime" ||
    countdownPhase === "intermission"
  );
};

export const automaticDirectorScene = (
  game?: SceneGame | null,
  detectedPause?: PauseKind
): DirectorScene => {
  if (isRegulationHalftime(game)) return "halftime";
  const pause = detectedPause === undefined
    ? getPauseKind(game?.phase_countdowns?.phase)
    : detectedPause;
  if (pause === "technical") return "pause_technical";
  if (pause === "tactical_t" || pause === "tactical_ct") return "pause_current";
  return "game";
};
