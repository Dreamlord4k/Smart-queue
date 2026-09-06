import { describe, expect, it, vi } from "vitest";

import {
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  fetchWithSession,
  refreshStoredAccessToken,
  type TokenStorage,
} from "./session";

function memoryStorage(values: Record<string, string>): TokenStorage {
  const data = new Map(Object.entries(values));
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

describe("refresh-сессия", () => {
  it("обновляет access при запуске, сохраняя refresh", async () => {
    const storage = memoryStorage({ [REFRESH_TOKEN_KEY]: "refresh-1" });
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ access_token: "access-2", token_type: "bearer" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      refreshStoredAccessToken({ apiBaseUrl: "http://api", storage, fetchImpl }),
    ).resolves.toBe("access-2");
    expect(storage.getItem(ACCESS_TOKEN_KEY)).toBe("access-2");
    expect(storage.getItem(REFRESH_TOKEN_KEY)).toBe("refresh-1");
  });

  it("после 401 обновляет access и повторяет исходный запрос один раз", async () => {
    const storage = memoryStorage({
      [ACCESS_TOKEN_KEY]: "access-old",
      [REFRESH_TOKEN_KEY]: "refresh-1",
    });
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "access-new" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    const response = await fetchWithSession("/protected", {}, {
      apiBaseUrl: "http://api",
      storage,
      fetchImpl,
    });

    expect(response.status).toBe(200);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(fetchImpl.mock.calls[0][1]?.headers).toMatchObject({
      Authorization: "Bearer access-old",
    });
    expect(fetchImpl.mock.calls[2][1]?.headers).toMatchObject({
      Authorization: "Bearer access-new",
    });
  });

  it("очищает оба токена при недействительном refresh", async () => {
    const storage = memoryStorage({
      [ACCESS_TOKEN_KEY]: "expired",
      [REFRESH_TOKEN_KEY]: "invalid",
    });
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "Недействительный refresh-токен" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(refreshStoredAccessToken({ storage, fetchImpl })).rejects.toThrow(
      "Недействительный refresh-токен",
    );
    expect(storage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
    expect(storage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });
});
