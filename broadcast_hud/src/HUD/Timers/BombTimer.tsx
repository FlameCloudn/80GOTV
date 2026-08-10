import { MAX_TIMER, useBombTimer } from "./Countdown";
import { C4 } from "./../../assets/Icons";

type BombTimerData = ReturnType<typeof useBombTimer>;

const Bomb = ({ bombData }: { bombData: BombTimerData }) => {
  const show = bombData.state === "planted" || bombData.state === "defusing";
  const remaining = Math.max(0, Math.min(MAX_TIMER.bomb, bombData.bombTime));
  const progress = remaining * 100 / MAX_TIMER.bomb;
  const urgent = remaining <= 10;
  const totalSeconds = Math.ceil(remaining);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const clock = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

  return (
    <div id="bomb_container" className={show ? "show" : "hide"} aria-hidden={!show}>
      <div className={`bomb_countdown ${urgent ? "urgent" : ""}`}>{clock}</div>
      <div className="bomb_status">
        <span className="bomb_status_label">PLANTED</span>
        <span className="bomb_icon"><C4 fill="white" /></span>
        <span className="bomb_timer_track" aria-hidden="true">
          <span className="bomb_timer" style={{ width: `${progress}%` }} />
        </span>
      </div>
    </div>
  );
}

export default Bomb;
