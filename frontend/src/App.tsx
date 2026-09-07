import { useEffect, useState } from "react";

import { decodeRoleFromToken, refreshStoredAccessToken, type UserRole } from "./auth/session";
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
  if (typeof window === "undefined" || !window.localStorage) {
    return null;
  }
  return window.localStorage.getItem("access_token");
}

function routeForRole(role: UserRole): AppRoute {
  return role === "teacher" ? "/teacher" : "/queues";
}

interface AppProps {
  initialRoute?: AppRoute;
  readToken?: () => string | null;
}

export function App({ initialRoute, readToken = readStoredToken }: AppProps) {
  const [token, setToken] = useState<string | null>(() => readToken());
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
    setToken(readToken());
    setRoute(routeForRole(role));
  }

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
        if (route === "/login" || route === "/register") {
          setRoute(routeForRole(decodeRoleFromToken(restoredToken) ?? "student"));
        }
      })
      .catch(() => {
        setToken(null);
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

  // Шапки-навигации нет: переключение Вход/Регистрация живёт
  // сегментом внутри карточки, остальные экраны — без дублей.
  return (
    <div className="app-root">
      {visible === "/login" && <Login onSuccess={handleLoginSuccess} />}
      {visible === "/register" && <Register onSuccess={() => setRoute("/login")} />}
      {visible === "/queues" && token && (
        <>
          <nav className="student-nav" aria-label="Навигация студента">
            <button className="student-button" type="button" onClick={() => setRoute("/settings")}>Настройки</button>
          </nav>
          <MyQueues
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
          accessToken={token}
          sessionId={selectedQueueId}
          onBack={() => setRoute("/queues")}
          onSettings={() => setRoute("/settings")}
        />
      )}
      {visible === "/queue" && token && !selectedQueueId && (
        <MyQueues
          accessToken={token}
          onOpenQueue={(sessionId) => setSelectedQueueId(sessionId)}
        />
      )}
      {visible === "/settings" && token && (
        <Settings
          accessToken={token}
          onBack={() => setRoute(selectedQueueId ? "/queue" : "/queues")}
          onDeleted={() => {
            setToken(null);
            setRoute("/login");
          }}
        />
      )}
      {visible === "/teacher" && token && (
        <TeacherDashboard
          accessToken={token}
          onOpenSession={(session) => {
            setSelectedSession(session);
            setRoute("/teacher/session");
          }}
        />
      )}
      {visible === "/teacher/session" && token && selectedSession && (
        <TeacherSession
          accessToken={token}
          session={selectedSession}
          onBack={() => setRoute("/teacher")}
        />
      )}
      {visible === "/teacher/session" && token && !selectedSession && (
        <TeacherDashboard accessToken={token} onOpenSession={setSelectedSession} />
      )}
    </div>
  );
}
