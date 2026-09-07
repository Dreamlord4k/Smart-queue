import { useCallback, useEffect, useMemo, useState } from "react";

import "../theme.css";
import {
  formatUniversitySessionStart,
  formatUniversityTime,
  UNIVERSITY_TIME_NOTE,
} from "../utils/time";

export type QueueStatus = "waiting" | "called" | "done" | "skipped" | "absent";

export interface MyQueueCard {
  entry_id: string;
  session_id: string;
  course_name: string;
  teacher_name: string;
  room: string;
  date: string;
  start_time: string;
  position: number | null;
  eta_start: string | null;
  eta_end: string | null;
  status: QueueStatus;
}

interface MyQueuesProps {
  accessToken?: string;
  apiBaseUrl?: string;
  initialQueues?: MyQueueCard[];
  onOpenQueue?: (sessionId: string) => void;
}

const statusLabels: Record<QueueStatus, string> = {
  waiting: "Ожидает",
  called: "Вас вызывают",
  done: "Завершено",
  skipped: "Пропущено",
  absent: "Не участвую",
};

function overlappingEntries(queues: MyQueueCard[]): Set<string> {
  const overlaps = new Set<string>();
  for (let left = 0; left < queues.length; left += 1) {
    for (let right = left + 1; right < queues.length; right += 1) {
      const first = queues[left];
      const second = queues[right];
      if (
        first.date !== second.date ||
        !first.eta_start ||
        !first.eta_end ||
        !second.eta_start ||
        !second.eta_end
      ) {
        continue;
      }
      if (
        new Date(first.eta_start) < new Date(second.eta_end) &&
        new Date(second.eta_start) < new Date(first.eta_end)
      ) {
        overlaps.add(first.entry_id);
        overlaps.add(second.entry_id);
      }
    }
  }
  return overlaps;
}

function formatEta(card: MyQueueCard): string {
  if (!card.eta_start || !card.eta_end) {
    return "Не рассчитывается";
  }
  return `${formatUniversityTime(card.eta_start)}–${formatUniversityTime(card.eta_end)}`;
}

export function MyQueues({
  accessToken,
  apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "",
  initialQueues,
  onOpenQueue,
}: MyQueuesProps) {
  const [queues, setQueues] = useState<MyQueueCard[]>(initialQueues ?? []);
  const [loading, setLoading] = useState(initialQueues === undefined);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (initialQueues !== undefined) return;
    if (!accessToken) {
      setError("Войдите, чтобы увидеть свои очереди");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/students/me/queues`, {
        headers: { Authorization: `Bearer ${accessToken}` },
        signal,
      });
      if (!response.ok) {
        throw new Error("Не удалось загрузить очереди");
      }
      setQueues((await response.json()) as MyQueueCard[]);
    } catch (reason: unknown) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason.message : "Неизвестная ошибка");
      }
    } finally {
      setLoading(false);
    }
  }, [accessToken, apiBaseUrl, initialQueues]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const overlaps = useMemo(() => overlappingEntries(queues), [queues]);

  return (
    <main className="mq-page">
      <h1>Мои очереди</h1>
      {loading && <p>Загружаем очереди…</p>}
      {error && (
        <p role="alert" className="mq-error">
          {error}
          <button type="button" className="mq-retry" onClick={() => void load()}>
            Попробовать снова
          </button>
        </p>
      )}
      {!loading && !error && queues.length === 0 && <p>Активных и предстоящих очередей нет.</p>}
      <section aria-label="Активные и предстоящие очереди" className="mq-grid">
        {queues.map((card) => (
          <article key={card.entry_id} data-testid={`queue-${card.entry_id}`} className="mq-card anim-rise">
            <h2>{card.course_name}</h2>
            <p>{card.teacher_name}, аудитория {card.room}</p>
            <p>{formatUniversitySessionStart(card.date, card.start_time)} ({UNIVERSITY_TIME_NOTE})</p>
            <p>Позиция: {card.position ?? "—"}</p>
            <p>ETA: {formatEta(card)} ({UNIVERSITY_TIME_NOTE})</p>
            <p>Статус: {statusLabels[card.status]}</p>
            {overlaps.has(card.entry_id) && (
              <p role="status" className="mq-warn">
                Возможное пересечение с другой очередью этого дня
              </p>
            )}
            <button type="button" onClick={() => onOpenQueue?.(card.session_id)} className="mq-button">
              Открыть очередь
            </button>
          </article>
        ))}
      </section>
    </main>
  );
}
