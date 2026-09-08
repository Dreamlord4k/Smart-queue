import { useCallback, useEffect, useState } from "react";

import type { TokenPair, UserRole } from "../auth/session";
import {
  DEMO_IDLE_TIMEOUT_MS,
  signalDemoReset,
  startDemoActivityMonitor,
} from "../demo/activity";
import "./DemoPanel.css";

type FetchImpl = typeof fetch;
type DemoAvailability = "checking" | "disabled" | "available" | "missing";

export const DEMO_RESET_INTERVAL_MS = DEMO_IDLE_TIMEOUT_MS;

function apiBaseUrl(explicit?: string): string {
  return explicit ?? (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
}

async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function demoLogin(
  role: UserRole,
  options: { apiBaseUrl?: string; fetchImpl?: FetchImpl } = {},
): Promise<TokenPair> {
  const response = await (options.fetchImpl ?? fetch)(
    `${apiBaseUrl(options.apiBaseUrl)}/auth/demo-login`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    },
  );
  if (!response.ok) {
    const error = new Error(await errorDetail(response, "Демо-вход недоступен"));
    Object.assign(error, { status: response.status });
    throw error;
  }
  return (await response.json()) as TokenPair;
}

export async function resetDemo(
  accessToken: string,
  options: { apiBaseUrl?: string; fetchImpl?: FetchImpl } = {},
): Promise<void> {
  const response = await (options.fetchImpl ?? fetch)(
    `${apiBaseUrl(options.apiBaseUrl)}/auth/demo-reset`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  );
  if (!response.ok) {
    throw new Error(await errorDetail(response, "Не удалось сбросить демо"));
  }
}

interface DemoPanelProps {
  accessToken?: string | null;
  apiBaseUrl?: string;
  demoSession: boolean;
  initialAvailability?: DemoAvailability;
  onLogin?: (pair: TokenPair, role: UserRole) => void;
  onReset?: () => void;
}

export function DemoPanel({
  accessToken,
  apiBaseUrl: explicitApiBaseUrl,
  demoSession,
  initialAvailability,
  onLogin,
  onReset,
}: DemoPanelProps) {
  const [availability, setAvailability] = useState<DemoAvailability>(
    initialAvailability ?? "checking",
  );
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (initialAvailability) return;
    const controller = new AbortController();
    fetch(`${apiBaseUrl(explicitApiBaseUrl)}/health`, { signal: controller.signal })
      .then(async (response) => {
        const body = (await response.json()) as { demo_mode?: boolean };
        setAvailability(body.demo_mode ? "available" : "disabled");
      })
      .catch(() => setAvailability("disabled"));
    return () => controller.abort();
  }, [explicitApiBaseUrl, initialAvailability]);

  const handleReset = useCallback(async (automatic = false) => {
    if (!accessToken || !demoSession) return;
    setPending(true);
    setMessage(null);
    try {
      await resetDemo(accessToken, { apiBaseUrl: explicitApiBaseUrl });
      if (typeof window !== "undefined") signalDemoReset(window.localStorage);
      setMessage(automatic ? "Демо автоматически сброшено после 30 минут бездействия" : "Демо сброшено");
      onReset?.();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Не удалось сбросить демо");
    } finally {
      setPending(false);
    }
  }, [accessToken, demoSession, explicitApiBaseUrl, onReset]);

  useEffect(() => {
    if (!demoSession || !accessToken || typeof window === "undefined") return;
    return startDemoActivityMonitor({
      target: window,
      storage: window.localStorage,
      onIdle: () => void handleReset(true),
      onExternalReset: () => {
        setMessage("Демо автоматически сброшено в другой вкладке");
        onReset?.();
      },
    });
  }, [accessToken, demoSession, handleReset]);

  async function signIn(role: UserRole) {
    setPending(true);
    setMessage(null);
    try {
      const pair = await demoLogin(role, { apiBaseUrl: explicitApiBaseUrl });
      onLogin?.(pair, role);
    } catch (reason) {
      if (reason instanceof Error && "status" in reason && reason.status === 404) {
        setAvailability("missing");
      } else {
        setMessage(reason instanceof Error ? reason.message : "Демо-вход недоступен");
      }
    } finally {
      setPending(false);
    }
  }

  if (accessToken && demoSession) {
    return (
      <aside
        className="demo-panel demo-panel--session"
        aria-label="Демонстрационный режим"
      >
        <strong>Демо-режим</strong>
        <p>Переключайте роль без выхода. Сброс — через 30 минут бездействия.</p>
        <div className="demo-panel__roles" aria-label="Переключить демо-роль">
          <button disabled={pending} type="button" onClick={() => void signIn("teacher")}>
            Демо-препод
          </button>
          <button disabled={pending} type="button" onClick={() => void signIn("student")}>
            Демо-студент
          </button>
        </div>
        <button
          className="demo-panel__reset"
          disabled={pending}
          type="button"
          onClick={() => void handleReset(false)}
        >
          Сбросить демо
        </button>
        {message && <p className="demo-panel__message" role="status">{message}</p>}
      </aside>
    );
  }

  if (accessToken || availability === "checking" || availability === "disabled") {
    return null;
  }

  return (
    <aside className="demo-panel" aria-label="Демонстрационный режим">
      <strong>Демо для комиссии</strong>
      {availability === "missing" ? (
        <p className="demo-panel__message">
          Запустите seed: <code>scripts/seed_demo_ui.py</code>
        </p>
      ) : (
        <>
          <p className="demo-panel__hint">
            Откройте роли в разных вкладках — изменения будут видны вживую.
          </p>
          <div className="demo-panel__roles" aria-label="Выбрать демо-роль">
            <button disabled={pending} type="button" onClick={() => void signIn("teacher")}>
              Демо-препод
            </button>
            <button disabled={pending} type="button" onClick={() => void signIn("student")}>
              Демо-студент
            </button>
          </div>
        </>
      )}
      {message && <p className="demo-panel__message" role="status">{message}</p>}
    </aside>
  );
}
