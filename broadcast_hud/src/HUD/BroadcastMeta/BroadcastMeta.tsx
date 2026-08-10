import { useEffect, useState } from "react";
import { useConfig } from "../../API/contexts/actions";

type BroadcastMatch = {
  id: number;
  status: string;
  event: { name: string; short_name: string };
  stage: string;
  bo: string;
};

type BroadcastResponse = {
  ok: boolean;
  match?: BroadcastMatch;
};

const cleanBase = (value: string) => value.trim().replace(/\/+$/, "");

const BroadcastMeta = () => {
  const settings = useConfig("broadcast_settings");
  const [match, setMatch] = useState<BroadcastMatch | null>(null);
  const [connected, setConnected] = useState(false);
  const query = new URLSearchParams(window.location.search);

  const apiBase = cleanBase(
    settings?.api_base || query.get("apiBase") || "https://80gotv.cn"
  );
  const matchId = String(settings?.match_id || query.get("matchId") || "").trim();
  const showEventBar = settings?.show_event_bar !== false;

  useEffect(() => {
    if (!apiBase) return;

    let cancelled = false;
    const load = async () => {
      const endpoint = matchId
        ? `${apiBase}/api/broadcast/matches/${encodeURIComponent(matchId)}`
        : `${apiBase}/api/broadcast/current`;
      try {
        const response = await fetch(endpoint, { cache: "no-store" });
        const payload = (await response.json()) as BroadcastResponse;
        if (cancelled) return;
        setMatch(payload.ok && payload.match ? payload.match : null);
        setConnected(response.ok && payload.ok);
      } catch {
        if (cancelled) return;
        setConnected(false);
      }
    };

    load();
    const interval = window.setInterval(load, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [apiBase, matchId]);

  if (!showEventBar) return null;

  const eventName = match?.event.short_name || match?.event.name || "80CS SUMMER MAJOR";
  const stage = match?.stage || "OFFICIAL BROADCAST";
  const format = match?.bo || "CS2";

  return (
    <header className="broadcast-meta">
      <div className="broadcast-brand">
        <img src="./brand/80gotv-mark.png" alt="" />
        <span>80GOTV</span>
      </div>
      <div className="broadcast-event">
        <strong>{eventName}</strong>
        <span>{stage}</span>
      </div>
      <div className="broadcast-format">{format}</div>
      <div className={`broadcast-link ${connected ? "online" : "local"}`}>
        <span className="broadcast-link-dot" />
        {connected ? "SITE LINK" : "LOCAL"}
      </div>
    </header>
  );
};

export default BroadcastMeta;
