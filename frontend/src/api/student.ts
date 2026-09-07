import { clearTokens, fetchWithSession, browserTokenStorage } from "../auth/session";
import type {
  AbsenceResult,
  LockResult,
  QueuePlacement,
  StudentQueueState,
} from "../types/student";

type FetchImpl = typeof fetch;

export interface TelegramLinkState {
  linked: boolean;
  code: string | null;
  expires_at: string | null;
  deep_link: string | null;
}

export interface StudentApi {
  getQueue(sessionId: string): Promise<StudentQueueState>;
  reorder(
    sessionId: string,
    entryId: string,
    targetEntryId: string,
    placement: QueuePlacement,
  ): Promise<void>;
  setLock(
    sessionId: string,
    entryId: string,
    locked: boolean,
    lockReason?: string,
  ): Promise<LockResult>;
  markAbsent(entryId: string, absenceReason?: string): Promise<AbsenceResult>;
  initTelegramLink(): Promise<TelegramLinkState>;
  deleteProfile(): Promise<void>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Сервер мог вернуть ответ без JSON.
  }
  return `Ошибка запроса (${response.status})`;
}

export function createStudentApi(
  accessToken: string,
  apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "",
  fetchImpl: FetchImpl = fetch,
): StudentApi {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetchWithSession(path, {
      ...init,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    }, { accessToken, apiBaseUrl, fetchImpl });
    if (!response.ok) throw new Error(await errorMessage(response));
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    getQueue: (sessionId) => request(`/sessions/${sessionId}/queue`),
    reorder: async (sessionId, entryId, targetEntryId, placement) => {
      await request(`/sessions/${sessionId}/queue/reorder`, {
        method: "PATCH",
        body: JSON.stringify({
          entry_id: entryId,
          target_entry_id: targetEntryId,
          placement,
        }),
      });
    },
    setLock: (sessionId, entryId, locked, lockReason) =>
      request(`/sessions/${sessionId}/queue/${entryId}/lock`, {
        method: "PATCH",
        body: JSON.stringify({
          locked,
          ...(locked ? { lock_reason: lockReason?.trim() || null } : {}),
        }),
      }),
    markAbsent: (entryId, absenceReason) =>
      request(`/students/me/queues/${entryId}/absence`, {
        method: "POST",
        body: JSON.stringify({ absence_reason: absenceReason?.trim() || null }),
      }),
    initTelegramLink: () =>
      request("/telegram/link/init", { method: "POST" }),
    deleteProfile: async () => {
      await request("/auth/me", { method: "DELETE" });
      const storage = browserTokenStorage();
      if (storage) clearTokens(storage);
    },
  };
}
