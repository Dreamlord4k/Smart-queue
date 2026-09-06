export interface QueueEvent {
  event_id: string;
  type: string;
  session_id: string;
  occurred_at: string;
}

export interface WebSocketLike {
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(): void;
}

export type SocketFactory = (url: string) => WebSocketLike;

export function queueSocketUrl(
  sessionId: string,
  accessToken: string,
  apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "",
): string {
  const fallbackOrigin =
    typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const url = new URL(`/ws/sessions/${sessionId}`, apiBaseUrl || fallbackOrigin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", accessToken);
  return url.toString();
}

export class QueueConnection {
  private socket: WebSocketLike | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;
  private refreshing = false;
  private refreshQueued = false;
  private readonly seenEvents = new Set<string>();

  constructor(
    private readonly options: {
      url: string;
      onUpdate: () => Promise<void> | void;
      socketFactory?: SocketFactory;
      pollIntervalMs?: number;
      reconnectDelayMs?: number;
    },
  ) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.stopPolling();
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  private connect(): void {
    if (this.stopped) return;
    const factory = this.options.socketFactory ?? ((url: string) => new WebSocket(url));
    try {
      const socket = factory(this.options.url);
      this.socket = socket;
      socket.onopen = () => {
        if (this.stopped || this.socket !== socket) return;
        this.stopPolling();
      };
      socket.onmessage = (message) => {
        if (this.stopped || this.socket !== socket) return;
        const event = this.readEvent(message.data);
        if (event && this.seenEvents.has(event.event_id)) return;
        if (event) {
          this.seenEvents.add(event.event_id);
          if (this.seenEvents.size > 100) {
            this.seenEvents.delete(this.seenEvents.values().next().value as string);
          }
        }
        void this.refresh();
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (this.socket === socket) this.socket = null;
        if (this.stopped) return;
        this.startPolling();
        this.scheduleReconnect();
      };
    } catch {
      this.startPolling();
      this.scheduleReconnect();
    }
  }

  private readEvent(data: unknown): QueueEvent | null {
    try {
      const event = JSON.parse(String(data)) as Partial<QueueEvent>;
      return typeof event.event_id === "string" ? event as QueueEvent : null;
    } catch {
      return null;
    }
  }

  private startPolling(): void {
    if (this.pollTimer !== null) return;
    void this.refresh();
    this.pollTimer = setInterval(
      () => void this.refresh(),
      this.options.pollIntervalMs ?? 5_000,
    );
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.pollTimer = null;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.stopped) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.options.reconnectDelayMs ?? 2_000);
  }

  private async refresh(): Promise<void> {
    if (this.stopped) return;
    if (this.refreshing) {
      this.refreshQueued = true;
      return;
    }
    this.refreshing = true;
    try {
      await this.options.onUpdate();
    } finally {
      this.refreshing = false;
      if (this.refreshQueued) {
        this.refreshQueued = false;
        void this.refresh();
      }
    }
  }
}
