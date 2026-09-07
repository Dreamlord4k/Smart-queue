import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MyQueueCard, MyQueues } from "./MyQueues";

const queues: MyQueueCard[] = [
  {
    entry_id: "entry-1",
    session_id: "session-1",
    course_name: "Алгоритмы",
    teacher_name: "Анна Петрова",
    room: "Р-123",
    date: "2026-09-08",
    start_time: "10:00:00",
    position: 2,
    eta_start: "2026-09-08T10:15:00Z",
    eta_end: "2026-09-08T10:30:00Z",
    status: "waiting",
  },
  {
    entry_id: "entry-2",
    session_id: "session-2",
    course_name: "Базы данных",
    teacher_name: "Иван Сидоров",
    room: "Р-221",
    date: "2026-09-08",
    start_time: "10:20:00",
    position: 1,
    eta_start: "2026-09-08T10:20:00Z",
    eta_end: "2026-09-08T10:35:00Z",
    status: "called",
  },
];

describe("MyQueues", () => {
  it("показывает независимые карточки сессий одного дня и предупреждает о пересечении", () => {
    const html = renderToStaticMarkup(<MyQueues initialQueues={queues} />);

    expect(html).toContain("Алгоритмы");
    expect(html).toContain("Позиция: 2");
    expect(html).toContain("Ожидает");
    expect(html).toContain("Базы данных");
    expect(html).toContain("Позиция: 1");
    expect(html).toContain("Вас вызывают");
    expect(html.match(/Возможное пересечение/g)).toHaveLength(2);
    expect(html).toContain("Примерно:");
    expect(html).not.toContain("ETA:");
  });

  it("карточки и кнопка используют классы единой темы", () => {
    const html = renderToStaticMarkup(<MyQueues initialQueues={queues} />);

    expect(html).toContain("mq-page");
    expect(html).toContain("mq-grid");
    expect(html.match(/mq-card/g)).toHaveLength(2);
    expect(html).toContain("mq-button");
    expect(html).not.toContain("style=");
  });
});
