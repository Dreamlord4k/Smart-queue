import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SessionForm } from "../components/teacher/SessionForm";
import type { GroupWithStudents, SessionSummary } from "../types/teacher";
import { splitSessions, TeacherDashboard } from "./TeacherDashboard";

const baseSession: SessionSummary = {
  id: "session-1",
  teacher_id: "teacher-1",
  course_name: "Алгоритмы",
  room: "Р-123",
  date: "2026-09-08",
  start_time: "10:00:00",
  duration_default: 15,
  capacity: 2,
  status: "planned",
  frozen: false,
  created_at: "2026-09-06T10:00:00Z",
};

const groups: GroupWithStudents[] = [
  {
    id: "group-1",
    name: "ИРИТ-РТФ-301",
    students: [
      { id: "student-1", full_name: "Анна Иванова", email: "anna@example.com" },
    ],
  },
];

describe("TeacherDashboard", () => {
  it("разделяет предстоящие, активные и завершённые сессии", () => {
    const sessions: SessionSummary[] = [
      baseSession,
      { ...baseSession, id: "session-2", course_name: "Базы данных", status: "active" },
      { ...baseSession, id: "session-3", course_name: "Сети", status: "closed" },
    ];
    const html = renderToStaticMarkup(
      <TeacherDashboard
        accessToken="token"
        initialSessions={sessions}
        initialGroups={groups}
      />,
    );

    expect(html).toContain("Предстоящие");
    expect(html).toContain("Идут сейчас");
    expect(html).toContain("Завершённые");
    expect(splitSessions(sessions).active[0].course_name).toBe("Базы данных");
    expect(html).toContain("Алгоритмы");
    expect(html).toContain("Сети");
    expect(html).toContain("Настройки");
  });

  it("форма предлагает группы и отдельных студентов без RSVP", () => {
    const html = renderToStaticMarkup(
      <SessionForm groups={groups} onCreate={() => undefined} />,
    );

    expect(html).toContain("Добавить группы целиком");
    expect(html).toContain("Или выбрать отдельных студентов");
    expect(html).toContain("Анна Иванова");
    expect(html.toLowerCase()).not.toContain("rsvp");
  });
});
