import "./Auth.css";

export type AuthTabId = "login" | "register";
export type AuthRoutePath = "/login" | "/register";

export const AUTH_ROUTE_EVENT = "auth:route";

export function emitAuthRoute(route: AuthRoutePath): void {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent<AuthRoutePath>(AUTH_ROUTE_EVENT, { detail: route }));
  }
}

const TABS: Array<{ id: AuthTabId; label: string; route: AuthRoutePath }> = [
  { id: "login", label: "Вход", route: "/login" },
  { id: "register", label: "Регистрация", route: "/register" },
];

export function AuthTabs({ active }: { active: AuthTabId }) {
  return (
    <div className="auth-tabs" role="group" aria-label="Вход или регистрация">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={tab.id === active ? "auth-tab auth-tab--active" : "auth-tab"}
          aria-pressed={tab.id === active}
          onClick={() => emitAuthRoute(tab.route)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
