import { afterEach, describe, expect, it, vi } from "vitest";

import {
  QueueConnection,
  queueSocketUrl,
  type WebSocketLike,
} from "./queueConnection";

class FakeSocket implements WebSocketLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  open() {
    this.onopen?.(new Event("open"));
  }

  message(eventId: string) {
    this.onmessage?.({
      data: JSON.stringify({
          event_id: eventId,
          type: "queue.updated",
          session_id: "session-1",
          occurred_at: "2026-09-06T20:00:00Z",
      }),
    } as MessageEvent);
  }

  close() {
    this.onclose?.({} as CloseEvent);
  }
}

afterEach(() => vi.useRealTimers());

describe("QueueConnection", () => {
  it("строит ws/wss URL с access JWT", () => {
    expect(queueSocketUrl("session-1", "jwt", "https://queue.example/api")).toBe(
      "wss://queue.example/ws/sessions/session-1?token=jwt",
    );
  });

  it("дедуплицирует события с одним event_id", async () => {
    const socket = new FakeSocket();
    const update = vi.fn(async () => undefined);
    const connection = new QueueConnection({
      url: "ws://example/ws",
      onUpdate: update,
      socketFactory: () => socket,
    });

    connection.start();
    socket.open();
    socket.message("event-1");
    socket.message("event-1");
    await Promise.resolve();

    expect(update).toHaveBeenCalledTimes(1);
    connection.stop();
  });

  it("объединяет несколько событий во время загрузки в одно повторное обновление", async () => {
    const socket = new FakeSocket();
    let release: (() => void) | undefined;
    const update = vi.fn(
      () => new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    const connection = new QueueConnection({
      url: "ws://example/ws",
      onUpdate: update,
      socketFactory: () => socket,
    });

    connection.start();
    socket.open();
    socket.message("event-1");
    socket.message("event-2");
    socket.message("event-3");
    expect(update).toHaveBeenCalledTimes(1);

    release?.();
    await Promise.resolve();
    await Promise.resolve();
    expect(update).toHaveBeenCalledTimes(2);
    connection.stop();
  });

  it("при разрыве включает polling 5 секунд и выключает его после reconnect", async () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const update = vi.fn(async () => undefined);
    const connection = new QueueConnection({
      url: "ws://example/ws",
      onUpdate: update,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    connection.start();
    sockets[0].open();
    sockets[0].close();
    await Promise.resolve();
    expect(update).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(update).toHaveBeenCalledTimes(2);
    expect(sockets).toHaveLength(2);

    sockets[1].open();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(update).toHaveBeenCalledTimes(2);

    sockets[1].message("event-2");
    await Promise.resolve();
    expect(update).toHaveBeenCalledTimes(3);
    connection.stop();
  });
});
