import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";

import { createStudentApi, type StudentApi } from "../api/student";
import { decodeSubjectFromToken } from "../auth/session";
import "../components/student/Student.css";
import { useQueueSocket } from "../hooks/useQueueSocket";
import type {
  QueuePlacement,
  StudentQueueEntry,
  StudentQueueState,
} from "../types/student";

interface QueueProps {
  accessToken: string;
  sessionId: string;
  apiBaseUrl?: string;
  api?: StudentApi;
  initialQueue?: StudentQueueState;
  onBack?: () => void;
  onSettings?: () => void;
}

const statusLabels: Record<StudentQueueEntry["status"], string> = {
  waiting: "Ожидает",
  called: "Вас вызывают",
  done: "Завершено",
  skipped: "Пропущено",
  absent: "Не участвую",
};

export function canDragEntry(
  entry: StudentQueueEntry,
  currentStudentId: string | null,
  frozen: boolean,
): boolean {
  return (
    entry.student_id === currentStudentId &&
    entry.status === "waiting" &&
    !entry.locked &&
    !frozen
  );
}

export function moveOwnEntry(
  entries: StudentQueueEntry[],
  sourceId: string,
  targetId: string,
  placement: QueuePlacement,
): StudentQueueEntry[] {
  const active = entries
    .filter((entry) => entry.status === "waiting" || entry.status === "called")
    .sort((left, right) => left.position - right.position);
  const source = active.find((entry) => entry.id === sourceId);
  const target = active.find((entry) => entry.id === targetId);
  if (!source || !target || source.id === target.id) return entries;

  const reordered = active.filter((entry) => entry.id !== source.id);
  const targetIndex = reordered.findIndex((entry) => entry.id === target.id);
  reordered.splice(targetIndex + (placement === "after" ? 1 : 0), 0, source);
  const normalized = reordered.map((entry, index) => ({ ...entry, position: index + 1 }));
  const history = entries.filter(
    (entry) => entry.status !== "waiting" && entry.status !== "called",
  );
  return [...normalized, ...history];
}

export async function reorderWithRollback(options: {
  queue: StudentQueueState;
  sourceId: string;
  targetId: string;
  placement: QueuePlacement;
  setQueue: (queue: StudentQueueState) => void;
  reorder: () => Promise<void>;
  reload: () => Promise<StudentQueueState>;
}): Promise<void> {
  options.setQueue({
    ...options.queue,
    entries: moveOwnEntry(
      options.queue.entries,
      options.sourceId,
      options.targetId,
      options.placement,
    ),
  });
  try {
    await options.reorder();
    options.setQueue(await options.reload());
  } catch (reason) {
    options.setQueue(options.queue);
    throw reason;
  }
}

function etaLabel(entry: StudentQueueEntry): string {
  if (!entry.eta_start || !entry.eta_end) return "ETA не рассчитан";
  const format = (value: string) =>
    new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `ETA ${format(entry.eta_start)}–${format(entry.eta_end)}`;
}

export function Queue({
  accessToken,
  sessionId,
  apiBaseUrl,
  api: suppliedApi,
  initialQueue,
  onBack,
  onSettings,
}: QueueProps) {
  const api = useMemo(
    () => suppliedApi ?? createStudentApi(accessToken, apiBaseUrl),
    [accessToken, apiBaseUrl, suppliedApi],
  );
  const currentStudentId = decodeSubjectFromToken(accessToken);
  const [queue, setQueue] = useState<StudentQueueState | null>(initialQueue ?? null);
  const [draggingEntryId, setDraggingEntryId] = useState<string | null>(null);
  const [lockEnabled, setLockEnabled] = useState(false);
  const [lockReason, setLockReason] = useState("");
  const [absenceReason, setAbsenceReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    setQueue(await api.getQueue(sessionId));
  }, [api, sessionId]);

  useEffect(() => {
    if (initialQueue) return;
    loadQueue().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить очередь"),
    );
  }, [initialQueue, loadQueue]);

  useQueueSocket({
    sessionId,
    accessToken,
    apiBaseUrl,
    onUpdate: loadQueue,
  });

  const entries = queue?.entries ?? [];
  const ownEntry = entries.find((entry) => entry.student_id === currentStudentId) ?? null;
  const activeEntries = entries.filter(
    (entry) => entry.status === "waiting" || entry.status === "called",
  );
  const ownIndex = ownEntry
    ? activeEntries.findIndex((entry) => entry.id === ownEntry.id)
    : -1;

  useEffect(() => {
    if (!ownEntry) return;
    setLockEnabled(ownEntry.locked);
    if (ownEntry.lock_reason !== null) setLockReason(ownEntry.lock_reason);
    if (ownEntry.absence_reason !== null) setAbsenceReason(ownEntry.absence_reason);
  }, [ownEntry]);

  async function run(action: () => Promise<void>, successMessage?: string) {
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (successMessage) setNotice(successMessage);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Неизвестная ошибка");
    } finally {
      setPending(false);
    }
  }

  function saveLock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ownEntry) return;
    const locked = lockEnabled;
    void run(async () => {
      const result = await api.setLock(
        sessionId,
        ownEntry.id,
        lockEnabled,
        lockReason,
      );
      setLockReason(result.lock_reason ?? "");
      await loadQueue();
    }, locked ? "Место зафиксировано" : "Фиксация снята — запись снова можно двигать");
  }

  function markAbsent() {
    if (!ownEntry) return;
    void run(async () => {
      const result = await api.markAbsent(ownEntry.id, absenceReason);
      setAbsenceReason(result.absence_reason ?? "");
      await loadQueue();
    }, "Вы отказались от этой сессии. Преподаватель видит причину.");
  }

  function dropOn(event: DragEvent<HTMLElement>, target: StudentQueueEntry) {
    event.preventDefault();
    const source = entries.find((entry) => entry.id === draggingEntryId);
    setDraggingEntryId(null);
    if (
      !queue ||
      !source ||
      !canDragEntry(source, currentStudentId, queue.frozen) ||
      target.status !== "waiting" ||
      source.id === target.id
    ) return;

    const bounds = event.currentTarget.getBoundingClientRect();
    const placement: QueuePlacement =
      event.clientY >= bounds.top + bounds.height / 2 ? "after" : "before";
    void run(async () => {
      await reorderWithRollback({
        queue,
        sourceId: source.id,
        targetId: target.id,
        placement,
        setQueue,
        reorder: () => api.reorder(sessionId, source.id, target.id, placement),
        reload: () => api.getQueue(sessionId),
      });
    }, "Порядок обновлён");
  }

  return (
    <main className="student-page">
      <div className="student-shell">
        <header className="student-header student-line">
          <div>
            <div className="student-actions">
              <button className="student-button" type="button" onClick={onBack}>← Мои очереди</button>
              <button className="student-button" type="button" onClick={onSettings}>Настройки</button>
            </div>
            <h1 className="student-title">Очередь</h1>
            <p className="student-muted">Перемещать можно только свою ожидающую карточку.</p>
          </div>
          <span className="student-badge">
            {queue?.frozen ? "Порядок заморожен" : "Порядок открыт"}
          </span>
        </header>

        {error && <p className="student-error" role="alert">{error}</p>}
        {notice && <p className="student-notice" role="status">{notice}</p>}
        {!queue && !error && <p>Загружаем очередь…</p>}

        {queue && (
          <div className="student-grid">
            <section className="student-panel" aria-label="Участники очереди">
              <h2>Участники</h2>
              <ul className="student-list">
                {activeEntries.map((entry) => {
                  const isOwn = entry.student_id === currentStudentId;
                  const draggable = canDragEntry(entry, currentStudentId, queue.frozen);
                  return (
                    <li
                      className={`student-entry${isOwn ? " student-entry--own" : ""}${draggable ? " student-entry--draggable" : ""}`}
                      key={entry.id}
                      draggable={draggable}
                      onDragStart={(event) => {
                        if (!draggable) return;
                        setDraggingEntryId(entry.id);
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => setDraggingEntryId(null)}
                      onDragOver={(event) => {
                        if (draggingEntryId && entry.status === "waiting") event.preventDefault();
                      }}
                      onDrop={(event) => dropOn(event, entry)}
                    >
                      <div className="student-line">
                        <strong>#{entry.position}, {entry.student_name}{isOwn ? " (вы)" : ""}</strong>
                        <span className="student-badge">{statusLabels[entry.status]}</span>
                      </div>
                      <p className="student-muted">{etaLabel(entry)}</p>
                      {entry.locked && <span>🔒 Место зафиксировано</span>}
                    </li>
                  );
                })}
              </ul>
            </section>

            <aside className="student-panel" aria-label="Моя запись">
              <h2>Моя запись</h2>
              {!ownEntry && <p>Ваша запись не найдена.</p>}
              {ownEntry && (
                <>
                  <p><strong>Позиция:</strong> {ownEntry.position}</p>
                  <p><strong>Статус:</strong> {statusLabels[ownEntry.status]}</p>
                  <p><strong>{etaLabel(ownEntry)}</strong></p>
                  {queue.frozen && ownEntry.status === "waiting" && (
                    <p className="student-muted" role="status">
                      Порядок заморожен преподавателем — перемещения отключены.
                    </p>
                  )}
                  {ownIndex >= 0 && (
                    <p className="student-muted">
                      Перед вами: {activeEntries[ownIndex - 1]?.student_name ?? "никого"}<br />
                      После вас: {activeEntries[ownIndex + 1]?.student_name ?? "никого"}
                    </p>
                  )}

                  {ownEntry.status === "waiting" && (
                    <>
                      <form onSubmit={saveLock}>
                        <label className="student-field">
                          <span>
                            <input
                              type="checkbox"
                              checked={lockEnabled}
                              onChange={(event) => setLockEnabled(event.target.checked)}
                            />{" "}Зафиксировать место
                          </span>
                          <textarea
                            className="student-textarea"
                            value={lockReason}
                            onChange={(event) => setLockReason(event.target.value)}
                            placeholder="Причина фиксации — необязательно"
                            disabled={!lockEnabled}
                          />
                        </label>
                        <button className="student-button" disabled={pending}>
                          Сохранить фиксацию
                        </button>
                      </form>

                      <div className="student-field">
                        <span>Не смогу участвовать</span>
                        <textarea
                          className="student-textarea"
                          value={absenceReason}
                          onChange={(event) => setAbsenceReason(event.target.value)}
                          placeholder="Причина отказа — необязательно"
                        />
                        <button
                          className="student-button student-button--danger"
                          type="button"
                          disabled={pending}
                          onClick={markAbsent}
                        >
                          Отказаться от этой сессии
                        </button>
                      </div>
                    </>
                  )}

                  {ownEntry.status === "absent" && (
                    <p>Вы отказались от этой сессии{absenceReason ? `: ${absenceReason}` : "."}</p>
                  )}
                </>
              )}
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}
