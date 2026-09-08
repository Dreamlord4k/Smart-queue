import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEMO_IDLE_TIMEOUT_MS,
  DEMO_LAST_ACTIVITY_KEY,
  DEMO_RESET_EVENT_KEY,
  startDemoActivityMonitor,
} from "./activity";

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

function storageEvent(key: string, newValue: string): Event {
  return Object.assign(new Event("storage"), { key, newValue });
}

describe("demo activity monitor", () => {
  afterEach(() => vi.useRealTimers());

  it("сбрасывает через 30 минут после последней активности, а не после входа", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-08T10:00:00Z"));
    const target = new EventTarget();
    const storage = new MemoryStorage();
    const onIdle = vi.fn();
    const stop = startDemoActivityMonitor({
      target,
      storage,
      onIdle,
      onExternalReset: vi.fn(),
    });

    vi.advanceTimersByTime(DEMO_IDLE_TIMEOUT_MS - 60_000);
    target.dispatchEvent(new Event("pointerdown"));
    vi.advanceTimersByTime(DEMO_IDLE_TIMEOUT_MS - 1);
    expect(onIdle).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onIdle).toHaveBeenCalledOnce();
    stop();
  });

  it("продлевает отсчёт активностью другой вкладки и принимает общий reset", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-08T10:00:00Z"));
    const target = new EventTarget();
    const storage = new MemoryStorage();
    const onIdle = vi.fn();
    const onExternalReset = vi.fn();
    const stop = startDemoActivityMonitor({ target, storage, onIdle, onExternalReset });

    vi.advanceTimersByTime(DEMO_IDLE_TIMEOUT_MS - 1_000);
    const sharedActivity = Date.now();
    target.dispatchEvent(storageEvent(DEMO_LAST_ACTIVITY_KEY, String(sharedActivity)));
    vi.advanceTimersByTime(1_001);
    expect(onIdle).not.toHaveBeenCalled();

    target.dispatchEvent(storageEvent(DEMO_RESET_EVENT_KEY, "reset:other-tab"));
    expect(onExternalReset).toHaveBeenCalledOnce();
    stop();
  });
});
