import { describe, expect, it, vi } from "vitest";

import { createTeacherApi } from "./teacher";

function json(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("teacher API", () => {
  it("использует согласованные маршруты управления и авторизацию", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(() =>
      Promise.resolve(json({})),
    );
    const api = createTeacherApi("teacher-token", "https://api.example", fetchMock);

    await api.updateSession("session-1", { status: "active" });
    await api.freezeSession("session-1");
    await api.finishEntry("session-1", "entry-1");
    await api.skipEntry("session-1", "entry-2");
    await api.addParticipant("session-1", "student-1");
    await api.removeParticipant("session-1", "entry-3");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "https://api.example/sessions/session-1",
      "https://api.example/sessions/session-1/freeze",
      "https://api.example/sessions/session-1/queue/entry-1/done",
      "https://api.example/sessions/session-1/queue/entry-2/skip",
      "https://api.example/sessions/session-1/participants",
      "https://api.example/sessions/session-1/participants/entry-3",
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init?.method)).toEqual([
      "PATCH",
      "POST",
      "POST",
      "POST",
      "POST",
      "DELETE",
    ]);
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      Authorization: "Bearer teacher-token",
    });
  });

  it("создаёт сессию из групп и явных студентов без RSVP", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(json({}));
    const api = createTeacherApi("token", "", fetchMock);

    await api.createSession({
      course_name: "Алгоритмы",
      room: "Р-123",
      date: "2026-09-08",
      start_time: "10:00",
      duration_default: 15,
      capacity: 2,
      group_ids: ["group-1"],
      student_ids: ["student-1"],
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.group_ids).toEqual(["group-1"]);
    expect(body.student_ids).toEqual(["student-1"]);
    expect(Object.keys(body).some((key) => key.toLowerCase().includes("rsvp"))).toBe(false);
  });
});
