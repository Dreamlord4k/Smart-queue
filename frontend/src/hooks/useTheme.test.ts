import { describe, expect, it } from "vitest";

import {
  applyResolvedTheme,
  readThemePreference,
  resolveTheme,
} from "./useTheme";

function fakeStorage(value: string | null) {
  return { getItem: () => value };
}

describe("resolveTheme", () => {
  it("явный выбор побеждает системный", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("system следует за системой", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

describe("readThemePreference", () => {
  it("читает сохранённый выбор и отбрасывает мусор", () => {
    expect(readThemePreference(fakeStorage("dark"))).toBe("dark");
    expect(readThemePreference(fakeStorage("light"))).toBe("light");
    expect(readThemePreference(fakeStorage("midnight"))).toBe("system");
    expect(readThemePreference(fakeStorage(null))).toBe("system");
    expect(readThemePreference(null)).toBe("system");
  });
});

describe("applyResolvedTheme", () => {
  it("выставляет data-theme без падения на пустом таргете", () => {
    const target = { dataset: {} as { theme?: string } };
    applyResolvedTheme(target, "dark");
    expect(target.dataset.theme).toBe("dark");
    applyResolvedTheme(null, "light");
    applyResolvedTheme(undefined, "light");
  });
});
