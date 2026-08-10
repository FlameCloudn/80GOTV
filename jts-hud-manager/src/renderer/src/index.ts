const query = new URLSearchParams(window.location.search)
export const port = Number(query.get('port') || 1349)
export const LOCAL_SERVER_URL = `http://127.0.0.1:${port}`
export const API_URL = `${LOCAL_SERVER_URL}/api`
