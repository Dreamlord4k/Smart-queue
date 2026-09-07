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

function stripQuery(path: string): string {
  return path.split("?", 1)[0];
}

function logApiError(action: string, path: string, status?: number): void {
  // Токены живут только в заголовках и теле — в путь без query они не попадают.
  console.error({ url: stripQuery(path), ...(status === undefined ? {} : { status }), action });
}

export function createStudentApi(
  accessToken: string,
  apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "",
  fetchImpl: FetchImpl = fetch,
): StudentApi {
  async function request<T>(action: string, path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetchWithSession(path, {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...init.headers,
        },
      }, { accessToken, apiBaseUrl, fetchImpl });
    } catch (networkError) {
      logApiError(action, path);
      throw networkError;
    }
    if (!response.ok) {
      logApiError(action, path, response.status);
      throw new Error(await errorMessage(response));
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    getQueue: (sessionId) => request("student.getQueue", `/sessions/${sessionId}/queue`),
    reorder: async (sessionId, entryId, targetEntryId, placement) => {
      await request("student.reorder", `/sessions/${sessionId}/queue/reorder`, {
        method: "PATCH",
        body: JSON.stringify({
          entry_id: entryId,
          target_entry_id: targetEntryId,
          placement,
        }),
      });
    },
    setLock: (sessionId, entryId, locked, lockReason) =>
      request("student.setLock", `/sessions/${sessionId}/queue/${entryId}/lock`, {
        method: "PATCH",
        body: JSON.stringify({
          locked,
          ...(locked ? { lock_reason: lockReason?.trim() || null } : {}),
        }),
      }),
    markAbsent: (entryId, absenceReason) =>
      request("student.markAbsent", `/students/me/queues/${entryId}/absence`, {
        method: "POST",
        body: JSON.stringify({ absence_reason: absenceReason?.trim() || null }),
      }),
    initTelegramLink: () =>
      request("student.initTelegramLink", "/telegram/link/init", { method: "POST" }),
    deleteProfile: async () => {
      await request("student.deleteProfile", "/auth/me", { method: "DELETE" });
      const storage = browserTokenStorage();
      if (storage) clearTokens(storage);
    },
  };
}
