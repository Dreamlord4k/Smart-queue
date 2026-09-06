import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { StudentQueueEntry, StudentQueueState } from "../types/student";
import {
  canDragEntry,
  moveOwnEntry,
  Queue,
  reorderWithRollback,
} from "./Queue";

function token(subject: string): string {
  const payload = btoa(JSON.stringify({ sub: subject, role: "student" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `header.${payload}.signature`;
}

const entries: StudentQueueEntry[] = [
  {
    id: "foreign-entry",
    student_id: "student-1",
    student_name: "Алексей Смирнов",
    position: 1,
    status: "waiting",
    channel: null,
    locked: false,
    lock_reason: null,
    absence_reason: null,
    eta_start: "2026-09-08T10:00:00Z",
    eta_end: "2026-09-08T10:15:00Z",
  },
  {
    id: "own-entry",
    student_id: "student-2",
    student_name: "Алексей Смирнов",
    position: 2,
    status: "waiting",
    channel: null,
    locked: false,
    lock_reason: null,
    absence_reason: null,
    eta_start: "2026-09-08T10:15:00Z",
    eta_end: "2026-09-08T10:30:00Z",
  },
];

const queue: StudentQueueState = {
  session_id: "session-1",
  frozen: false,
  entries,
};

describe("Queue", () => {
  it("не смешивает одноимённые аккаунты и делает draggable только свою запись", () => {
    const html = renderToStaticMarkup(
      <Queue accessToken={token("student-2")} sessionId="session-1" initialQueue={queue} />,
    );

    expect(html.match(/Алексей Смирнов/g)).toHaveLength(3);
    expect(html.match(/draggable="true"/g)).toHaveLength(1);
    expect(canDragEntry(entries[0], "student-2", false)).toBe(false);
    expect(canDragEntry(entries[1], "student-2", false)).toBe(true);
    expect(canDragEntry(entries[1], "student-2", true)).toBe(false);
  });

  it("перемещает только source-запись относительно цели", () => {
    const result = moveOwnEntry(entries, "own-entry", "foreign-entry", "before");

    expect(result.slice(0, 2).map((entry) => entry.id)).toEqual([
      "own-entry",
      "foreign-entry",
    ]);
    expect(result.slice(0, 2).map((entry) => entry.position)).toEqual([1, 2]);
  });

  it("откатывает оптимистичный порядок после отказа сервера", async () => {
    const states: StudentQueueState[] = [];

    await expect(
      reorderWithRollback({
        queue,
        sourceId: "own-entry",
        targetId: "foreign-entry",
        placement: "before",
        setQueue: (state) => states.push(state),
        reorder: vi.fn().mockRejectedValue(new Error("Целевое место зафиксировано")),
        reload: vi.fn(),
      }),
    ).rejects.toThrow("Целевое место зафиксировано");

    expect(states[0].entries[0].id).toBe("own-entry");
    expect(states.at(-1)).toBe(queue);
  });

  it("показывает фиксацию и отказ как независимые действия", () => {
    const html = renderToStaticMarkup(
      <Queue accessToken={token("student-2")} sessionId="session-1" initialQueue={queue} />,
    );

    expect(html).toContain("Причина фиксации — необязательно");
    expect(html).toContain("Причина отказа — необязательно");
    expect(html).toContain("Сохранить фиксацию");
    expect(html).toContain("Отказаться от этой сессии");
  });
});
