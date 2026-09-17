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
};

export type CoachEvent =
  | { type: "start"; conversation_id: number }
  | { type: "token"; text: string }
  | { type: "tool"; name: string; input: unknown }
  | { type: "error"; message: string }
  | { type: "done" };

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

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      for (const line of frame.split("\n")) {
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
