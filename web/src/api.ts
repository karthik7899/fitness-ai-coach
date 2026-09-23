export interface Exercise {
  id: number;
  name: string;
  category: string | null;
  modality: string;
  primary_muscles: string[];
}

export interface SetEntry {
  id: number;
  exercise_id: number;
  position: number;
  reps: number | null;
  weight_kg: number | null;
  rpe: number | null;
  is_warmup: boolean;
}

export interface Workout {
  id: number;
  performed_on: string;
  notes: string | null;
  source: string;
  sets: SetEntry[];
}

export interface Summary {
  latest_metrics: Record<string, { metric: string; value: number; unit: string; date: string }>;
  load: { date: string; load_au: number; acute_7d: number; chronic_28d: number; acwr: number | null } | null;
  recent_workouts: { date: string; volume_kg: number; working_sets: number; exercises: number }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status}: ${await response.text()}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export interface LoadRow {
  date: string;
  strength_tonnes: number;
  cardio_minutes: number;
  load_au: number;
  acute_7d: number | null;
  chronic_28d: number | null;
  acwr: number | null;
}

export interface MuscleRow {
  muscle: string;
  volume_kg: number;
  working_sets: number;
}

export interface ExerciseRow {
  exercise: string;
  volume_kg: number;
  sessions: number;
}

export interface ProgressionRow {
  date: string;
  best_e1rm_kg: number | null;
  top_weight_kg: number | null;
  volume_kg: number;
  working_sets: number;
}

export interface GeminiSettings {
  configured: boolean;
  source: "ui" | "env" | null;
  hint: string | null;
  can_clear: boolean;
  model: string;
  model_source: "ui" | "env";
}

export interface IngestSettings {
  inbox_dir: string;
  watch_dirs: { path: string; exists: boolean }[];
  watch_source: "ui" | "env";
}

export interface SettingsPayload {
  gemini: GeminiSettings;
  ingest: IngestSettings;
}

export interface SaveResult extends SettingsPayload {
  verified: boolean;
  error: string | null;
}

const range = (start: string, end: string) => `start=${start}&end=${end}`;

export const api = {
  summary: () => request<Summary>("/metrics/summary"),
  load: (start: string, end: string) => request<LoadRow[]>(`/metrics/load?${range(start, end)}`),
  volume: (start: string, end: string) =>
    request<{ by_muscle: MuscleRow[]; by_day: unknown[] }>(`/metrics/volume?${range(start, end)}`),
  exercisesWithHistory: () => request<ExerciseRow[]>("/metrics/exercises"),
  progression: (name: string, start: string, end: string) =>
    request<ProgressionRow[]>(
      `/metrics/exercise/${encodeURIComponent(name)}?${range(start, end)}`,
    ),
  exercises: (search?: string) =>
    request<Exercise[]>(`/exercises${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  workouts: (limit = 20) => request<Workout[]>(`/workouts?limit=${limit}`),
  createWorkout: (performed_on: string) =>
    request<Workout>("/workouts", {
      method: "POST",
      body: JSON.stringify({ performed_on }),
    }),
  addSet: (workoutId: number, body: Partial<SetEntry> & { exercise_id: number }) =>
    request<SetEntry>(`/workouts/${workoutId}/sets`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteSet: (setId: number) => request<void>(`/sets/${setId}`, { method: "DELETE" }),

  settings: () => request<SettingsPayload>("/settings"),
  saveGemini: (body: { api_key?: string; model?: string }) =>
    request<SaveResult>("/settings/gemini", { method: "PUT", body: JSON.stringify(body) }),
  clearGemini: () => request<void>("/settings/gemini", { method: "DELETE" }),
  saveWatchDirs: (watch_dirs: string[]) =>
    request<SettingsPayload & { warning: string | null }>("/settings/ingest", {
      method: "PUT",
      body: JSON.stringify({ watch_dirs }),
    }),
  syncInbox: () =>
    request<{ directory: string; files: unknown[] }>("/sync/inbox", { method: "POST" }),

  inspectBackup: (file: File) => upload<BackupInfo>("/backup/inspect", file),
  restoreBackup: (file: File) =>
    upload<{ restored: BackupInfo; previous_database: string }>("/backup/restore", file),
};

export type BackupInfo = {
  workouts: number;
  sets: number;
  exercises: number;
  daily_metrics: number;
  earliest: string | null;
  latest: string | null;
  is_empty: boolean;
};

async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`/api${path}`, { method: "POST", body });
  if (!response.ok) {
    // The server explains what is wrong with the file; that detail is the
    // whole value of the message, so surface it rather than the status code.
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export type CoachEvent =
  | { type: "start"; conversation_id: number }
  | { type: "token"; text: string }
  | { type: "tool"; name: string; input: unknown }
  | { type: "retry"; unverified: string[] }
  | ({ type: "grounding" } & Grounding)
  | ({ type: "trace" } & Trace)
  | { type: "error"; message: string }
  | { type: "done" };

/** The harness's verdict on the final answer's figures. */
export interface Grounding {
  ok: boolean;
  verified: string[];
  unverified: string[];
  retried: boolean;
}

export interface TraceStep {
  kind: "model" | "tool" | "check" | "retry";
  label: string;
  detail: string;
  millis: number;
  failed: boolean;
}

export interface Trace {
  steps: TraceStep[];
  usage: { prompt: number; output: number; total: number };
  total_millis: number;
}

/** POST the message and read the SSE response body. EventSource is GET-only. */
export async function streamChat(
  message: string,
  conversationId: number | null,
  onEvent: (event: CoachEvent) => void,
): Promise<void> {
  const response = await fetch("/api/coach/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!response.body) throw new Error("No response stream from the coach.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames end on a blank line. The server emits CRLF, so match both.
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      for (const line of frame.split(/\r?\n/)) {
        if (!line.startsWith("data:")) continue;
        try {
          onEvent(JSON.parse(line.slice(5).trim()) as CoachEvent);
        } catch {
          // Ignore keep-alive and non-JSON frames.
        }
      }
    }
  }
}
