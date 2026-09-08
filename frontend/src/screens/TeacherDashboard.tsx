import { useEffect, useMemo, useState } from "react";

import { createTeacherApi, type TeacherApi } from "../api/teacher";
import { SessionForm } from "../components/teacher/SessionForm";
import { ThemeToggle } from "../components/ThemeToggle";
import "../components/teacher/Teacher.css";
import type {
  CreateSessionInput,
  GroupWithStudents,
  SessionSummary,
} from "../types/teacher";
import { formatUniversitySessionStart, UNIVERSITY_TIME_NOTE } from "../utils/time";

interface TeacherDashboardProps {
  accessToken: string;
  apiBaseUrl?: string;
  api?: TeacherApi;
  initialSessions?: SessionSummary[];
  initialGroups?: GroupWithStudents[];
  onOpenSession?: (session: SessionSummary) => void;
  onSettings?: () => void;
}

export function splitSessions(sessions: SessionSummary[]) {
  return {
    active: sessions.filter((item) => item.status === "active" || item.status === "paused"),
    upcoming: sessions.filter((item) => item.status === "planned"),
    completed: sessions.filter(
      (item) => item.status === "closed" || item.status === "cancelled",
    ),
  };
}

const labels = {
  active: "Идут сейчас",
  upcoming: "Предстоящие",
  completed: "Завершённые",
};

function SessionCard({
  session,
  onOpen,
}: {
  session: SessionSummary;
  onOpen?: (session: SessionSummary) => void;
}) {
  return (
    <article className="teacher-card anim-rise">
      <div className="teacher-session-line">
        <span className="teacher-badge">{session.status}</span>
        <span>{session.capacity} канал(а)</span>
      </div>
      <h3>{session.course_name}</h3>
      <p>{formatUniversitySessionStart(session.date, session.start_time)} ({UNIVERSITY_TIME_NOTE})</p>
      <p>Аудитория {session.room}, {session.duration_default} мин/студент</p>
      <p className="teacher-muted">
        {session.frozen ? "Порядок заморожен" : "Порядок ещё открыт"}
      </p>
      <button className="teacher-button" type="button" onClick={() => onOpen?.(session)}>
        Открыть сессию
      </button>
    </article>
  );
}

export function TeacherDashboard({
  accessToken,
  apiBaseUrl,
  api: suppliedApi,
  initialSessions,
  initialGroups,
  onOpenSession,
  onSettings,
}: TeacherDashboardProps) {
  const api = useMemo(
    () => suppliedApi ?? createTeacherApi(accessToken, apiBaseUrl),
    [accessToken, apiBaseUrl, suppliedApi],
  );
  const [sessions, setSessions] = useState(initialSessions ?? []);
  const [groups, setGroups] = useState(initialGroups ?? []);
  const [loading, setLoading] = useState(
    initialSessions === undefined || initialGroups === undefined,
  );
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialSessions !== undefined && initialGroups !== undefined) return;
    let active = true;
    Promise.all([api.listSessions(), api.listGroups()])
      .then(([loadedSessions, loadedGroups]) => {
        if (!active) return;
        setSessions(loadedSessions);
        setGroups(loadedGroups);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить кабинет");
        }
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [api, initialGroups, initialSessions]);

  async function createSession(input: CreateSessionInput) {
    setCreating(true);
    setError(null);
    try {
      const created = await api.createSession(input);
      setSessions((current) => [...current, created]);
      setShowForm(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось создать сессию");
    } finally {
      setCreating(false);
    }
  }

  const sections = splitSessions(sessions);

  return (
    <main className="teacher-page">
      <div className="teacher-shell">
        <header className="teacher-header">
          <div>
            <p className="teacher-eyebrow">Умная очередь</p>
            <h1 className="teacher-title">Мои сессии</h1>
            <p className="teacher-muted">Сегодняшние и предстоящие приёмы в одном месте</p>
          </div>
          <div className="teacher-actions">
            <ThemeToggle />
            <button className="teacher-button" type="button" onClick={onSettings}>
              Настройки
            </button>
            <button
              className="teacher-button teacher-button--primary"
              type="button"
              onClick={() => setShowForm((value) => !value)}
            >
              {showForm ? "Скрыть форму" : "Новая сессия"}
            </button>
          </div>
        </header>

        {error && <p className="teacher-error" role="alert">{error}</p>}
        {loading && <p>Загружаем сессии…</p>}

        {showForm && (
          <section className="teacher-panel">
            <h2>Создание сессии</h2>
            <SessionForm groups={groups} pending={creating} onCreate={createSession} />
          </section>
        )}

        {(Object.keys(sections) as Array<keyof typeof sections>).map((key) => (
          <section className="teacher-section" key={key} aria-label={labels[key]}>
            <h2>{labels[key]}</h2>
            {sections[key].length === 0 ? (
              <p className="teacher-muted">Сессий здесь пока нет.</p>
            ) : (
              <div className="teacher-grid">
                {sections[key].map((session) => (
                  <SessionCard key={session.id} session={session} onOpen={onOpenSession} />
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </main>
  );
}
