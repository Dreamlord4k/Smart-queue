export type SessionStatus =
  | "planned"
  | "active"
  | "paused"
  | "closed"
  | "cancelled";

export type QueueStatus = "waiting" | "called" | "done" | "skipped" | "absent";

export interface SessionSummary {
  id: string;
  teacher_id: string;
  course_name: string;
  room: string;
  date: string;
  start_time: string;
  duration_default: number;
  capacity: number;
  status: SessionStatus;
  frozen: boolean;
  created_at: string;
}

export interface SessionReport {
  accepted_count: number;
  skipped_count: number;
  average_service_seconds: number | null;
  planned_duration_seconds: number;
  actual_duration_seconds: number | null;
  average_eta_error_seconds: number | null;
}

export interface SessionUpdate extends SessionSummary {
  report: SessionReport | null;
}

export interface GroupStudent {
  id: string;
  full_name: string;
  email: string;
}

export interface GroupWithStudents {
  id: string;
  name: string;
  students: GroupStudent[];
}

export interface QueueEntryState {
  id: string;
  student_id: string;
  student_name: string;
  position: number;
  status: QueueStatus;
  channel: number | null;
  called_at: string | null;
  locked: boolean;
  lock_reason: string | null;
  absence_reason: string | null;
  eta_start: string | null;
  eta_end: string | null;
}

export interface QueueState {
  session_id: string;
  entries: QueueEntryState[];
}

export interface CreateSessionInput {
  course_name: string;
  room: string;
  date: string;
  start_time: string;
  duration_default: number;
  capacity: number;
  group_ids: string[];
  student_ids: string[];
}

export interface CreatedSession extends SessionSummary {
  queue: Array<{
    id: string;
    student_id: string;
    position: number;
    status: QueueStatus;
  }>;
}
