import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { StudentQueueEntry, StudentQueueState } from "../types/student";
import {
  canDragEntry,
  dragAutoScrollDelta,
  LockReasonDrawer,
  moveOwnEntry,
  placementForDrop,
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

  it("выбирает сторону вставки по направлению движения", () => {
    const fifth = { ...entries[1], id: "fifth", position: 5 };
    const third = { ...entries[0], id: "third", position: 3 };

    expect(placementForDrop(fifth, third)).toBe("before");
    expect(placementForDrop(third, fifth)).toBe("after");
  });

  it("делает вставку через locked-якорь, не сдвигая его позицию", () => {
    const anchored = Array.from({ length: 5 }, (_, index) => ({
      ...entries[0],
      id: `entry-${index + 1}`,
      student_id: `student-${index + 1}`,
      student_name: `Студент ${index + 1}`,
      position: index + 1,
      locked: index === 3,
    }));

    const result = moveOwnEntry(anchored, "entry-5", "entry-3", "before");

    expect(result.map((entry) => entry.id)).toEqual([
      "entry-1",
      "entry-2",
      "entry-5",
      "entry-4",
      "entry-3",
    ]);
    expect(result[3]).toMatchObject({ id: "entry-4", locked: true, position: 4 });
    expect(new Set(result.map((entry) => entry.id)).size).toBe(5);
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
    expect(states.at(-1)).toEqual(queue);
    expect(states.at(-1)?.entries.map((entry) => entry.id)).toEqual([
      "foreign-entry",
      "own-entry",
    ]);
    expect(new Set(states.at(-1)?.entries.map((entry) => entry.id)).size).toBe(2);
  });

  it("ускоряет прокрутку только рядом с краями мобильного viewport", () => {
    expect(dragAutoScrollDelta(12, 375)).toBeLessThan(0);
    expect(dragAutoScrollDelta(190, 375)).toBe(0);
    expect(dragAutoScrollDelta(360, 375)).toBeGreaterThan(0);
  });

  it("показывает фиксацию и отказ как независимые действия", () => {
    const html = renderToStaticMarkup(
      <Queue accessToken={token("student-2")} sessionId="session-1" initialQueue={queue} />,
    );

    expect(html).toContain("В начало");
    expect(html).not.toContain("Например, пересечение с другой парой");
    expect(html).toContain("Причина отказа — необязательно");
    expect(html).toContain("Сохранить фиксацию");
    expect(html).toContain("Отказаться от этой сессии");
  });

  it("показывает причину фиксации во внепоточном боковом диалоге", () => {    const html = renderToStaticMarkup(
      <LockReasonDrawer
        open
        reason="После пары"
        pending={false}
        onReasonChange={vi.fn()}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(html).toContain('role="dialog"');
    expect(html).toContain('class="student-lock-drawer"');
    expect(html).toContain("После пары");
  });
});

const studentCssPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "components",
  "student",
  "Student.css",
);

describe("видимость кнопок быстрого перемещения", () => {
  it("на десктопе кнопки скрыты CSS, drag у своей записи есть", () => {
    const css = readFileSync(studentCssPath, "utf8");
    const baseBlock = css.match(/\.student-reorder-controls\s*\{[^}]*\}/);

    expect(baseBlock?.[0]).toMatch(/display:\s*none/);

    const html = renderToStaticMarkup(
      <Queue accessToken={token("student-2")} sessionId="session-1" initialQueue={queue} />,
    );
    expect(html).toContain("В начало");
    expect(html.match(/draggable="true"/g)).toHaveLength(1);
  });

  it("кнопки включаются только на узких тач-экранах", () => {
    const css = readFileSync(studentCssPath, "utf8");

    expect(css).toMatch(
      /@media\s*\(max-width:\s*640px\)\s*and\s*\(pointer:\s*coarse\)[\s\S]*?\.student-reorder-controls\s*\{[^}]*display:\s*flex/,
    );
  });
});
