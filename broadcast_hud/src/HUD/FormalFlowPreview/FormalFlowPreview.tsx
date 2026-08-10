import { useEffect, useState } from "react";
import BpShowcase from "../BpShowcase/BpShowcase";
import BroadcastPreview from "../Preview/BroadcastPreview";
import PauseShowcase from "../PauseShowcase/PauseShowcase";
import HalftimeShowcase from "../HalftimeShowcase/HalftimeShowcase";
import VictoryShowcase from "../VictoryShowcase/VictoryShowcase";

type FlowScene =
  | "bp"
  | "live_first"
  | "tactical"
  | "live_after_tactical"
  | "technical"
  | "live_before_half"
  | "halftime"
  | "live_second"
  | "victory";

const flow: Array<{ scene: FlowScene; duration: number }> = [
  { scene: "bp", duration: 15300 },
  { scene: "live_first", duration: 7000 },
  { scene: "tactical", duration: 7000 },
  { scene: "live_after_tactical", duration: 5000 },
  { scene: "technical", duration: 7000 },
  { scene: "live_before_half", duration: 5000 },
  { scene: "halftime", duration: 19000 },
  { scene: "live_second", duration: 7000 },
  { scene: "victory", duration: 15000 },
];

const FormalFlowPreview = () => {
  const [step, setStep] = useState(0);
  const current = flow[Math.min(step, flow.length - 1)];

  useEffect(() => {
    if (step >= flow.length - 1) return;
    const timer = window.setTimeout(() => setStep((value) => value + 1), current.duration);
    return () => window.clearTimeout(timer);
  }, [current.duration, step]);

  if (current.scene === "bp") return <BpShowcase demo />;
  if (current.scene === "tactical") return <PauseShowcase demoKind="tactical_t" />;
  if (current.scene === "technical") return <PauseShowcase demoKind="technical" />;
  if (current.scene === "halftime") return <HalftimeShowcase demo />;
  if (current.scene === "victory") return <VictoryShowcase demo />;

  const liveProps = current.scene === "live_first"
    ? { leftScore: 4, rightScore: 5, timer: "0:48", roundLabel: "ROUND 10 / 24" }
    : current.scene === "live_after_tactical"
      ? { leftScore: 5, rightScore: 6, timer: "1:21", roundLabel: "ROUND 12 / 24" }
      : current.scene === "live_before_half"
        ? { leftScore: 5, rightScore: 7, timer: "0:06", roundLabel: "ROUND 12 / 24" }
        : { leftScore: 9, rightScore: 8, timer: "0:37", roundLabel: "ROUND 18 / 24" };

  return <BroadcastPreview
    leftName="TEAM A"
    rightName="TEAM B"
    mapName="MIRAGE"
    mapNumber="MAP 1 / 3"
    {...liveProps}
  />;
};

export default FormalFlowPreview;
