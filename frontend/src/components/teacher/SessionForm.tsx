import { useMemo, useState, type FormEvent } from "react";

import type {
  CreateSessionInput,
  GroupWithStudents,
} from "../../types/teacher";

interface SessionFormProps {
  groups: GroupWithStudents[];
  pending?: boolean;
  onCreate: (input: CreateSessionInput) => Promise<void> | void;
}

function toggle(values: string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}

export function SessionForm({ groups, pending = false, onCreate }: SessionFormProps) {
  const [courseName, setCourseName] = useState("");
  const [room, setRoom] = useState("");
  const [date, setDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [duration, setDuration] = useState(15);
  const [capacity, setCapacity] = useState(1);
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [studentIds, setStudentIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");

  const students = useMemo(() => {
    const unique = new Map(
      groups.flatMap((group) => group.students).map((student) => [student.id, student]),
    );
    const query = search.trim().toLocaleLowerCase("ru-RU");
    return [...unique.values()].filter(
      (student) =>
        !query ||
        student.full_name.toLocaleLowerCase("ru-RU").includes(query) ||
        student.email.toLocaleLowerCase("ru-RU").includes(query),
    );
  }, [groups, search]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onCreate({
      course_name: courseName.trim(),
      room: room.trim(),
      date,
      start_time: startTime,
      duration_default: duration,
      capacity,
      group_ids: groupIds,
      student_ids: studentIds,
    });
  }

  return (
    <form className="teacher-form" onSubmit={submit} aria-label="Новая сессия">
      <div className="teacher-form__grid">
        <label>
          <span>Предмет</span>
          <input required value={courseName} onChange={(e) => setCourseName(e.target.value)} />
        </label>
        <label>
          <span>Аудитория</span>
          <input required value={room} onChange={(e) => setRoom(e.target.value)} />
        </label>
        <label>
          <span>Дата</span>
          <input required type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          <span>Начало</span>
          <input required type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
        </label>
        <label>
          <span>Минут на студента</span>
          <input
            required
            min={1}
            type="number"
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
          />
        </label>
        <label>
          <span>Параллельных каналов</span>
          <input
            required
            min={1}
            type="number"
            value={capacity}
            onChange={(e) => setCapacity(Number(e.target.value))}
          />
        </label>
      </div>

      <fieldset>
        <legend>Добавить группы целиком</legend>
        <div className="teacher-checks">
          {groups.map((group) => (
            <label key={group.id}>
              <input
                type="checkbox"
                checked={groupIds.includes(group.id)}
                onChange={() => setGroupIds(toggle(groupIds, group.id))}
              />
              {group.name} ({group.students.length})
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Или выбрать отдельных студентов</legend>
        <input
          type="search"
          placeholder="Поиск по имени или email"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="teacher-checks teacher-checks--students">
          {students.map((student) => (
            <label key={student.id}>
              <input
                type="checkbox"
                checked={studentIds.includes(student.id)}
                onChange={() => setStudentIds(toggle(studentIds, student.id))}
              />
              {student.full_name} ({student.email})
            </label>
          ))}
        </div>
      </fieldset>

      <button className="teacher-button teacher-button--primary" disabled={pending}>
        {pending ? "Создаём…" : "Создать сессию"}
      </button>
    </form>
  );
}
