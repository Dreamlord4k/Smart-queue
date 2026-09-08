import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  DEMO_RESET_INTERVAL_MS,
  DemoPanel,
  demoLogin,
  resetDemo,
} from "./DemoPanel";

describe("DemoPanel", () => {
  it("использует 30-минутный интервал автосброса", () => {
    expect(DEMO_RESET_INTERVAL_MS).toBe(30 * 60 * 1000);
  });

  it("показывает кнопки входа только гостю", () => {
    const guest = renderToStaticMarkup(
      <DemoPanel initialAvailability="available" demoSession={false} />,
    );
    const authorized = renderToStaticMarkup(
      <DemoPanel
        accessToken="token"
        initialAvailability="available"
        demoSession={false}
      />,
    );

    expect(guest).toContain("Демо-препод");
    expect(guest).toContain("Демо-студент");
    expect(guest).not.toContain("demo-panel--session");
    expect(authorized).toBe("");
  });

  it("оставляет в авторизованной demo-сессии обе роли и сброс", () => {
    const html = renderToStaticMarkup(
      <DemoPanel
        accessToken="demo-token"
        initialAvailability="available"
        demoSession
      />,
    );

    expect(html).toContain("Демо-режим");
    expect(html).toContain("Сбросить демо");
    expect(html).toContain("Демо-препод");
    expect(html).toContain("Демо-студент");
    expect(html).toContain("Переключить демо-роль");
    expect(html).toContain("demo-panel--session");
  });

  it("объясняет, как восстановить отсутствующий seed", () => {
    const html = renderToStaticMarkup(
      <DemoPanel initialAvailability="missing" demoSession={false} />,
    );

    expect(html).toContain("Запустите seed");
    expect(html).not.toContain("Демо-препод");
  });
});

describe("demo API", () => {
  it("логин передаёт только выбранную роль", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ access_token: "a", refresh_token: "r" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await demoLogin("teacher", { apiBaseUrl: "http://api", fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://api/auth/demo-login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ role: "teacher" }),
      }),
    );
  });

  it("сброс авторизуется demo-токеном", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 200 }));

    await resetDemo("demo-token", { apiBaseUrl: "http://api", fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://api/auth/demo-reset",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer demo-token" }),
      }),
    );
  });
});
