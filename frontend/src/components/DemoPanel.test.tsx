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

  it("показывает обе роли и сброс только внутри demo-сессии", () => {
    const regular = renderToStaticMarkup(
      <DemoPanel initialAvailability="available" demoSession={false} />,
    );
    const demo = renderToStaticMarkup(
      <DemoPanel initialAvailability="available" demoSession />,
    );

    expect(regular).toContain("Демо-препод");
    expect(regular).toContain("Демо-студент");
    expect(regular).not.toContain("Сбросить демо");
    expect(demo).toContain("Сбросить демо");
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
