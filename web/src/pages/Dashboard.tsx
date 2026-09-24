import { useEffect, useState } from "react";

import { api, type Summary, type Template } from "../api";

const METRIC_LABELS: Record<string, string> = {
  steps: "Steps",
  sleep_minutes: "Sleep",
  resting_hr: "Resting HR",
  hrv_ms: "HRV",
  active_minutes: "Active",
  body_weight_kg: "Bodyweight",
};

function formatMetric(metric: string, value: number): string {
  if (metric === "sleep_minutes") {
    const hours = Math.floor(value / 60);
    return `${hours}h ${Math.round(value % 60)}m`;
  }
  return metric === "steps" ? value.toLocaleString() : `${value}`;
}

export default function Dashboard({ onStart }: { onStart: () => void }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.summary().then(setSummary).catch((e) => setError(String(e)));
    api.templates().then(setTemplates).catch((e) => setError(String(e)));
    api.activePlan().then((plan) => setActive(plan?.template.id ?? null)).catch(() => {});
  }, []);

  const start = async (id: string) => {
    setStarting(true);
    try {
      await api.startTemplate(id);
      onStart();
    } catch (e) {
      setError(String(e));
      setStarting(false);
    }
  };

  if (error) return <p className="error">{error}</p>;
  if (!summary) return <p className="muted">Loading…</p>;

  const metrics = Object.values(summary.latest_metrics);

  return (
    <div className="stack">
      {templates.length > 0 && (
        <section>
          <h2>Workouts by body part</h2>
          <div className="cards">
            {templates.map((t) => (
              <div className="card" key={t.id}>
                <div className="card-head">
                  <div>
                    <strong>{t.name}</strong>
                    <div className="muted small">{t.about}</div>
                  </div>
                  <button onClick={() => start(t.id)} disabled={starting}>
                    {t.id === active ? "Continue" : "Start"}
                  </button>
                </div>
                <div className="muted small">
                  {t.exercises.map((e) => `${e.exercise} ${e.sets}×${e.reps_min}–${e.reps_max}`).join(" · ")}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2>Latest wellness</h2>
        {metrics.length === 0 ? (
          <p className="muted">
            No watch data yet. Sync a Health Connect export to populate this.
          </p>
        ) : (
          <div className="tiles">
            {metrics.map((m) => (
              <div className="tile" key={m.metric}>
                <span className="label">{METRIC_LABELS[m.metric] ?? m.metric}</span>
                <span className="value">{formatMetric(m.metric, m.value)}</span>
                <span className="muted">{m.date}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2>Training load</h2>
        {summary.load ? (
          <div className="tiles">
            <div className="tile">
              <span className="label">Acute (7d)</span>
              <span className="value">{summary.load.acute_7d}</span>
            </div>
            <div className="tile">
              <span className="label">Chronic (28d)</span>
              <span className="value">{summary.load.chronic_28d}</span>
            </div>
            <div className="tile">
              <span className="label">ACWR</span>
              <span className="value">{summary.load.acwr ?? "—"}</span>
            </div>
          </div>
        ) : (
          <p className="muted">No load computed yet.</p>
        )}
      </section>

      <section>
        <h2>Recent sessions</h2>
        {summary.recent_workouts.length === 0 ? (
          <p className="muted">Nothing logged yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Volume (kg)</th>
                <th>Working sets</th>
                <th>Exercises</th>
              </tr>
            </thead>
            <tbody>
              {summary.recent_workouts.map((w) => (
                <tr key={w.date}>
                  <td>{w.date}</td>
                  <td>{w.volume_kg.toLocaleString()}</td>
                  <td>{w.working_sets}</td>
                  <td>{w.exercises}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
