import { Router, Request, Response } from 'express';
import { dbAll, dbRun } from '../../database/sqlite';

const router = Router();
const MASKED_WEBSITE_TOKEN = '********';

export interface AppSettings {
  autoSwitchSides: boolean;
  telnetHost: string;
  telnetPort: number;
  websiteUrl: string;
  websiteGsiToken: string;
  websiteMatchId: string;
  forwardLiveData: boolean;
  directorShortcuts: string;
}

const DEFAULT_SETTINGS: AppSettings = {
  autoSwitchSides: true,
  telnetHost: '127.0.0.1',
  telnetPort: 2020,
  websiteUrl: 'https://80gotv.cn',
  websiteGsiToken: '',
  websiteMatchId: '',
  forwardLiveData: false,
  directorShortcuts: '{}',
};

const ALLOWED_KEYS = new Set<keyof AppSettings>([
  'autoSwitchSides',
  'telnetHost',
  'telnetPort',
  'websiteUrl',
  'websiteGsiToken',
  'websiteMatchId',
  'forwardLiveData',
  'directorShortcuts',
]);

// Load all settings from the DB and return as a typed object
export const getSettings = async (): Promise<AppSettings> => {
  const rows: { key: string; value: string }[] = await dbAll('SELECT key, value FROM settings');
  const map = Object.fromEntries(rows.map(r => [r.key, r.value]));
  return {
    autoSwitchSides: map.autoSwitchSides !== undefined ? map.autoSwitchSides === 'true' : DEFAULT_SETTINGS.autoSwitchSides,
    telnetHost: map.telnetHost ?? DEFAULT_SETTINGS.telnetHost,
    telnetPort: map.telnetPort !== undefined ? Number(map.telnetPort) : DEFAULT_SETTINGS.telnetPort,
    websiteUrl: map.websiteUrl ?? DEFAULT_SETTINGS.websiteUrl,
    websiteGsiToken: map.websiteGsiToken ?? DEFAULT_SETTINGS.websiteGsiToken,
    websiteMatchId: map.websiteMatchId ?? DEFAULT_SETTINGS.websiteMatchId,
    forwardLiveData: map.forwardLiveData !== undefined ? map.forwardLiveData === 'true' : DEFAULT_SETTINGS.forwardLiveData,
    directorShortcuts: map.directorShortcuts ?? DEFAULT_SETTINGS.directorShortcuts,
  };
};

const publicSettings = async (): Promise<AppSettings> => {
  const settings = await getSettings();
  return {
    ...settings,
    websiteGsiToken: settings.websiteGsiToken ? MASKED_WEBSITE_TOKEN : '',
  };
};

// GET /api/settings — return all settings as a JSON object
router.get('/', async (_req: Request, res: Response) => {
  try {
    res.json(await publicSettings());
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

// PUT /api/settings — update one or more settings keys
router.put('/', async (req: Request, res: Response) => {
  try {
    const updates: Partial<AppSettings> = req.body;
    for (const [key, value] of Object.entries(updates)) {
      if (!ALLOWED_KEYS.has(key as keyof AppSettings)) continue;
      // The renderer receives a masked token. Keeping that value must not
      // overwrite the real secret when the user only changes the URL.
      if (key === 'websiteGsiToken' && value === MASKED_WEBSITE_TOKEN) continue;
      await dbRun(
        'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        [key, key === 'directorShortcuts' ? JSON.stringify(value ?? {}) : String(value)]
      );
    }
    res.json(await publicSettings());
  } catch (err: any) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
