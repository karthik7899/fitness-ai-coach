import { type FormEvent, useRef, useState } from "react";

import { type Grounding, type Trace, streamChat } from "../api";

interface Turn {
  role: "user" | "assistant";
  text: string;
  tools: string[];
  correcting?: string[];
  grounding?: Grounding;
  trace?: Trace;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

const duration = (millis: number) =>
  millis < 1000 ? `${millis} ms` : `${(millis / 1000).toFixed(1)} s`;

function Verdict({ grounding }: { grounding: Grounding }) {
  const total = grounding.verified.length + grounding.unverified.length;
  if (total === 0) return null;
  if (grounding.ok) {
    return (
      <div className="verdict good">
        ✓ All {plural(total, "figure")} found in your data
        {grounding.retried ? ", after one correction" : ""}
      </div>
    );
  }
  return (
    <div className="verdict warning">
      ⚠ Not found in your data: {grounding.unverified.join(", ")}
    </div>
  );
}

function TraceView({ trace }: { trace: Trace }) {
  const models = trace.steps.filter((s) => s.kind === "model").length;
  const tools = trace.steps.filter((s) => s.kind === "tool").length;
  const totals = [plural(models, "model call"), plural(tools, "tool call")];
  if (trace.usage.total > 0) totals.push(`${trace.usage.total.toLocaleString()} tokens`);
  totals.push(duration(trace.total_millis));

  return (
    <details className="trace">
      <summary>How this was answered</summary>
      {trace.steps.map((step, i) => (
        <div key={i} className={step.failed ? "step failed" : "step"}>
          {[step.kind, step.label, step.detail, duration(step.millis)]
            .filter(Boolean)
            .join(" · ")}
          {step.failed ? "  (failed)" : ""}
        </div>
      ))}
      <div className="totals">{totals.join(" · ")}</div>
    </details>
  );
}

export default function Coach() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<number | null>(null);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || busy) return;

    setInput("");
    setBusy(true);
    setTurns((prev) => [
      ...prev,
      { role: "user", text: message, tools: [] },
      { role: "assistant", text: "", tools: [] },
    ]);

    const update = (patch: (turn: Turn) => Turn) =>
      setTurns((prev) => {
        const next = [...prev];
        next[next.length - 1] = patch(next[next.length - 1]);
        return next;
      });

    try {
      await streamChat(message, conversationId.current, (event) => {
        switch (event.type) {
          case "start":
            conversationId.current = event.conversation_id;
            break;
          case "token":
            update((t) => ({ ...t, text: t.text + event.text }));
            break;
          case "tool":
            update((t) => ({ ...t, tools: [...t.tools, event.name] }));
            break;
          case "retry":
            // The answer already streamed quoted figures the tools never
            // returned; the coach is rewriting it, so drop the draft.
            update((t) => ({ ...t, text: "", correcting: event.unverified }));
            break;
          case "grounding": {
            const { type: _, ...grounding } = event;
            update((t) => ({ ...t, grounding, correcting: undefined }));
            break;
          }
          case "trace": {
            const { type: _, ...trace } = event;
            update((t) => ({ ...t, trace }));
            break;
          }
          case "error":
            update((t) => ({ ...t, text: `${t.text}\n\n[${event.message}]` }));
            break;
        }
      });
    } catch (e) {
      update((t) => ({ ...t, text: `${t.text}\n\n[${String(e)}]` }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <section className="chat">
        {turns.length === 0 && (
          <p className="muted">
            Ask about your training. The coach queries the database directly — try
            “how has my squat moved this month?” or “am I ramping load too fast?”
          </p>
        )}
        {turns.map((turn, i) => (
          <div key={i} className={`turn ${turn.role}`}>
            {turn.tools.length > 0 && (
              <div className="tools">
                {turn.tools.map((name, j) => (
                  <span className="pill" key={j}>
                    {name}
                  </span>
                ))}
              </div>
            )}
            {turn.correcting && (
              <div className="verdict muted">
                Rechecking — {turn.correcting.join(", ")} did not match your data…
              </div>
            )}
            <div className="text">{turn.text || (busy ? "…" : "")}</div>
            {turn.grounding && <Verdict grounding={turn.grounding} />}
            {turn.trace && <TraceView trace={turn.trace} />}
          </div>
        ))}
      </section>

      <form onSubmit={send} className="row">
        <input
          value={input}
          placeholder="Ask your coach…"
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
