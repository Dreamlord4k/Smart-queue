import { useState, type FormEvent } from "react";

import type { UserRole } from "./Login";
import "./Auth.css";

export interface RegisteredUser {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  group_id: string | null;
}

type FetchImpl = typeof fetch;

function resolveApiBaseUrl(explicit?: string): string {
  if (explicit !== undefined) {
    return explicit;
  }
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
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
  return "Не удалось зарегистрироваться";
}

export interface RegisterInput {
  email: string;
  fullName: string;
  password: string;
  role: UserRole;
  groupId?: string;
}

export async function registerUser(
  input: RegisterInput,
  options?: { apiBaseUrl?: string; fetchImpl?: FetchImpl },
): Promise<RegisteredUser> {
  const groupId = input.groupId?.trim() ? input.groupId.trim() : null;
  if (input.role === "student" && !groupId) {
    throw new Error("Для студента обязательна группа");
  }
  const apiBaseUrl = resolveApiBaseUrl(options?.apiBaseUrl);
  const fetchImpl = options?.fetchImpl ?? fetch;
  const response = await fetchImpl(`${apiBaseUrl}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: input.email.trim().toLowerCase(),
      full_name: input.fullName.trim(),
      password: input.password,
      role: input.role,
      ...(input.role === "student" ? { group_id: groupId } : {}),
    }),
  });
  if (!response.ok) {
    throw new Error(await readErrorDetail(response));
  }
  return (await response.json()) as RegisteredUser;
}

interface RegisterProps {
  apiBaseUrl?: string;
  onSuccess?: (user: RegisteredUser) => void;
}

export interface RegisterFieldErrors {
  email?: string;
  fullName?: string;
  password?: string;
  groupId?: string;
}

export function validateRegisterInput(input: RegisterInput): RegisterFieldErrors {
  const errors: RegisterFieldErrors = {};
  const email = input.email.trim();
  if (!email) {
    errors.email = "Введите email";
  } else if (!email.includes("@")) {
    errors.email = "В email не хватает @ — проверьте адрес";
  }
  if (!input.fullName.trim()) {
    errors.fullName = "Представьтесь — введите ФИО";
  }
  if (!input.password) {
    errors.password = "Придумайте пароль";
  } else if (input.password.length < 8) {
    errors.password = "Пароль короткий — минимум 8 символов";
  }
  if (input.role === "student" && !input.groupId?.trim()) {
    errors.groupId = "Укажите ID группы";
  }
  return errors;
}

export function Register({ apiBaseUrl, onSuccess }: RegisterProps) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("student");
  const [groupId, setGroupId] = useState("");
  const [fieldErrors, setFieldErrors] = useState<RegisterFieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const hints = validateRegisterInput({ email, fullName, password, role, groupId });
    setFieldErrors(hints);
    if (Object.keys(hints).length > 0) {
      return;
    }
    setPending(true);
    try {
      const user = await registerUser(
        { email, fullName, password, role, groupId },
        { apiBaseUrl },
      );
      if (onSuccess) {
        onSuccess(user);
      } else if (typeof window !== "undefined") {
        window.location.assign("/login");
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
        <h1 className="auth-title">Регистрация</h1>
        <p className="auth-subtitle">Минута — и вы в очереди на сдачу</p>
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
              aria-describedby={fieldErrors.email ? "register-email-hint" : undefined}
            />
            {fieldErrors.email && (
              <span id="register-email-hint" className="auth-hint">
                {fieldErrors.email}
              </span>
            )}
          </label>
          <label className="auth-field">
            <span className="auth-label">ФИО</span>
            <input
              className={fieldErrors.fullName ? "auth-input auth-input--invalid" : "auth-input"}
              type="text"
              name="full_name"
              autoComplete="name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              aria-invalid={Boolean(fieldErrors.fullName)}
              aria-describedby={fieldErrors.fullName ? "register-name-hint" : undefined}
            />
            {fieldErrors.fullName && (
              <span id="register-name-hint" className="auth-hint">
                {fieldErrors.fullName}
              </span>
            )}
          </label>
          <label className="auth-field">
            <span className="auth-label">Пароль (минимум 8 символов)</span>
            <input
              className={fieldErrors.password ? "auth-input auth-input--invalid" : "auth-input"}
              type="password"
              name="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={Boolean(fieldErrors.password)}
              aria-describedby={fieldErrors.password ? "register-password-hint" : undefined}
            />
            {fieldErrors.password && (
              <span id="register-password-hint" className="auth-hint">
                {fieldErrors.password}
              </span>
            )}
          </label>
          <label className="auth-field">
            <span className="auth-label">Роль</span>
            <select
              className="auth-select"
              name="role"
              value={role}
              onChange={(event) => setRole(event.target.value as UserRole)}
            >
              <option value="student">Студент</option>
              <option value="teacher">Преподаватель</option>
            </select>
          </label>
          {role === "student" && (
            <label className="auth-field">
              <span className="auth-label">ID группы (UUID)</span>
              <input
                className={fieldErrors.groupId ? "auth-input auth-input--invalid" : "auth-input"}
                type="text"
                name="group_id"
                placeholder="UUID группы"
                value={groupId}
                onChange={(event) => setGroupId(event.target.value)}
                aria-invalid={Boolean(fieldErrors.groupId)}
                aria-describedby={fieldErrors.groupId ? "register-group-hint" : undefined}
              />
              {fieldErrors.groupId && (
                <span id="register-group-hint" className="auth-hint">
                  {fieldErrors.groupId}
                </span>
              )}
            </label>
          )}
          {error && (
            <p role="alert" className="auth-error">
              {error}
            </p>
          )}
          <button type="submit" disabled={pending} className="auth-submit">
            {pending ? "Регистрируем…" : "Зарегистрироваться"}
          </button>
        </form>
      </div>
    </main>
  );
}
