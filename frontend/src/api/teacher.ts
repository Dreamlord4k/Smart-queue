import type {
  CreatedSession,
  CreateSessionInput,
  GroupWithStudents,
  QueueState,
  SessionStatus,
  SessionSummary,
  SessionUpdate,
} from "../types/teacher";

type FetchImpl = typeof fetch;

export interface TeacherApi {
  listSessions(): Promise<SessionSummary[]>;
  listGroups(): Promise<GroupWithStudents[]>;
  createSession(input: CreateSessionInput): Promise<CreatedSession>;
  getQueue(sessionId: string): Promise<QueueState>;
  updateSession(
    sessionId: string,
    patch: { status?: SessionStatus; duration_default?: number },
  ): Promise<SessionUpdate>;
  freezeSession(sessionId: string): Promise<{ id: string; frozen: boolean }>;
  finishEntry(sessionId: string, entryId: string): Promise<unknown>;
  skipEntry(sessionId: string, entryId: string): Promise<unknown>;
  addParticipant(sessionId: string, studentId: string): Promise<unknown>;
  removeParticipant(sessionId: string, entryId: string): Promise<unknown>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Возвращаем общий текст, если сервер прислал не JSON.
  }
  return `Ошибка запроса (${response.status})`;
}

export function createTeacherApi(
  accessToken: string,
  apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "",
  fetchImpl: FetchImpl = fetch,
): TeacherApi {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetchImpl(`${apiBaseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    return (await response.json()) as T;
  }

  return {
    listSessions: () => request<SessionSummary[]>("/sessions/mine"),
    listGroups: () =>
      request<GroupWithStudents[]>("/groups?include_students=true"),
    createSession: (input) =>
      request<CreatedSession>("/sessions", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    getQueue: (sessionId) =>
      request<QueueState>(`/sessions/${sessionId}/queue`),
    updateSession: (sessionId, patch) =>
      request<SessionUpdate>(`/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    freezeSession: (sessionId) =>
      request<{ id: string; frozen: boolean }>(`/sessions/${sessionId}/freeze`, {
        method: "POST",
      }),
    finishEntry: (sessionId, entryId) =>
      request(`/sessions/${sessionId}/queue/${entryId}/done`, { method: "POST" }),
    skipEntry: (sessionId, entryId) =>
      request(`/sessions/${sessionId}/queue/${entryId}/skip`, { method: "POST" }),
    addParticipant: (sessionId, studentId) =>
      request(`/sessions/${sessionId}/participants`, {
        method: "POST",
        body: JSON.stringify({ student_id: studentId }),
      }),
    removeParticipant: (sessionId, entryId) =>
      request(`/sessions/${sessionId}/participants/${entryId}`, {
        method: "DELETE",
      }),
  };
}
