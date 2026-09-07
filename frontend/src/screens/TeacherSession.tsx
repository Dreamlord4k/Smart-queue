import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { createTeacherApi, type TeacherApi } from "../api/teacher";
import "../components/teacher/Teacher.css";
import { useQueueSocket } from "../hooks/useQueueSocket";
import type {
  GroupWithStudents,
  QueueEntryState,
  QueueState,
  SessionReport,
  SessionStatus,
  SessionSummary,
} from "../types/teacher";

interface TeacherSessionProps {
  accessToken: string;
  session: SessionSummary;
  groups?: GroupWithStudents[];
  apiBaseUrl?: string;
  api?: TeacherApi;
  initialQueue?: QueueState;
  initialReport?: SessionReport | null;
  onBack?: () => void;
}

const statusLabels: Record<SessionStatus, string> = {
  planned: "Запланирована",
  active: "Идёт приём",
  paused: "На паузе",
  closed: "Завершена",
  cancelled: "Отменена",
};

function etaLabel(entry: QueueEntryState): string {
  if (!entry.eta_start || !entry.eta_end) return "ETA не рассчитан";
  const format = (value: string) =>
    new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `ETA ${format(entry.eta_start)}–${format(entry.eta_end)}`;
}

function secondsLabel(value: number | null): string {
  if (value === null) return "—";
  return `${Math.round(value / 60)} мин`;
}

export function TeacherSession({
  accessToken,
  session: initialSession,
  groups = [],
  apiBaseUrl,
  api: suppliedApi,
  initialQueue,
  initialReport = null,
  onBack,
}: TeacherSessionProps) {
  const api = useMemo(
    () => suppliedApi ?? createTeacherApi(accessToken, apiBaseUrl),
    [accessToken, apiBaseUrl, suppliedApi],
  );
  const [session, setSession] = useState(initialSession);
  const [queue, setQueue] = useState<QueueState | null>(initialQueue ?? null);
  const [report, setReport] = useState<SessionReport | null>(initialReport);
  const [availableGroups, setAvailableGroups] = useState(groups);
  const [duration, setDuration] = useState(initialSession.duration_default);
  const [candidateId, setCandidateId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    setQueue(await api.getQueue(session.id));
  }, [api, session.id]);

  useEffect(() => {
    if (initialQueue) return;
    loadQueue().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить очередь"),
    );
  }, [initialQueue, loadQueue]);

  useQueueSocket({
    sessionId: session.id,
    accessToken,
    apiBaseUrl,
    onUpdate: loadQueue,
  });

  useEffect(() => {
    if (groups.length > 0) return;
    api.listGroups().then(setAvailableGroups).catch(() => undefined);
  }, [api, groups.length]);

  const allStudents = useMemo(() => {
    const unique = new Map(
      availableGroups
        .flatMap((group) => group.students)
        .map((student) => [student.id, student]),
    );
    return [...unique.values()].sort((a, b) => a.full_name.localeCompare(b.full_name, "ru"));
  }, [availableGroups]);

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

  function changeStatus(status: SessionStatus) {
    void run(async () => {
      const updated = await api.updateSession(session.id, { status });
      setSession(updated);
      setReport(updated.report);
      await loadQueue();
    }, `Статус сессии: ${statusLabels[status]}`);
  }

  function freeze() {
    void run(async () => {
      const frozen = await api.freezeSession(session.id);
      setSession((current) => ({ ...current, frozen: frozen.frozen }));
    }, "Список заморожен — порядок больше не меняется");
  }

  function changeDuration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      const updated = await api.updateSession(session.id, {
        duration_default: duration,
      });
      setSession(updated);
      await loadQueue();
    }, "Длительность приёма обновлена");
  }

  function queueAction(action: () => Promise<unknown>, successMessage?: string) {
    void run(async () => {
      await action();
      await loadQueue();
    }, successMessage);
  }

  function addParticipant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!candidateId) return;
    queueAction(async () => {
      await api.addParticipant(session.id, candidateId);
      setCandidateId("");
    }, "Участник добавлен в конец очереди");
  }

  const entries = queue?.entries ?? [];
  const waiting = entries.filter((entry) => entry.status === "waiting");
  const history = entries.filter((entry) =>
    ["done", "skipped", "absent"].includes(entry.status),
  );

  return (
    <main className="teacher-page">
      <div className="teacher-shell">
        <header className="teacher-header">
          <div>
            <button className="teacher-button" type="button" onClick={onBack}>← Все сессии</button>
            <p className="teacher-eyebrow">{statusLabels[session.status]}</p>
            <h1 className="teacher-title">{session.course_name}</h1>
            <p className="teacher-muted">
              {session.date} в {session.start_time.slice(0, 5)}, аудитория {session.room}
            </p>
          </div>
          <span className="teacher-badge">
            {session.frozen ? "Порядок заморожен" : "Порядок открыт"}
          </span>
        </header>

        {error && <p className="teacher-error" role="alert">{error}</p>}
        {notice && <p className="teacher-notice" role="status">{notice}</p>}

        <section className="teacher-panel teacher-toolbar" aria-label="Управление сессией">
          <div className="teacher-actions">
            {session.status === "planned" && !session.frozen && (
              <button className="teacher-button" disabled={pending} onClick={freeze}>Заморозить список</button>
            )}
            {session.status === "planned" && (
              <button
                className="teacher-button teacher-button--primary"
                disabled={pending || !session.frozen}
                onClick={() => changeStatus("active")}
              >
                Начать приём
              </button>
            )}
            {session.status === "active" && (
              <button className="teacher-button" disabled={pending} onClick={() => changeStatus("paused")}>Пауза</button>
            )}
            {session.status === "paused" && (
              <button className="teacher-button teacher-button--primary" disabled={pending} onClick={() => changeStatus("active")}>Продолжить</button>
            )}
            {(session.status === "active" || session.status === "paused") && (
              <button className="teacher-button" disabled={pending} onClick={() => changeStatus("closed")}>Закрыть сессию</button>
            )}
            {(session.status === "planned" || session.status === "active" || session.status === "paused") && (
              <button className="teacher-button teacher-button--danger" disabled={pending} onClick={() => changeStatus("cancelled")}>Отменить</button>
            )}
          </div>
          {session.status !== "closed" && session.status !== "cancelled" && (
            <form className="teacher-control" onSubmit={changeDuration}>
              <label>
                <span>Минут на студента</span>
                <input min={1} type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
              </label>
              <button className="teacher-button" disabled={pending}>Сохранить</button>
            </form>
          )}
        </section>

        <section className="teacher-section" aria-label="Каналы приёма">
          <h2>Каналы приёма</h2>
          <div className="teacher-channels">
            {Array.from({ length: session.capacity }, (_, index) => index + 1).map((channel) => {
              const current = entries.find(
                (entry) => entry.status === "called" && entry.channel === channel,
              );
              return (
                <article className="teacher-channel anim-rise" key={channel}>
                  <span className="teacher-badge">Канал {channel}</span>
                  <h3>{current?.student_name ?? "Свободен"}</h3>
                  {current && (
                    <>
                      <div className="teacher-reasons">
                        <span>Фиксация: {current.locked ? "да" : "нет"}</span>
                        {current.lock_reason && <span>Причина фиксации: {current.lock_reason}</span>}
                      </div>
                      <div className="teacher-actions teacher-channel-actions">
                        <button className="teacher-button teacher-button--primary" disabled={pending} onClick={() => queueAction(() => api.finishEntry(session.id, current.id), `Готово: ${current.student_name}`)}>Готово</button>
                        <button className="teacher-button" disabled={pending} onClick={() => queueAction(() => api.skipEntry(session.id, current.id), `Пропущен: ${current.student_name}`)}>Пропустить</button>
                      </div>
                    </>
                  )}
                </article>
              );
            })}
          </div>
        </section>

        <section className="teacher-section" aria-label="Ожидающие участники">
          <h2>Очередь</h2>
          <ul className="teacher-list">
            {waiting.map((entry) => (
              <li key={entry.id}>
                <div className="teacher-session-line">
                  <span><strong>#{entry.position}, {entry.student_name}</strong> — {etaLabel(entry)}</span>
                  <button
                    className="teacher-button"
                    disabled={pending || session.status === "closed" || session.status === "cancelled"}
                    onClick={() => queueAction(() => api.removeParticipant(session.id, entry.id), `Удалён из очереди: ${entry.student_name}`)}
                  >
                    Удалить
                  </button>
                </div>
                <div className="teacher-reasons">
                  <span>Фиксация: {entry.locked ? "да" : "нет"}</span>
                  {entry.lock_reason && <span>Причина фиксации: {entry.lock_reason}</span>}
                  {entry.absence_reason && <span>Причина отказа: {entry.absence_reason}</span>}
                </div>
              </li>
            ))}
          </ul>
        </section>

        {session.status !== "closed" && session.status !== "cancelled" && (
          <section className="teacher-panel">
            <h2>Добавить участника</h2>
            <form className="teacher-control teacher-actions" onSubmit={addParticipant}>
              <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)} aria-label="Студент">
                <option value="">Выберите студента</option>
                {allStudents.map((student) => <option key={student.id} value={student.id}>{student.full_name} ({student.email})</option>)}
              </select>
              <button className="teacher-button teacher-button--primary" disabled={pending || !candidateId}>Добавить в конец</button>
            </form>
          </section>
        )}

        <section className="teacher-section" aria-label="История участия">
          <h2>История</h2>
          <ul className="teacher-list">
            {history.map((entry) => (
              <li key={entry.id}>
                <strong>{entry.student_name}</strong> — {entry.status}
                <div className="teacher-reasons">
                  {entry.lock_reason && <span>Причина фиксации: {entry.lock_reason}</span>}
                  {entry.absence_reason && <span>Причина отказа: {entry.absence_reason}</span>}
                </div>
              </li>
            ))}
          </ul>
        </section>

        {report && (
          <section className="teacher-report" aria-label="Итоговый отчёт">
            <div>Принято<strong>{report.accepted_count}</strong></div>
            <div>Пропущено<strong>{report.skipped_count}</strong></div>
            <div>Средняя длительность<strong>{secondsLabel(report.average_service_seconds)}</strong></div>
            <div>Плановое время<strong>{secondsLabel(report.planned_duration_seconds)}</strong></div>
            <div>Фактическое время<strong>{secondsLabel(report.actual_duration_seconds)}</strong></div>
            <div>Средняя ошибка ETA<strong>{secondsLabel(report.average_eta_error_seconds)}</strong></div>
          </section>
        )}
      </div>
    </main>
  );
}
