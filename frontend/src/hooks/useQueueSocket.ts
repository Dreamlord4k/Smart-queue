import { useEffect } from "react";

import { QueueConnection, queueSocketUrl } from "../realtime/queueConnection";

export function useQueueSocket(options: {
  sessionId: string;
  accessToken: string;
  apiBaseUrl?: string;
  onUpdate: () => Promise<void> | void;
}): void {
  const { sessionId, accessToken, apiBaseUrl, onUpdate } = options;

  useEffect(() => {
    const connection = new QueueConnection({
      url: queueSocketUrl(sessionId, accessToken, apiBaseUrl),
      onUpdate,
    });
    connection.start();
    return () => connection.stop();
  }, [accessToken, apiBaseUrl, onUpdate, sessionId]);
}
