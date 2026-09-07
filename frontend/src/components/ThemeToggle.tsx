import { useTheme } from "../hooks/useTheme";

export function ThemeToggle() {
  const { theme, setPreference } = useTheme();
  const dark = theme === "dark";

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Тёмная тема"
      className="theme-toggle"
      onClick={() => setPreference(dark ? "light" : "dark")}
    >
      <span className="theme-toggle__knob" aria-hidden="true" />
      <span className="theme-toggle__label">{dark ? "Тёмная" : "Светлая"}</span>
    </button>
  );
}
