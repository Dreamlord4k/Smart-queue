import { useState, type FormEvent } from "react";

export type UserRole = "student" | "teacher";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface TokenStorage {
  setItem(key: string, value: string): void;
  getItem(key: string): string | null;
  removeItem(key: string): void;
}

type FetchImpl = typeof fetch;

function resolveApiBaseUrl(explicit?: string): string {
  if (explicit !== undefined) {
    return explicit;
  }
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
}

function defaultStorage(): TokenStorage | null {
  if (typeof window !== "undefined" && window.localStorage) {
    return window.localStorage;
  }
  return null;
}

export function decodeRoleFromToken(token: string): UserRole | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) {
      return null;
    }
    const decoded = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/")),
    ) as { role?: unknown };
    return decoded.role === "student" || decoded.role === "teacher"
      ? decoded.role
      : null;
  } catch {
    return null;
  }
}

export function saveTokens(storage: TokenStorage, pair: TokenPair): void {
  storage.setItem("access_token", pair.access_token);
  storage.setItem("refresh_token", pair.refresh_token);
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string" && data.detail) {
      return data.detail;
    }
  } catch {
    // Игнорируем ошибку разбора — вернём текст по умолчанию.
  }
  return "Не удалось войти";
}

export async function loginUser(
  input: { email: string; password: string },
  options?: { apiBaseUrl?: string; fetchImpl?: FetchImpl },
): Promise<TokenPair> {
  const apiBaseUrl = resolveApiBaseUrl(options?.apiBaseUrl);
  const fetchImpl = options?.fetchImpl ?? fetch;
  const response = await fetchImpl(`${apiBaseUrl}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: input.email.trim().toLowerCase(),
      password: input.password,
    }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }
  return (await response.json()) as TokenPair;
}

interface LoginProps {
  apiBaseUrl?: string;
  onSuccess?: (role: UserRole) => void;
}

export function Login({ apiBaseUrl, onSuccess }: LoginProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const pair = await loginUser({ email, password }, { apiBaseUrl });
      const storage = defaultStorage();
      if (storage) {
        saveTokens(storage, pair);
      }
      const role = decodeRoleFromToken(pair.access_token) ?? "student";
      if (onSuccess) {
        onSuccess(role);
      } else if (typeof window !== "undefined") {
        window.location.assign(role === "teacher" ? "/teacher" : "/queues");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Неизвестная ошибка");
    } finally {
      setPending(false);
    }
  }

  return (
    <main
      style={{ maxWidth: 480, margin: "0 auto", padding: 24, fontFamily: "sans-serif" }}
    >
      <h1>Вход</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            name="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={pending}>
          {pending ? "Входим…" : "Войти"}
        </button>
      </form>
    </main>
  );
}
