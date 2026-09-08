import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ACCESS_TOKEN_KEY, type TokenStorage } from "./auth/session";
import { activateDemoRole, App } from "./App";

function fakeJwt(role: string): string {
  const payload = btoa(JSON.stringify({ sub: "user-id", role }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `header.${payload}.signature`;
}

describe("App", () => {
  it("без токена показывает вход", () => {
    const html = renderToStaticMarkup(<App readToken={() => null} />);

    expect(html).toContain("Вход");
    expect(html).toContain('name="password"');
  });

  it("защищённый маршрут без токена ведёт на вход", () => {
    const html = renderToStaticMarkup(
      <App initialRoute="/queues" readToken={() => null} />,
    );

    expect(html).toContain("Вход");
    expect(html).not.toContain("Мои очереди");
  });

  it("преподаватель с токеном видит дашборд сессий", () => {
    const html = renderToStaticMarkup(
      <App initialRoute="/teacher" readToken={() => fakeJwt("teacher")} />,
    );

    expect(html).toContain("Мои сессии");
    expect(html).toContain("Новая сессия");
  });

  it("студент с токеном попадает в свои очереди", () => {
    const html = renderToStaticMarkup(
      <App readToken={() => fakeJwt("student")} />,
    );

    expect(html).toContain("Мои очереди");
    expect(html).toContain("Настройки");
  });

  it("настройки доступны только в авторизованной части", () => {
    const protectedHtml = renderToStaticMarkup(
      <App initialRoute="/settings" readToken={() => fakeJwt("student")} />,
    );
    const anonymousHtml = renderToStaticMarkup(
      <App initialRoute="/settings" readToken={() => null} />,
    );

    expect(protectedHtml).toContain("Удалить мой профиль");
    expect(anonymousHtml).toContain("Вход");
    expect(anonymousHtml).not.toContain("Удалить мой профиль");
  });

  it("на auth-роутах нет дублирующей шапки-навигации", () => {
    const loginHtml = renderToStaticMarkup(<App readToken={() => null} />);
    const registerHtml = renderToStaticMarkup(
      <App initialRoute="/register" readToken={() => null} />,
    );

    expect(loginHtml).not.toContain("<nav");
    expect(registerHtml).not.toContain("<nav");
    expect(registerHtml).toContain("auth-tabs");
  });

  it("переключает demo-преподавателя на кабинет студента с заменой токена", () => {
    const values = new Map<string, string>();
    const storage: TokenStorage = {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    };

    const teacher = activateDemoRole(
      { access_token: "teacher-token", refresh_token: "teacher-refresh" },
      "teacher",
      storage,
    );
    const student = activateDemoRole(
      { access_token: "student-token", refresh_token: "student-refresh" },
      "student",
      storage,
    );

    expect(teacher.route).toBe("/teacher");
    expect(student.route).toBe("/queues");
    expect(storage.getItem(ACCESS_TOKEN_KEY)).toBe("student-token");
  });
});
