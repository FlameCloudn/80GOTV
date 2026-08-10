import { io } from "socket.io-client";
import { isDev, port } from ".";
import { GSI, hudIdentity } from "./HUD";
import { CSGORaw } from "csgogsi";
import { actions, configs } from "./contexts/actions";
import type { CSGO } from "csgogsi";
import type { Match } from "./types";

export const socket = io(isDev ? `localhost:${port}` : '/');

let activeMatch: Match | null = null;

export const setActiveMatch = (match: Match | null) => {
    activeMatch = match;
};

type RoundPlayerDamage = {
	steamid: string;
	damage: number;
};
type RoundDamage = {
	round: number;
	players: RoundPlayerDamage[];
};

// The app also sends team metadata to csgogsi. That metadata can contain the
// last value saved in the local match record, which is not authoritative while
// a new map is being played. Before parsing each frame, copy the live CS2
// series score over the metadata so a reused match cannot show old map wins.
const syncLiveSeriesScores = (raw: any) => {
    // Series wins come from the website-synced match, never from TGPro's
    // observer slots or its often-missing default series fields.
    if (!raw?.map || !GSI.teams.left || !GSI.teams.right) return;
    const leftId = GSI.teams.left.id;
    const rightId = GSI.teams.right.id;
    const leftScore = Number(GSI.teams.left.map_score) || 0;
    const rightScore = Number(GSI.teams.right.map_score) || 0;
    const mappedCt = raw?._80gotv?.team_ct;
    const mappedT = raw?._80gotv?.team_t;
    if (mappedCt === 'team1' && mappedT === 'team2') {
        raw.map.team_ct.matches_won_this_series = leftScore;
        raw.map.team_t.matches_won_this_series = rightScore;
        return;
    }
    if (mappedCt === 'team2' && mappedT === 'team1') {
        raw.map.team_ct.matches_won_this_series = rightScore;
        raw.map.team_t.matches_won_this_series = leftScore;
        return;
    }
    // Older APP/server builds did not attach _80gotv mapping. Keep their
    // explicit team-id path as a compatibility fallback.
    if (raw.map.team_ct?.id === leftId || raw.map.team_t?.id === leftId) {
        if (raw.map.team_ct?.id === leftId) {
            raw.map.team_ct.matches_won_this_series = leftScore;
            raw.map.team_t.matches_won_this_series = rightScore;
        } else {
            raw.map.team_ct.matches_won_this_series = rightScore;
            raw.map.team_t.matches_won_this_series = leftScore;
        }
    }
};

const normalizeMapName = (value: unknown) => {
    const name = String(value || '').trim().toLowerCase().replace(/^de_/, '');
    return name.replace(/^.*\//, '');
};

const openingCtTeamIdFor = (raw: any) => {
    const mapName = normalizeMapName(raw?.map?.name);
    const veto = activeMatch?.vetos.find((item) => normalizeMapName(item.mapName) === mapName);
    return veto?.openingCtTeamId || null;
};

const canonicalizeGameTeams = (raw: any, parsed: CSGO | null): CSGO | null => {
    if (!parsed?.map || !GSI.teams.left || !GSI.teams.right) return parsed;

    const leftIdentity = GSI.teams.left;
    const rightIdentity = GSI.teams.right;
    const leftId = String(leftIdentity.id || '');
    const rightId = String(rightIdentity.id || '');
    const metadataTeamId = (value: unknown) => {
        if (value === 'team1') return leftId;
        if (value === 'team2') return rightId;
        return '';
    };
    const rawCtCandidate = String(raw?.map?.team_ct?.id || '');
    const rawTCandidate = String(raw?.map?.team_t?.id || '');
    const rawCtId = [leftId, rightId].includes(rawCtCandidate)
        ? rawCtCandidate
        : metadataTeamId(raw?._80gotv?.team_ct);
    const rawTId = [leftId, rightId].includes(rawTCandidate)
        ? rawTCandidate
        : metadataTeamId(raw?._80gotv?.team_t);
    const hasKnownSides = [rawCtId, rawTId].every((id) => id === leftId || id === rightId) && rawCtId !== rawTId;
    if (!hasKnownSides) return parsed;

    let ctId = rawCtId;
    let tId = rawTId;
    const openingCtId = openingCtTeamIdFor(raw);
    const scoreTotal = Number(raw?.map?.team_ct?.score || 0) + Number(raw?.map?.team_t?.score || 0);
    // Before the first round score exists, BP is the authority for the first
    // colors. Once the map is live, the raw CS2 side is authoritative.
    if (openingCtId && scoreTotal === 0 && (openingCtId === leftId || openingCtId === rightId)) {
        ctId = openingCtId;
        tId = openingCtId === leftId ? rightId : leftId;
    }

    const teamObject = (id: string, side: 'CT' | 'T', existing: any) => {
        const identity = id === leftId ? leftIdentity : rightIdentity;
        return {
            ...existing,
            id,
            name: identity.name || existing?.name,
            country: identity.country ?? existing?.country ?? null,
            logo: identity.logo || existing?.logo || null,
            extra: identity.extra || existing?.extra || {},
            side,
            orientation: id === leftId ? 'left' : 'right'
        };
    };

    parsed.map.team_ct = teamObject(ctId, 'CT', parsed.map.team_ct);
    parsed.map.team_t = teamObject(tId, 'T', parsed.map.team_t);

    // Keep every player card and the observed-player panel on the same side
    // object as the scoreboard, so their color changes together at halftime.
    parsed.players = parsed.players.map((player) => {
        const rawPlayer = raw?.allplayers?.[player.steamid];
        const side = String(rawPlayer?.team || player.team?.side || '').toUpperCase();
        return {
            ...player,
            team: side === 'CT' ? parsed.map.team_ct : parsed.map.team_t
        };
    });
    if (parsed.player) {
        const side = String(raw?.allplayers?.[parsed.player.steamid]?.team || parsed.player.team?.side || '').toUpperCase();
        parsed.player = {
            ...parsed.player,
            team: side === 'CT' ? parsed.map.team_ct : parsed.map.team_t
        };
    }
    return parsed;
};

const digestAndCanonicalize = (data: CSGORaw) => {
    syncLiveSeriesScores(data);
    const parsed = GSI.digest(data);
    return canonicalizeGameTeams(data, parsed);
};

socket.on("update", (data: any, damage: any) => {
    if (damage) {
        GSI.damage = damage;
    }
    digestAndCanonicalize(data);
});

const isInWindow = !!window.parent.ipcApi;

if(isInWindow){
	window.parent.ipcApi.receive('raw', (data: CSGORaw, damage?: RoundDamage[]) => {
		if(damage){
			GSI.damage = damage;
		}
        digestAndCanonicalize(data);
	});
}

const href = window.location.href;

socket.on("connect", () => {
    socket.emit("started");
});

if (isDev) {
    hudIdentity.name = (Math.random() * 1000 + 1).toString(36).replace(/[^a-z]+/g, '').substr(0, 15);
    hudIdentity.isDev = true;
} else {
    const segment = href.substr(href.indexOf('/huds/') + 6);
    hudIdentity.name = segment.substr(0, segment.lastIndexOf('/'));
}

socket.on("readyToRegister", () => {
    socket.emit("register", hudIdentity.name, isDev, "cs2", isInWindow ? "IPC" : "DEFAULT");
});
socket.on(`hud_config`, (data: any) => {
    configs.save(data);
});
socket.on(`hud_action`, (data: any) => {
    actions.execute(data.action, data.data);
});
socket.on('keybindAction', (action: string) => {
    actions.execute(action);
});

socket.on("refreshHUD", () => {
    window.top?.location.reload();
});

socket.on("update_mirv", (data: any) => {
    GSI.digestMIRV(data);
})
