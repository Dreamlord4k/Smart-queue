import { useState, type FormEvent } from "react";

import "./Auth.css";

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

export interface LoginFieldErrors {
  email?: string;
  password?: string;
}

export function validateLoginInput(input: {
  email: string;
  password: string;
}): LoginFieldErrors {
  const errors: LoginFieldErrors = {};
  const email = input.email.trim();
  if (!email) {
    errors.email = "Введите email";
  } else if (!email.includes("@")) {
    errors.email = "В email не хватает @ — проверьте адрес";
  }
  if (!input.password) {
    errors.password = "Введите пароль";
  }
  return errors;
}

export function Login({ apiBaseUrl, onSuccess }: LoginProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const hints = validateLoginInput({ email, password });
    setFieldErrors(hints);
    if (Object.keys(hints).length > 0) {
      return;
    }
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
    <main className="auth-page">
      <div className="auth-card">
        <p className="auth-logo">Умная очередь</p>
        <h1 className="auth-title">Вход</h1>
        <p className="auth-subtitle">Очереди, время и уведомления — в одном месте</p>
        <form noValidate onSubmit={handleSubmit}>
          <label className="auth-field">
            <span className="auth-label">Email</span>
            <input
              className={fieldErrors.email ? "auth-input auth-input--invalid" : "auth-input"}
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? "login-email-hint" : undefined}
            />
            {fieldErrors.email && (
              <span id="login-email-hint" className="auth-hint">
                {fieldErrors.email}
              </span>
            )}
          </label>
          <label className="auth-field">
            <span className="auth-label">Пароль</span>
            <input
              className={fieldErrors.password ? "auth-input auth-input--invalid" : "auth-input"}
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={Boolean(fieldErrors.password)}
              aria-describedby={fieldErrors.password ? "login-password-hint" : undefined}
            />
            {fieldErrors.password && (
              <span id="login-password-hint" className="auth-hint">
                {fieldErrors.password}
              </span>
            )}
          </label>
          {error && (
            <p role="alert" className="auth-error">
              {error}
            </p>
          )}
          <button type="submit" disabled={pending} className="auth-submit">
            {pending ? "Входим…" : "Войти"}
          </button>
        </form>
      </div>
    </main>
  );
}
