import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("рендерит переключатель с текущим состоянием", () => {
    const html = renderToStaticMarkup(<ThemeToggle />);

    expect(html).toContain('role="switch"');
    expect(html).toContain("Тёмная тема");
    // Без окна считаем тему светлой.
    expect(html).toContain('aria-checked="false"');
    expect(html).toContain("Светлая");
  });
});
