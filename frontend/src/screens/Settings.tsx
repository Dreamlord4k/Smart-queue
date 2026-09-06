import { useMemo, useState } from "react";

import { createStudentApi, type StudentApi } from "../api/student";
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
  const [error, setError] = useState<string | null>(null);

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
