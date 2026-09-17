import { type FormEvent, useRef, useState } from "react";

import { streamChat } from "../api";

interface Turn {
  role: "user" | "assistant";
  text: string;
  tools: string[];
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
            <div className="text">{turn.text || (busy ? "…" : "")}</div>
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
