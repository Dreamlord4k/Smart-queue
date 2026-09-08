import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Settings } from "./Settings";

describe("Settings", () => {
  it("требует явного подтверждения перед удалением профиля", () => {
    const html = renderToStaticMarkup(<Settings accessToken="token" />);

    expect(html).toContain("Удалить мой профиль");
    expect(html).toContain("Я понимаю последствия и подтверждаю удаление");
    expect(html).toContain("Удалить профиль навсегда");
    expect(html).toContain("disabled");
  });

  it("не показывает удаление профиля в demo-сессии", () => {
    const html = renderToStaticMarkup(<Settings accessToken="token" demoMode />);

    expect(html).not.toContain("Удалить мой профиль");
    expect(html).not.toContain("Удалить профиль навсегда");
  });

  it("предупреждает преподавателя об удалении его сессий, но не студентов", () => {
    const html = renderToStaticMarkup(<Settings accessToken="token" role="teacher" />);

    expect(html).toContain("созданные вами сессии и их очереди");
    expect(html).toContain("Аккаунты студентов сохранятся");
    expect(html).toContain("Удалить профиль навсегда");
  });
});
