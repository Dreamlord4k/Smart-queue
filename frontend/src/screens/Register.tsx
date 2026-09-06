import { useState, type FormEvent } from "react";

import type { UserRole } from "./Login";

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

export function Register({ apiBaseUrl, onSuccess }: RegisterProps) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("student");
  const [groupId, setGroupId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
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
    <main
      style={{ maxWidth: 480, margin: "0 auto", padding: 24, fontFamily: "sans-serif" }}
    >
      <h1>Регистрация</h1>
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
          ФИО
          <input
            type="text"
            name="full_name"
            autoComplete="name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            required
          />
        </label>
        <label>
          Пароль (минимум 8 символов)
          <input
            type="password"
            name="password"
            autoComplete="new-password"
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <label>
          Роль
          <select
            name="role"
            value={role}
            onChange={(event) => setRole(event.target.value as UserRole)}
          >
            <option value="student">Студент</option>
            <option value="teacher">Преподаватель</option>
          </select>
        </label>
        {role === "student" && (
          <label>
            ID группы (UUID)
            <input
              type="text"
              name="group_id"
              placeholder="UUID группы"
              value={groupId}
              onChange={(event) => setGroupId(event.target.value)}
              required
            />
          </label>
        )}
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={pending}>
          {pending ? "Регистрируем…" : "Зарегистрироваться"}
        </button>
      </form>
    </main>
  );
}
