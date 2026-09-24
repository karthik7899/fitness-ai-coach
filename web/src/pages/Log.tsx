import { type FormEvent, useEffect, useState } from "react";

import { api, type Exercise, type Plan, type PlanEntry, type Workout } from "../api";

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
    setReps(String(entry.reps));
    setWeight(entry.last_weight_kg === null ? "" : String(entry.last_weight_kg));
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
        is_warmup: isWarmup,
      });
      // Following a plan, the next set is usually the same again.
      if (!plan?.entries.some((e) => e.exercise_id === exerciseId)) setReps("");
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const nameOf = (id: number) => exercises.find((e) => e.id === id)?.name ?? `#${id}`;

  return (
    <div className="stack">
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
                      {entry.sets} × {entry.reps}
                      {entry.last_weight_kg !== null && ` · last ${entry.last_weight_kg} kg`}
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
