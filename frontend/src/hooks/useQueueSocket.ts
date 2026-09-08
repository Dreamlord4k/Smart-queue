import { useEffect } from "react";

import { QueueConnection, queueSocketUrl } from "../realtime/queueConnection";

export function useQueueSocket(options: {
  sessionId: string;
  accessToken: string;
  apiBaseUrl?: string;
  onUpdate: () => Promise<void> | void;
  enabled?: boolean;
}): void {
  const { sessionId, accessToken, apiBaseUrl, onUpdate, enabled = true } = options;

  useEffect(() => {
    if (!enabled) return;
    const connection = new QueueConnection({
      url: queueSocketUrl(sessionId, accessToken, apiBaseUrl),
      onUpdate,
    });
    connection.start();
    return () => connection.stop();
  }, [accessToken, apiBaseUrl, enabled, onUpdate, sessionId]);
}
