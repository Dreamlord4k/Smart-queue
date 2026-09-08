import { useCallback, useEffect, useState } from "react";

import {
  browserDemoTokenStorage,
  browserTokenStorage,
  clearTokens,
  decodeDemoFromToken,
  decodeRoleFromToken,
  refreshStoredAccessToken,
  saveTokens,
  type TokenStorage,
  type TokenPair,
  type UserRole,
} from "./auth/session";
import { DemoPanel } from "./components/DemoPanel";
import { Login } from "./screens/Login";
import { MyQueues } from "./screens/MyQueues";
import { Queue } from "./screens/Queue";
import { Register } from "./screens/Register";
import { Settings } from "./screens/Settings";
import { AUTH_ROUTE_EVENT, type AuthRoutePath } from "./screens/AuthTabs";
import { TeacherDashboard } from "./screens/TeacherDashboard";
import { TeacherSession } from "./screens/TeacherSession";
import type { SessionSummary } from "./types/teacher";

export type AppRoute =
  | "/login"
  | "/register"
  | "/queues"
  | "/queue"
  | "/settings"
  | "/teacher"
  | "/teacher/session";

function readStoredToken(): string | null {
  return browserTokenStorage()?.getItem("access_token") ?? null;
}

export function routeForRole(role: UserRole): AppRoute {
  return role === "teacher" ? "/teacher" : "/queues";
}

export function activateDemoRole(
  pair: TokenPair,
  role: UserRole,
  storage: TokenStorage | null,
): { token: string; route: AppRoute } {
  if (storage) saveTokens(storage, pair);
  return { token: pair.access_token, route: routeForRole(role) };
}

interface AppProps {
  initialRoute?: AppRoute;
  readToken?: () => string | null;
}

export function App({ initialRoute, readToken = readStoredToken }: AppProps) {
  const [token, setToken] = useState<string | null>(() => readToken());
  const [demoSession, setDemoSession] = useState(() =>
    token ? decodeDemoFromToken(token) : false,
  );
  const [demoRevision, setDemoRevision] = useState(0);
  const [selectedQueueId, setSelectedQueueId] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<SessionSummary | null>(null);
  const [route, setRoute] = useState<AppRoute>(() => {
    if (initialRoute) {
      return initialRoute;
    }
    if (!token) {
      return "/login";
    }
    return routeForRole(decodeRoleFromToken(token) ?? "student");
  });

  function handleLoginSuccess(role: UserRole) {
    const storedToken = readToken();
    setToken(storedToken);
    setDemoSession(storedToken ? decodeDemoFromToken(storedToken) : false);
    setRoute(routeForRole(role));
  }

  function handleDemoLogin(pair: TokenPair, role: UserRole) {
    const storage = browserDemoTokenStorage();
    const next = activateDemoRole(pair, role, storage);
    setToken(next.token);
    setDemoSession(true);
    setSelectedQueueId(null);
    setSelectedSession(null);
    setRoute(next.route);
  }

  const handleDemoReset = useCallback(() => {
    const storage = browserDemoTokenStorage();
    if (storage) clearTokens(storage);
    setToken(null);
    setDemoSession(false);
    setDemoRevision((value) => value + 1);
    setSelectedQueueId(null);
    setSelectedSession(null);
    setRoute("/login");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onAuthRoute = (event: Event) => {
      const route = (event as CustomEvent<AuthRoutePath>).detail;
      if (route === "/login" || route === "/register") {
        setRoute(route);
      }
    };
    window.addEventListener(AUTH_ROUTE_EVENT, onAuthRoute);
    return () => window.removeEventListener(AUTH_ROUTE_EVENT, onAuthRoute);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    refreshStoredAccessToken()
      .then((restoredToken) => {
        if (!restoredToken) return;
        setToken(restoredToken);
        setDemoSession(decodeDemoFromToken(restoredToken));
        if (route === "/login" || route === "/register") {
          setRoute(routeForRole(decodeRoleFromToken(restoredToken) ?? "student"));
        }
      })
      .catch(() => {
        setToken(null);
        setDemoSession(false);
        setRoute("/login");
      });
    // Восстановление выполняется один раз после запуска клиента.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Защищённые маршруты без токена ведут на вход.
  const visible: AppRoute =
    !token &&
    (route === "/queues" || route === "/queue" || route === "/settings" || route.startsWith("/teacher"))
      ? "/login"
      : route;
  const currentRole = token ? decodeRoleFromToken(token) : null;

  // Шапки-навигации нет: переключение Вход/Регистрация живёт
  // сегментом внутри карточки, остальные экраны — без дублей.
  return (
    <div className={`app-root${demoSession ? " app-root--demo" : ""}`}>
      {visible === "/login" && <Login onSuccess={handleLoginSuccess} />}
      {visible === "/register" && <Register onSuccess={() => setRoute("/login")} />}
      {visible === "/queues" && token && (
        <>
          <nav className="student-nav" aria-label="Навигация студента">
            <button className="student-button" type="button" onClick={() => setRoute("/settings")}>Настройки</button>
          </nav>
          <MyQueues
            key={demoRevision}
            accessToken={token}
            onOpenQueue={(sessionId) => {
              setSelectedQueueId(sessionId);
              setRoute("/queue");
            }}
          />
        </>
      )}
      {visible === "/queue" && token && selectedQueueId && (
        <Queue
          key={demoRevision}
          accessToken={token}
          sessionId={selectedQueueId}
          onBack={() => setRoute("/queues")}
          onSettings={() => setRoute("/settings")}
        />
      )}
      {visible === "/queue" && token && !selectedQueueId && (
        <MyQueues
          key={demoRevision}
          accessToken={token}
          onOpenQueue={(sessionId) => setSelectedQueueId(sessionId)}
        />
      )}
      {visible === "/settings" && token && (
        <Settings
          key={demoRevision}
          accessToken={token}
          demoMode={demoSession}
          role={currentRole ?? "student"}
          onBack={() => setRoute(
            currentRole === "teacher"
              ? "/teacher"
              : selectedQueueId
                ? "/queue"
                : "/queues",
          )}
          onDeleted={() => {
            setToken(null);
            setDemoSession(false);
            setRoute("/login");
          }}
        />
      )}
      {visible === "/teacher" && token && (
        <TeacherDashboard
          key={demoRevision}
          accessToken={token}
          onSettings={() => setRoute("/settings")}
          onOpenSession={(session) => {
            setSelectedSession(session);
            setRoute("/teacher/session");
          }}
        />
      )}
      {visible === "/teacher/session" && token && selectedSession && (
        <TeacherSession
          key={demoRevision}
          accessToken={token}
          session={selectedSession}
          onBack={() => setRoute("/teacher")}
        />
      )}
      {visible === "/teacher/session" && token && !selectedSession && (
        <TeacherDashboard
          key={demoRevision}
          accessToken={token}
          onSettings={() => setRoute("/settings")}
          onOpenSession={setSelectedSession}
        />
      )}
      <DemoPanel
        accessToken={token}
        demoSession={demoSession}
        onLogin={handleDemoLogin}
        onReset={handleDemoReset}
      />
    </div>
  );
}
