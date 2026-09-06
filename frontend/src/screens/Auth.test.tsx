import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { Login, loginUser, validateLoginInput } from "./Login";
import { Register, registerUser, validateRegisterInput } from "./Register";
import { emitAuthRoute } from "./AuthTabs";
import { decodeRoleFromToken, saveTokens } from "../auth/session";

function fakeJwt(role: string): string {
  const payload = btoa(JSON.stringify({ sub: "user-id", role }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `header.${payload}.signature`;
}

function okResponse(body: unknown): Response {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

function errorResponse(detail: string, status = 401): Response {
  return {
    ok: false,
    status,
    json: async () => ({ detail }),
  } as Response;
}

describe("decodeRoleFromToken", () => {
  it("читает роль студента и преподавателя из payload токена", () => {
    expect(decodeRoleFromToken(fakeJwt("student"))).toBe("student");
    expect(decodeRoleFromToken(fakeJwt("teacher"))).toBe("teacher");
  });

  it("возвращает null для битого токена", () => {
    expect(decodeRoleFromToken("not-a-token")).toBeNull();
    expect(decodeRoleFromToken(fakeJwt("admin"))).toBeNull();
  });
});

describe("saveTokens", () => {
  it("кладёт обе части пары в хранилище", () => {
    const storage = new Map<string, string>();
    saveTokens(
      {
        setItem: (key, value) => void storage.set(key, value),
        getItem: (key) => storage.get(key) ?? null,
        removeItem: (key) => void storage.delete(key),
      },
      { access_token: "access", refresh_token: "refresh", token_type: "bearer" },
    );

    expect(storage.get("access_token")).toBe("access");
    expect(storage.get("refresh_token")).toBe("refresh");
  });
});

describe("loginUser", () => {
  it("отправляет нормализованный email на POST /auth/login", async () => {
    const fetchImpl = vi.fn(async () => okResponse({ access_token: "a", refresh_token: "r" }));

    const pair = await loginUser(
      { email: "  Student@Example.com ", password: "secret123" },
      { apiBaseUrl: "http://api", fetchImpl: fetchImpl as typeof fetch },
    );

    expect(pair).toEqual({ access_token: "a", refresh_token: "r" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "student@example.com",
      password: "secret123",
    });
  });

  it("пробрасывает detail сервера при неверных данных", async () => {
    const fetchImpl = vi.fn(async () => errorResponse("Неверный email или пароль"));

    await expect(
      loginUser(
        { email: "a@b.c", password: "wrong" },
        { apiBaseUrl: "", fetchImpl: fetchImpl as typeof fetch },
      ),
    ).rejects.toThrow("Неверный email или пароль");
  });
});

describe("registerUser", () => {
  it("регистрирует студента с group_id", async () => {
    const fetchImpl = vi.fn(async () =>
      okResponse({ id: "1", email: "s@e.c", full_name: "Студент", role: "student", group_id: "g" }),
    );

    await registerUser(
      { email: "s@e.c", fullName: "Студент", password: "password1", role: "student", groupId: "g" },
      { apiBaseUrl: "", fetchImpl: fetchImpl as typeof fetch },
    );

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/auth/register");
    expect(JSON.parse(init.body as string)).toMatchObject({ role: "student", group_id: "g" });
  });

  it("регистрирует преподавателя без group_id и требует группу у студента", async () => {
    const fetchImpl = vi.fn(async () =>
      okResponse({ id: "2", email: "t@e.c", full_name: "Препод", role: "teacher", group_id: null }),
    );

    await registerUser(
      { email: "t@e.c", fullName: "Препод", password: "password1", role: "teacher" },
      { apiBaseUrl: "", fetchImpl: fetchImpl as typeof fetch },
    );

    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).not.toHaveProperty("group_id");

    await expect(
      registerUser(
        { email: "s@e.c", fullName: "Студент", password: "password1", role: "student" },
        { apiBaseUrl: "", fetchImpl: fetchImpl as typeof fetch },
      ),
    ).rejects.toThrow("Для студента обязательна группа");
  });
});

describe("формы входа и регистрации", () => {
  it("Login показывает поля email/пароль и кнопку", () => {
    const html = renderToStaticMarkup(<Login apiBaseUrl="" />);

    expect(html).toContain("Вход");
    expect(html).toContain('name="email"');
    expect(html).toContain('name="password"');
    expect(html).toContain("Войти");
  });

  it("Register показывает роль и поле группы для студента", () => {
    const html = renderToStaticMarkup(
      <Register
        apiBaseUrl=""
        initialGroups={[{ id: "group-1", name: "РИ-120001" }]}
      />,
    );

    expect(html).toContain("Регистрация");
    expect(html).toContain('name="role"');
    expect(html).toContain('name="group_id"');
    expect(html).toContain("РИ-120001");
    expect(html).toContain("Зарегистрироваться");
  });

  it("формы в стиле Material You: логотип и коралловая кнопка", () => {
    const html = renderToStaticMarkup(
      <>
        <Login apiBaseUrl="" />
        <Register apiBaseUrl="" />
      </>,
    );

    expect(html.match(/Умная очередь/g)).toHaveLength(2);
    expect(html).toContain("auth-submit");
  });

  it("карточка выше центра, логотип крупный", () => {
    const html = renderToStaticMarkup(<Login apiBaseUrl="" />);

    expect(html).toContain("auth-card");
    expect(html).toContain("auth-logo");
  });
});

describe("переключатель Вход/Регистрация", () => {
  it("подсвечивает активную вкладку входа", () => {
    const html = renderToStaticMarkup(<Login apiBaseUrl="" />);

    expect(html).toContain("auth-tabs");
    expect(html.match(/auth-tab--active/g)).toHaveLength(1);
    expect(html).toContain('auth-tab--active" aria-pressed="true">Вход<');
  });

  it("подсвечивает активную вкладку регистрации", () => {
    const html = renderToStaticMarkup(<Register apiBaseUrl="" />);

    expect(html.match(/auth-tab--active/g)).toHaveLength(1);
    expect(html).toContain('auth-tab--active" aria-pressed="true">Регистрация<');
  });

  it("клик шлёт событие навигации без смены пропсов", () => {
    const seen: unknown[] = [];
    const holder = globalThis as { window?: unknown };
    const previous = holder.window;
    holder.window = {
      dispatchEvent: (event: Event) => {
        seen.push((event as CustomEvent).detail);
        return true;
      },
    };
    try {
      emitAuthRoute("/register");
    } finally {
      if (previous === undefined) {
        delete holder.window;
      } else {
        holder.window = previous;
      }
    }

    expect(seen).toEqual(["/register"]);
  });
});

describe("валидация после нажатия", () => {
  it("login: email без @ и пустой пароль дают подсказки", () => {
    expect(validateLoginInput({ email: "userexample.com", password: "secret" })).toEqual({
      email: "В email не хватает @ — проверьте адрес",
    });
    expect(validateLoginInput({ email: "", password: "" })).toEqual({
      email: "Введите email",
      password: "Введите пароль",
    });
    expect(validateLoginInput({ email: "a@b.c", password: "secret" })).toEqual({});
  });

  it("register: пустые поля и короткий пароль дают подсказки", () => {
    expect(
      validateRegisterInput({ email: "a@b.c", fullName: "", password: "123", role: "teacher" }),
    ).toEqual({
      fullName: "Представьтесь — введите ФИО",
      password: "Пароль короткий — минимум 8 символов",
    });
    expect(
      validateRegisterInput({
        email: "a@b.c",
        fullName: "Студент",
        password: "password1",
        role: "student",
        groupId: "",
      }),
    ).toEqual({ groupId: "Выберите группу" });
    expect(
      validateRegisterInput({
        email: "a@b.c",
        fullName: "Студент",
        password: "password1",
        role: "student",
        groupId: "g",
      }),
    ).toEqual({});
  });
});
