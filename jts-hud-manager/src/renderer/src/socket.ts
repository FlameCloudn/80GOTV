import { io } from 'socket.io-client';
import { LOCAL_SERVER_URL } from './index';

// Shared socket connection for the Electron renderer / admin UI
export const socket = io(LOCAL_SERVER_URL, {
  autoConnect: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 1000,
});
