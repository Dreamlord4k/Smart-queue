import { useEffect, useState } from "react";

import { Login, decodeRoleFromToken, type UserRole } from "./screens/Login";
import { MyQueues } from "./screens/MyQueues";
import { Register } from "./screens/Register";
import { AUTH_ROUTE_EVENT, type AuthRoutePath } from "./screens/AuthTabs";

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

  // Защищённые маршруты без токена ведут на вход.
  const visible: AppRoute =
    !token && (route === "/queues" || route === "/teacher") ? "/login" : route;

  // Шапки-навигации нет: переключение Вход/Регистрация живёт
  // сегментом внутри карточки, остальные экраны — без дублей.
  return (
    <div style={{ fontFamily: "sans-serif" }}>
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
