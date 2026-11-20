import { updateBadgeCount } from '../features/notifications/badge.mjs';
import '../features/notifications/popup.mjs';

updateBadgeCount();
setInterval(updateBadgeCount, 120000);
