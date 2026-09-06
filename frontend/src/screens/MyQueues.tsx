import { useEffect, useMemo, useState } from "react";

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
  const options: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
  };
  return `${new Date(card.eta_start).toLocaleTimeString("ru-RU", options)}–${new Date(
    card.eta_end,
  ).toLocaleTimeString("ru-RU", options)}`;
}

export function MyQueues({
  accessToken,
  apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  initialQueues,
  onOpenQueue,
}: MyQueuesProps) {
  const [queues, setQueues] = useState<MyQueueCard[]>(initialQueues ?? []);
  const [loading, setLoading] = useState(initialQueues === undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialQueues !== undefined) {
      return;
    }
    if (!accessToken) {
      setError("Войдите, чтобы увидеть свои очереди");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    fetch(`${apiBaseUrl}/students/me/queues`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Не удалось загрузить очереди");
        }
        return (await response.json()) as MyQueueCard[];
      })
      .then(setQueues)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason.message : "Неизвестная ошибка");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [accessToken, apiBaseUrl, initialQueues]);

  const overlaps = useMemo(() => overlappingEntries(queues), [queues]);

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: 24, fontFamily: "sans-serif" }}>
      <h1>Мои очереди</h1>
      {loading && <p>Загружаем очереди…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && queues.length === 0 && <p>Активных и предстоящих очередей нет.</p>}
      <section aria-label="Активные и предстоящие очереди" style={{ display: "grid", gap: 16 }}>
        {queues.map((card) => (
          <article
            key={card.entry_id}
            data-testid={`queue-${card.entry_id}`}
            style={{ border: "1px solid #d7dce2", borderRadius: 12, padding: 18 }}
          >
            <h2>{card.course_name}</h2>
            <p>{card.teacher_name} · аудитория {card.room}</p>
            <p>{card.date} в {card.start_time.slice(0, 5)}</p>
            <p>Позиция: {card.position ?? "—"}</p>
            <p>ETA: {formatEta(card)}</p>
            <p>Статус: {statusLabels[card.status]}</p>
            {overlaps.has(card.entry_id) && (
              <p role="status">Возможное пересечение с другой очередью этого дня</p>
            )}
            <button type="button" onClick={() => onOpenQueue?.(card.session_id)}>
              Открыть очередь
            </button>
          </article>
        ))}
      </section>
    </main>
  );
}
