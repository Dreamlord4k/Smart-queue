import { useState } from "react";

import { Login, decodeRoleFromToken, type UserRole } from "./screens/Login";
import { MyQueues } from "./screens/MyQueues";
import { Register } from "./screens/Register";

export type AppRoute = "/login" | "/register" | "/queues" | "/teacher";

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

  // Защищённые маршруты без токена ведут на вход.
  const visible: AppRoute =
    !token && (route === "/queues" || route === "/teacher") ? "/login" : route;

  return (
    <div style={{ fontFamily: "sans-serif" }}>
      <nav style={{ display: "flex", gap: 12, padding: "12px 24px" }}>
        {!token && (
          <>
            <button type="button" onClick={() => setRoute("/login")}>
              Вход
            </button>
            <button type="button" onClick={() => setRoute("/register")}>
              Регистрация
            </button>
          </>
        )}
      </nav>
      {visible === "/login" && <Login onSuccess={handleLoginSuccess} />}
      {visible === "/register" && <Register onSuccess={() => setRoute("/login")} />}
      {visible === "/queues" && token && <MyQueues accessToken={token} />}
      {visible === "/teacher" && (
        <main style={{ maxWidth: 960, margin: "0 auto", padding: 24 }}>
          <h1>Кабинет преподавателя</h1>
          <p>Экран управления сессиями — скоро.</p>
        </main>
      )}
    </div>
  );
}
