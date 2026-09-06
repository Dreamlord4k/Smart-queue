import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { App } from "./App";

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

  it("преподаватель с токеном видит заглушку кабинета", () => {
    const html = renderToStaticMarkup(
      <App initialRoute="/teacher" readToken={() => fakeJwt("teacher")} />,
    );

    expect(html).toContain("Кабинет преподавателя");
    expect(html).toContain("скоро");
  });

  it("студент с токеном попадает в свои очереди", () => {
    const html = renderToStaticMarkup(
      <App readToken={() => fakeJwt("student")} />,
    );

    expect(html).toContain("Мои очереди");
  });
});
