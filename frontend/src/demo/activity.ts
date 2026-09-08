export const DEMO_IDLE_TIMEOUT_MS = 30 * 60 * 1000;
export const DEMO_LAST_ACTIVITY_KEY = "smart_queue_demo_last_activity";
export const DEMO_RESET_EVENT_KEY = "smart_queue_demo_reset_event";

export interface DemoSharedStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

interface DemoEventTarget {
  addEventListener(type: string, listener: EventListener): void;
  removeEventListener(type: string, listener: EventListener): void;
}

interface DemoActivityMonitorOptions {
  target: DemoEventTarget;
  storage: DemoSharedStorage;
  onIdle: () => void;
  onExternalReset: () => void;
  now?: () => number;
}

function storedTimestamp(storage: DemoSharedStorage): number | null {
  const value = Number(storage.getItem(DEMO_LAST_ACTIVITY_KEY));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function signalDemoReset(
  storage: DemoSharedStorage,
  now: () => number = Date.now,
): void {
  const occurredAt = now();
  storage.setItem(DEMO_LAST_ACTIVITY_KEY, String(occurredAt));
  storage.setItem(DEMO_RESET_EVENT_KEY, `${occurredAt}:${Math.random().toString(36).slice(2)}`);
}

export function startDemoActivityMonitor({
  target,
  storage,
  onIdle,
  onExternalReset,
  now = Date.now,
}: DemoActivityMonitorOptions): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;

  const schedule = (lastActivity: number) => {
    if (timer !== undefined) clearTimeout(timer);
    const remaining = Math.max(0, DEMO_IDLE_TIMEOUT_MS - (now() - lastActivity));
    timer = setTimeout(onIdle, remaining);
  };

  const recordActivity: EventListener = () => {
    const occurredAt = now();
    storage.setItem(DEMO_LAST_ACTIVITY_KEY, String(occurredAt));
    schedule(occurredAt);
  };

  const receiveSharedState: EventListener = (event) => {
    const storageEvent = event as Event & { key?: string | null; newValue?: string | null };
    if (storageEvent.key === DEMO_LAST_ACTIVITY_KEY && storageEvent.newValue) {
      const occurredAt = Number(storageEvent.newValue);
      if (Number.isFinite(occurredAt)) schedule(occurredAt);
    }
    if (storageEvent.key === DEMO_RESET_EVENT_KEY && storageEvent.newValue) {
      onExternalReset();
    }
  };

  const initialActivity = storedTimestamp(storage) ?? now();
  if (storedTimestamp(storage) === null) {
    storage.setItem(DEMO_LAST_ACTIVITY_KEY, String(initialActivity));
  }
  schedule(initialActivity);

  for (const eventName of ["pointerdown", "keydown", "touchstart"]) {
    target.addEventListener(eventName, recordActivity);
  }
  target.addEventListener("storage", receiveSharedState);

  return () => {
    if (timer !== undefined) clearTimeout(timer);
    for (const eventName of ["pointerdown", "keydown", "touchstart"]) {
      target.removeEventListener(eventName, recordActivity);
    }
    target.removeEventListener("storage", receiveSharedState);
  };
}
