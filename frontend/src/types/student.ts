import type { QueueStatus } from "../screens/MyQueues";

export interface PublicGroup {
  id: string;
  name: string;
}

export interface StudentQueueEntry {
  id: string;
  student_id: string;
  student_name: string;
  position: number;
  status: QueueStatus;
  channel: number | null;
  locked: boolean;
  lock_reason: string | null;
  absence_reason: string | null;
  eta_start: string | null;
  eta_end: string | null;
}

export interface StudentQueueState {
  session_id: string;
  frozen: boolean;
  entries: StudentQueueEntry[];
}

export type QueuePlacement = "before" | "after";

export interface LockResult {
  id: string;
  session_id: string;
  status: QueueStatus;
  locked: boolean;
  lock_reason: string | null;
  absence_reason: string | null;
}

export interface AbsenceResult {
  id: string;
  session_id: string;
  status: QueueStatus;
  absence_reason: string | null;
}
