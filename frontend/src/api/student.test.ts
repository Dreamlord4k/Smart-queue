import { describe, expect, it, vi } from "vitest";

import { createStudentApi } from "./student";

function json(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("student API", () => {
  it("вызывает self-reorder, lock и absence с разными payload", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(json({})));
    const api = createStudentApi("student-token", "https://api.example", fetchImpl);

    await api.reorder("session-1", "own-entry", "target-entry", "before");
    await api.setLock("session-1", "own-entry", true, "После пары");
    await api.markAbsent("own-entry", "Экзамен");

    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example/sessions/session-1/queue/reorder",
      "https://api.example/sessions/session-1/queue/own-entry/lock",
      "https://api.example/students/me/queues/own-entry/absence",
    ]);
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1]?.body))).toEqual({
      entry_id: "own-entry",
      target_entry_id: "target-entry",
      placement: "before",
    });
    expect(JSON.parse(String(fetchImpl.mock.calls[1][1]?.body))).toEqual({
      locked: true,
      lock_reason: "После пары",
    });
    expect(JSON.parse(String(fetchImpl.mock.calls[2][1]?.body))).toEqual({
      absence_reason: "Экзамен",
    });
  });

  it("удаляет только текущий профиль через DELETE /auth/me", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
    const api = createStudentApi("student-token", "", fetchImpl);

    await api.deleteProfile();

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[0][0]).toBe("/auth/me");
    expect(fetchImpl.mock.calls[0][1]?.method).toBe("DELETE");
  });
});
