import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { QueueState, SessionReport, SessionSummary } from "../types/teacher";
import { TeacherSession } from "./TeacherSession";

const session: SessionSummary = {
  id: "session-1",
  teacher_id: "teacher-1",
  course_name: "Алгоритмы",
  room: "Р-123",
  date: "2026-09-08",
  start_time: "10:00:00",
  duration_default: 15,
  capacity: 2,
  status: "active",
  frozen: true,
  created_at: "2026-09-06T10:00:00Z",
};

const queue: QueueState = {
  session_id: session.id,
  entries: [
    {
      id: "entry-called",
      student_id: "student-1",
      student_name: "Анна Иванова",
      position: 1,
      status: "called",
      channel: 1,
      locked: false,
      lock_reason: null,
      absence_reason: null,
      eta_start: null,
      eta_end: null,
    },
    {
      id: "entry-waiting",
      student_id: "student-2",
      student_name: "Борис Сидоров",
      position: 2,
      status: "waiting",
      channel: null,
      locked: true,
      lock_reason: "Договорился о времени",
      absence_reason: null,
      eta_start: "2026-09-08T10:15:00Z",
      eta_end: "2026-09-08T10:20:00Z",
    },
    {
      id: "entry-absent",
      student_id: "student-3",
      student_name: "Вера Петрова",
      position: 3,
      status: "absent",
      channel: null,
      locked: false,
      lock_reason: null,
      absence_reason: "Другая встреча",
      eta_start: null,
      eta_end: null,
    },
  ],
};

describe("TeacherSession", () => {
  it("показывает каналы, очередь, причины и действия без drag-and-drop", () => {
    const html = renderToStaticMarkup(
      <TeacherSession accessToken="token" session={session} initialQueue={queue} />,
    );

    expect(html).toContain("Канал 1");
    expect(html).toContain("Канал 2");
    expect(html).toContain("Анна Иванова");
    expect(html).toContain("Готово");
    expect(html).toContain("Пропустить");
    expect(html).toContain("teacher-channel-actions");
    expect(html).toContain("Причина фиксации: Договорился о времени");
    expect(html).toContain("Причина отказа: Другая встреча");
    expect(html).toContain("Добавить участника");
    expect(html.toLowerCase()).not.toContain("drag");
  });

  it("после закрытия показывает полный итоговый отчёт", () => {
    const report: SessionReport = {
      accepted_count: 7,
      skipped_count: 2,
      average_service_seconds: 720,
      planned_duration_seconds: 3600,
      actual_duration_seconds: 4020,
      average_eta_error_seconds: 180,
    };
    const html = renderToStaticMarkup(
      <TeacherSession
        accessToken="token"
        session={{ ...session, status: "closed" }}
        initialQueue={queue}
        initialReport={report}
      />,
    );

    expect(html).toContain("Итоговый отчёт");
    expect(html).toContain("Принято");
    expect(html).toContain(">7<");
    expect(html).toContain("Пропущено");
    expect(html).toContain("Плановое время");
    expect(html).toContain("Фактическое время");
    expect(html).toContain("Средняя ошибка ETA");
  });
});
