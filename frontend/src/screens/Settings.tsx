import { useEffect, useMemo, useState } from "react";

import {
  createStudentApi,
  type StudentApi,
  type TelegramLinkState,
} from "../api/student";
import { ThemeToggle } from "../components/ThemeToggle";
import "../components/student/Student.css";

interface SettingsProps {
  accessToken: string;
  apiBaseUrl?: string;
  api?: StudentApi;
  onBack?: () => void;
  onDeleted?: () => void;
}

export function Settings({
  accessToken,
  apiBaseUrl,
  api: suppliedApi,
  onBack,
  onDeleted,
}: SettingsProps) {
  const api = useMemo(
    () => suppliedApi ?? createStudentApi(accessToken, apiBaseUrl),
    [accessToken, apiBaseUrl, suppliedApi],
  );
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [telegram, setTelegram] = useState<TelegramLinkState | null>(null);
  const [telegramPending, setTelegramPending] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadTelegramLink() {
    setTelegramPending(true);
    setError(null);
    try {
      setTelegram(await api.initTelegramLink());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось получить код Telegram");
    } finally {
      setTelegramPending(false);
    }
  }

  useEffect(() => {
    void loadTelegramLink();
    // API стабилен для текущего токена; повторный выпуск запускается кнопкой.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  async function deleteProfile() {
    if (!confirmed) return;
    setPending(true);
    setError(null);
    try {
      await api.deleteProfile();
      onDeleted?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось удалить профиль");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="student-page">
      <div className="student-shell">
        <button className="student-button" type="button" onClick={onBack}>← Назад</button>
        <h1 className="student-title">Настройки</h1>
        {error && <p className="student-error" role="alert">{error}</p>}
        <section className="student-panel" aria-label="Привязка Telegram">
          <h2>Уведомления в Telegram</h2>
          {telegramPending ? (
            <p>Проверяем состояние привязки…</p>
          ) : telegram?.linked ? (
            <p>Telegram привязан. Уведомления об очереди включены.</p>
          ) : (
            <>
              <p>
                Отправьте боту команду <strong>/start {telegram?.code}</strong>.
                Код действует 10 минут и только один раз.
              </p>
              {telegram?.deep_link && (
                <a className="student-button" href={telegram.deep_link} target="_blank" rel="noreferrer">
                  Открыть Telegram
                </a>
              )}
              <button
                className="student-button"
                type="button"
                onClick={() => void loadTelegramLink()}
              >
                Выпустить новый код
              </button>
            </>
          )}
        </section>
        <section className="student-panel" aria-label="Оформление">
          <h2>Оформление</h2>
          <p>Тёмная тема бережёт глаза вечером. Выбор запоминается на этом устройстве.</p>
          <ThemeToggle />
        </section>
        <section className="student-panel" aria-label="Удаление профиля">
          <h2>Удалить мой профиль</h2>
          <p>
            Аккаунт и связанные с ним записи будут удалены без возможности восстановления.
            Данные других участников не изменятся.
          </p>
          <label className="student-field">
            <span>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />{" "}Я понимаю последствия и подтверждаю удаление
            </span>
          </label>
          <button
            className="student-button student-button--danger"
            type="button"
            disabled={!confirmed || pending}
            onClick={() => void deleteProfile()}
          >
            {pending ? "Удаляем…" : "Удалить профиль навсегда"}
          </button>
        </section>
      </div>
    </main>
  );
}
