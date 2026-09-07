import type {
  CreatedSession,
  CreateSessionInput,
  GroupWithStudents,
  QueueState,
  SessionStatus,
  SessionSummary,
  SessionUpdate,
} from "../types/teacher";
import { fetchWithSession } from "../auth/session";

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
  unfreezeSession(sessionId: string): Promise<{ id: string; frozen: boolean }>;
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

function stripQuery(path: string): string {
  return path.split("?", 1)[0];
}

function logApiError(action: string, path: string, status?: number): void {
  // Токены живут только в заголовках и теле — в путь без query они не попадают.
  console.error({ url: stripQuery(path), ...(status === undefined ? {} : { status }), action });
}

export function createTeacherApi(
  accessToken: string,
  apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "",
  fetchImpl: FetchImpl = fetch,
): TeacherApi {
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
    return (await response.json()) as T;
  }

  return {
    listSessions: () => request<SessionSummary[]>("teacher.listSessions", "/sessions/mine"),
    listGroups: () =>
      request<GroupWithStudents[]>("teacher.listGroups", "/groups?include_students=true"),
    createSession: (input) =>
      request<CreatedSession>("teacher.createSession", "/sessions", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    getQueue: (sessionId) =>
      request<QueueState>("teacher.getQueue", `/sessions/${sessionId}/queue`),
    updateSession: (sessionId, patch) =>
      request<SessionUpdate>("teacher.updateSession", `/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    freezeSession: (sessionId) =>
      request<{ id: string; frozen: boolean }>("teacher.freezeSession", `/sessions/${sessionId}/freeze`, {
        method: "POST",
      }),
    unfreezeSession: (sessionId) =>
      request<{ id: string; frozen: boolean }>("teacher.unfreezeSession", `/sessions/${sessionId}/unfreeze`, {
        method: "POST",
      }),
    finishEntry: (sessionId, entryId) =>
      request("teacher.finishEntry", `/sessions/${sessionId}/queue/${entryId}/done`, { method: "POST" }),
    skipEntry: (sessionId, entryId) =>
      request("teacher.skipEntry", `/sessions/${sessionId}/queue/${entryId}/skip`, { method: "POST" }),
    addParticipant: (sessionId, studentId) =>
      request("teacher.addParticipant", `/sessions/${sessionId}/participants`, {
        method: "POST",
        body: JSON.stringify({ student_id: studentId }),
      }),
    removeParticipant: (sessionId, entryId) =>
      request("teacher.removeParticipant", `/sessions/${sessionId}/participants/${entryId}`, {
        method: "DELETE",
      }),
  };
}
