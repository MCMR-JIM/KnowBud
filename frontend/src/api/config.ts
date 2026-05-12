const API_PORT = import.meta.env.VITE_API_PORT || 8090;
const API_HOST = import.meta.env.VITE_API_HOST || '127.0.0.1';

export const API_BASE = `http://${API_HOST}:${API_PORT}/v1`;
export const API_BASE_NO_VERSION = `http://${API_HOST}:${API_PORT}`;
