export type UserRole = "student" | "teacher";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
}

export interface TokenStorage {
  setItem(key: string, value: string): void;
  getItem(key: string): string | null;
  removeItem(key: string): void;
}

type FetchImpl = typeof fetch;

export const ACCESS_TOKEN_KEY = "access_token";
export const REFRESH_TOKEN_KEY = "refresh_token";

export function browserTokenStorage(): TokenStorage | null {
  if (typeof window === "undefined" || !window.localStorage) return null;
  return window.localStorage;
}

export function saveTokens(storage: TokenStorage, pair: TokenPair): void {
  storage.setItem(ACCESS_TOKEN_KEY, pair.access_token);
  storage.setItem(REFRESH_TOKEN_KEY, pair.refresh_token);
}

export function clearTokens(storage: TokenStorage): void {
  storage.removeItem(ACCESS_TOKEN_KEY);
  storage.removeItem(REFRESH_TOKEN_KEY);
}

function decodePayload(token: string): Record<string, unknown> | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function decodeRoleFromToken(token: string): UserRole | null {
  const role = decodePayload(token)?.role;
  return role === "student" || role === "teacher" ? role : null;
}

export function decodeSubjectFromToken(token: string): string | null {
  const subject = decodePayload(token)?.sub;
  return typeof subject === "string" && subject ? subject : null;
}

async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Ответ может не содержать JSON.
  }
  return fallback;
}

export async function refreshStoredAccessToken(options: {
  apiBaseUrl?: string;
  storage?: TokenStorage | null;
  fetchImpl?: FetchImpl;
} = {}): Promise<string | null> {
  const storage = options.storage ?? browserTokenStorage();
  if (!storage) return null;
  const refreshToken = storage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return storage.getItem(ACCESS_TOKEN_KEY);

  const response = await (options.fetchImpl ?? fetch)(
    `${options.apiBaseUrl ?? (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ""}/auth/refresh`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    },
  );
  if (!response.ok) {
    clearTokens(storage);
    throw new Error(await errorDetail(response, "Сессия истекла — войдите снова"));
  }
  const body = (await response.json()) as { access_token: string };
  storage.setItem(ACCESS_TOKEN_KEY, body.access_token);
  return body.access_token;
}

export async function fetchWithSession(
  input: string,
  init: RequestInit = {},
  options: {
    accessToken?: string;
    apiBaseUrl?: string;
    storage?: TokenStorage | null;
    fetchImpl?: FetchImpl;
  } = {},
): Promise<Response> {
  const storage = options.storage ?? browserTokenStorage();
  const fetchImpl = options.fetchImpl ?? fetch;
  const apiBaseUrl =
    options.apiBaseUrl ?? (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

  const send = (token: string | null) =>
    fetchImpl(`${apiBaseUrl}${input}`, {
      ...init,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });

  const currentToken = storage?.getItem(ACCESS_TOKEN_KEY) ?? options.accessToken ?? null;
  const first = await send(currentToken);
  if (first.status !== 401 || !storage?.getItem(REFRESH_TOKEN_KEY)) return first;

  const refreshed = await refreshStoredAccessToken({ apiBaseUrl, storage, fetchImpl });
  return send(refreshed);
}
