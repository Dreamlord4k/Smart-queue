export const UNIVERSITY_TIME_ZONE = "Asia/Yekaterinburg";
export const UNIVERSITY_TIME_NOTE = "время местное";

const universityTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: UNIVERSITY_TIME_ZONE,
});

export function formatUniversityTime(value: string | Date): string {
  const instant = value instanceof Date ? value : new Date(value);
  return universityTimeFormatter.format(instant);
}

export function formatUniversitySessionStart(date: string, startTime: string): string {
  const localInstant = new Date(`${date}T${startTime.slice(0, 8)}+05:00`);
  return `${date} в ${formatUniversityTime(localInstant)}`;
}
