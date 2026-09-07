import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (preference === "light") return "light";
  if (preference === "dark") return "dark";
  return systemDark ? "dark" : "light";
}

export function readThemePreference(
  storage: Pick<Storage, "getItem"> | null | undefined,
): ThemePreference {
  const raw = storage?.getItem(THEME_STORAGE_KEY);
  return raw === "light" || raw === "dark" || raw === "system" ? raw : "system";
}

export function applyResolvedTheme(
  target: { dataset: { theme?: string } } | null | undefined,
  theme: ResolvedTheme,
): void {
  if (!target) return;
  target.dataset.theme = theme;
}

function systemDarkNow(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function persistPreference(preference: ThemePreference): void {
  try {
    window.localStorage?.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Приватный режим: выбор живёт только до перезагрузки.
  }
}

export function useTheme(): {
  preference: ThemePreference;
  theme: ResolvedTheme;
  setPreference: (next: ThemePreference) => void;
} {
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    typeof window === "undefined" ? "system" : readThemePreference(window.localStorage),
  );
  const theme = resolveTheme(preference, systemDarkNow());

  useEffect(() => {
    if (typeof document !== "undefined") {
      applyResolvedTheme(document.documentElement, theme);
    }
    if (typeof window !== "undefined") {
      persistPreference(preference);
    }
  }, [preference, theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
  }, []);

  return { preference, theme, setPreference };
}
