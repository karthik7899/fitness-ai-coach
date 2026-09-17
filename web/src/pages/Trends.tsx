import { useEffect, useMemo, useState } from "react";

import {
  api,
  type ExerciseRow,
  type LoadRow,
  type MuscleRow,
  type ProgressionRow,
} from "../api";
import BarChart from "../charts/BarChart";
import LineChart from "../charts/LineChart";
import { compact, mediumDate } from "../charts/format";

const SERIES_1 = "#3987e5";
const SERIES_2 = "#d95926";

const PRESETS = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "1 year", days: 365 },
];

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** ACWR read as a state, with an icon and a word so colour never carries it alone. */
function acwrState(acwr: number | null) {
  if (acwr == null) return { label: "No reading", tone: "muted", icon: "dash" as const };
  if (acwr < 0.8) return { label: "Detraining", tone: "warning", icon: "down" as const };
  if (acwr <= 1.3) return { label: "Steady build", tone: "good", icon: "check" as const };
  if (acwr <= 1.5) return { label: "Ramping fast", tone: "serious", icon: "up" as const };
  return { label: "Spike", tone: "critical", icon: "alert" as const };
}

function StateIcon({ icon }: { icon: "check" | "up" | "down" | "alert" | "dash" }) {
  const paths: Record<typeof icon, string> = {
    check: "M2 7 L5.5 10.5 L12 3",
    up: "M7 11 V3 M3 6.5 L7 2.5 L11 6.5",
    down: "M7 3 V11 M3 7.5 L7 11.5 L11 7.5",
    alert: "M7 2.5 V8 M7 10.5 V11.5",
    dash: "M3 7 H11",
  };
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" className="state-icon">
      <path d={paths[icon]} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Trends() {
  const [days, setDays] = useState(90);
  const [load, setLoad] = useState<LoadRow[]>([]);
  const [muscles, setMuscles] = useState<MuscleRow[]>([]);
  const [exercises, setExercises] = useState<ExerciseRow[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [progression, setProgression] = useState<ProgressionRow[]>([]);
  const [showTable, setShowTable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [start, end] = useMemo(() => {
    const today = new Date();
    const from = new Date();
    from.setDate(today.getDate() - days);
    return [iso(from), iso(today)];
  }, [days]);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.load(start, end), api.volume(start, end), api.exercisesWithHistory()])
      .then(([loadRows, volume, exerciseRows]) => {
        setLoad(loadRows);
        setMuscles(volume.by_muscle);
        setExercises(exerciseRows);
        setSelected((current) => current || exerciseRows[0]?.exercise || "");
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [start, end]);

  useEffect(() => {
    if (!selected) return;
    api
      .progression(selected, start, end)
      .then(setProgression)
      .catch((e) => setError(String(e)));
  }, [selected, start, end]);

  const latest = load.length ? load[load.length - 1] : null;
  const state = acwrState(latest?.acwr ?? null);

  const loadSeries = [
    {
      name: "Acute (7-day)",
      color: SERIES_1,
      points: load.map((r) => ({ date: r.date, value: r.acute_7d })),
    },
    {
      name: "Chronic (28-day)",
      color: SERIES_2,
      points: load.map((r) => ({ date: r.date, value: r.chronic_28d })),
    },
  ];

  const acwrSeries = [
    { name: "ACWR", color: SERIES_1, points: load.map((r) => ({ date: r.date, value: r.acwr })) },
  ];

  const e1rmSeries = [
    {
      name: selected,
      color: SERIES_1,
      points: progression.map((r) => ({ date: r.date, value: r.best_e1rm_kg })),
    },
  ];

  const muscleBars = muscles.map((m) => ({
    label: m.muscle.replace(/_/g, " "),
    value: Math.round(m.volume_kg),
    detail: `${m.working_sets} working sets`,
  }));

  if (error) return <p className="error">{error}</p>;

  return (
    <div className={`stack${loading ? " reloading" : ""}`}>
      <div className="filters">
        {PRESETS.map((p) => (
          <button
            key={p.days}
            className={p.days === days ? "chip active" : "chip"}
            onClick={() => setDays(p.days)}
          >
            {p.label}
          </button>
        ))}
        <button className="chip" onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Hide table" : "Table view"}
        </button>
      </div>

      <section>
        <h2>Readiness</h2>
        <div className="tiles">
          <div className="tile">
            <span className="label">Acute : chronic ratio</span>
            <span className="value">{latest?.acwr ?? "—"}</span>
            <span className={`state state-${state.tone}`}>
              <StateIcon icon={state.icon} /> {state.label}
            </span>
          </div>
          <div className="tile">
            <span className="label">Acute load (7d)</span>
            <span className="value">{latest?.acute_7d ?? "—"}</span>
            <span className="muted">arbitrary units</span>
          </div>
          <div className="tile">
            <span className="label">Chronic load (28d)</span>
            <span className="value">{latest?.chronic_28d ?? "—"}</span>
            <span className="muted">arbitrary units</span>
          </div>
        </div>
      </section>

      <section>
        <h2>Acute vs chronic load</h2>
        <LineChart series={loadSeries} height={230} format={(v) => v.toFixed(2)} />
      </section>

      <section>
        <h2>Acute:chronic ratio</h2>
        <LineChart
          series={acwrSeries}
          height={190}
          format={(v) => v.toFixed(2)}
          band={{ from: 0.8, to: 1.3, label: "steady build" }}
          area
        />
      </section>

      <section>
        <h2>Volume by muscle group</h2>
        <BarChart bars={muscleBars} color={SERIES_1} format={(v) => `${compact(v)} kg`} />
      </section>

      <section>
        <div className="section-head">
          <h2>Estimated 1RM</h2>
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {exercises.map((e) => (
              <option key={e.exercise} value={e.exercise}>
                {e.exercise}
              </option>
            ))}
          </select>
        </div>
        <LineChart
          series={e1rmSeries}
          height={220}
          format={(v) => `${v.toFixed(1)} kg`}
          area
          emptyMessage="No sets in the 1–12 rep range for this lift, so no 1RM estimate."
        />
      </section>

      {showTable && (
        <section>
          <h2>Data</h2>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Strength (t)</th>
                <th>Cardio (min)</th>
                <th>Acute 7d</th>
                <th>Chronic 28d</th>
                <th>ACWR</th>
              </tr>
            </thead>
            <tbody>
              {[...load].reverse().slice(0, 60).map((r) => (
                <tr key={r.date}>
                  <td>{mediumDate(r.date)}</td>
                  <td>{r.strength_tonnes.toFixed(2)}</td>
                  <td>{r.cardio_minutes.toFixed(0)}</td>
                  <td>{r.acute_7d ?? "—"}</td>
                  <td>{r.chronic_28d ?? "—"}</td>
                  <td>{r.acwr ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
