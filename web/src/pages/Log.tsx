import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { api, type Exercise, type Plan, type PlanEntry, type Workout } from "../api";

/** Today's target in words, with which way it moved and why. */
function targetLine(entry: PlanEntry): string {
  const load =
    entry.target_weight_kg === null
      ? `${entry.target_reps} reps`
      : `${entry.target_weight_kg} kg × ${entry.target_reps}`;
  switch (entry.advice) {
    case "new":
      return `Today: ${entry.target_reps} reps, a weight you could lift ${entry.reps_max} times`;
    case "up":
      return entry.target_weight_kg === null
        ? "Today: top of the range last time, add load"
        : `Today: ${load}  ↑ up from last time`;
    case "repeat":
      return `Today: ${load} · beat last time`;
    case "down":
      return `Today: ${load}  ↓ lighter, to get back in the range`;
  }
}

/** A short beep and a buzz where the device allows, when rest is over. */
function signal() {
  try {
    const context = new AudioContext();
    const tone = context.createOscillator();
    tone.frequency.value = 880;
    tone.connect(context.destination);
    tone.start();
    tone.stop(context.currentTime + 0.4);
    tone.onended = () => context.close();
  } catch {
    // No audio: the timer reaching zero on screen still says it.
  }
  navigator.vibrate?.(400);
}

/** Counts down the rest after a set. Held as an end time, so it survives re-renders. */
function RestTimer({ endsAt, total, onChange }: {
  endsAt: number;
  total: number;
  onChange: (endsAt: number | null, total: number) => void;
}) {
  const [now, setNow] = useState(Date.now());
  const fired = useRef(false);

  useEffect(() => {
    fired.current = false;
    const tick = setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= endsAt && !fired.current) {
        fired.current = true;
        signal();
        onChange(null, 0);
      }
    }, 250);
    return () => clearInterval(tick);
  }, [endsAt, onChange]);

  const left = Math.max(0, endsAt - now);
  const seconds = Math.ceil(left / 1000);
  return (
    <div className="rest">
      <div className="card-head">
        <strong>
          Rest {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </strong>
        <span>
          <button className="link" onClick={() => onChange(endsAt + 30_000, total + 30_000)}>
            +30s
          </button>{" "}
          <button className="link" onClick={() => onChange(null, 0)}>
            skip
          </button>
        </span>
      </div>
      <div className="rest-bar">
        <div style={{ width: `${total ? (left / total) * 100 : 0}%` }} />
      </div>
    </div>
  );
}

// The local date, not toISOString's UTC one: east of Greenwich that is still
// yesterday for the first hours of the morning, and sets would land there.
const today = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

export default function Log() {
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [workout, setWorkout] = useState<Workout | null>(null);
  const [exerciseId, setExerciseId] = useState<number | null>(null);
  const [weight, setWeight] = useState("");
  const [reps, setReps] = useState("");
  const [isWarmup, setIsWarmup] = useState(false);
  const [rpe, setRpe] = useState("");
  const [rest, setRest] = useState<{ endsAt: number; total: number } | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    const created = await api.createWorkout(today());
    setWorkout(await api.workouts(1).then((all) => all.find((w) => w.id === created.id) ?? created));
    setPlan(await api.activePlan());
  };

  // Fill the form from the plan: its exercise, target reps, last weight.
  const choose = (entry: PlanEntry) => {
    if (entry.exercise_id === null) return;
    setExerciseId(entry.exercise_id);
    setReps(String(entry.target_reps));
    const weight = entry.target_weight_kg ?? entry.last_weight_kg;
    setWeight(weight === null ? "" : String(weight));
    setRpe("");
    setIsWarmup(false);
  };

  const finish = async () => {
    await api.finishPlan();
    setPlan(null);
  };

  useEffect(() => {
    api.exercises().then((list) => {
      setExercises(list);
      if (list.length) setExerciseId(list[0].id);
    });
    refresh().catch((e) => setError(String(e)));
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!workout || exerciseId === null) return;
    try {
      await api.addSet(workout.id, {
        exercise_id: exerciseId,
        weight_kg: weight ? Number(weight) : null,
        reps: reps ? Number(reps) : null,
        rpe: rpe ? Number(rpe) : null,
        is_warmup: isWarmup,
      });
      const planned = plan?.entries.find((e) => e.exercise_id === exerciseId);
      const seconds = isWarmup ? 60 : (planned?.rest_s ?? 120);
      setRest({ endsAt: Date.now() + seconds * 1000, total: seconds * 1000 });
      setRpe("");
      // Following a plan, the next set is usually the same again.
      if (!plan?.entries.some((e) => e.exercise_id === exerciseId)) setReps("");
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  // Stable, so the timer's interval is not torn down on every render.
  const onRest = useCallback(
    (endsAt: number | null, total: number) =>
      setRest(endsAt === null ? null : { endsAt, total }),
    [],
  );

  const nameOf = (id: number) => exercises.find((e) => e.id === id)?.name ?? `#${id}`;

  return (
    <div className="stack">
      {rest && <RestTimer endsAt={rest.endsAt} total={rest.total} onChange={onRest} />}

      {plan && (
        <section>
          <div className="card-head">
            <h2>{plan.template.name}</h2>
            <button className="link" onClick={finish}>
              finish
            </button>
          </div>
          <div className="plan">
            {plan.entries.map((entry) => {
              const complete = entry.done >= entry.sets;
              return (
                <button
                  key={entry.exercise}
                  className={`plan-row${entry.exercise_id === exerciseId ? " chosen" : ""}`}
                  onClick={() => choose(entry)}
                >
                  <span>
                    {entry.exercise}
                    <span className="muted small">
                      {" "}
                      {entry.sets} × {entry.reps_min}–{entry.reps_max}
                      {entry.exercise.toLowerCase() !== entry.planned.toLowerCase() &&
                        ` · for ${entry.planned}`}
                      {entry.last_weight_kg !== null && ` · last ${entry.last_weight_kg} kg`}
                    </span>
                    <span className={`target small${entry.advice === "up" ? " up" : ""}`}>
                      {targetLine(entry)}
                    </span>
                  </span>
                  <span className={complete ? "done" : "muted"}>
                    {complete ? "✓ " : ""}
                    {entry.done}/{entry.sets}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      <section>
        <h2>Log a set — {today()}</h2>
        <form onSubmit={submit} className="row">
          <select
            value={exerciseId ?? ""}
            onChange={(e) => setExerciseId(Number(e.target.value))}
          >
            {exercises.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </select>
          <input
            type="number"
            step="0.5"
            placeholder="kg"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
          />
          <input
            type="number"
            placeholder="reps"
            value={reps}
            onChange={(e) => setReps(e.target.value)}
          />
          {/* RPE 10 is nothing left, 8 is two reps in reserve. Optional, but it is
              what tells the progression rule a grind from an easy set. */}
          <select value={rpe} onChange={(e) => setRpe(e.target.value)} aria-label="RPE">
            <option value="">RPE</option>
            {["6", "7", "8", "9", "10"].map((v) => (
              <option key={v} value={v}>
                RPE {v}
              </option>
            ))}
          </select>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={isWarmup}
              onChange={(e) => setIsWarmup(e.target.checked)}
            />
            warmup
          </label>
          <button type="submit">Add set</button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>

      <section>
        <h2>Today</h2>
        {!workout || workout.sets.length === 0 ? (
          <p className="muted">No sets yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Exercise</th>
                <th>Weight</th>
                <th>Reps</th>
                <th>RPE</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {workout.sets.map((s) => (
                <tr key={s.id} className={s.is_warmup ? "muted" : ""}>
                  <td>{s.position}</td>
                  <td>{nameOf(s.exercise_id)}</td>
                  <td>{s.weight_kg ?? "—"}</td>
                  <td>{s.reps ?? "—"}</td>
                  <td>{s.rpe ?? "—"}</td>
                  <td>
                    <button
                      onClick={() => api.deleteSet(s.id).then(refresh)}
                      className="link"
                    >
                      remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
