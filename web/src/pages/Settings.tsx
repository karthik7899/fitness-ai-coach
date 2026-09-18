import { type FormEvent, useEffect, useState } from "react";

import { api, type SettingsPayload } from "../api";

const KEY_URL = "https://aistudio.google.com/apikey";

function WatchFolders({
  current,
  onSaved,
}: {
  current: SettingsPayload;
  onSaved: (s: SettingsPayload) => void;
}) {
  const [draft, setDraft] = useState(
    current.ingest.watch_dirs.map((d) => d.path).join("\n"),
  );
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; message: string } | null>(null);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setNote(null);
    try {
      const saved = await api.saveWatchDirs(draft.split("\n"));
      onSaved(saved);
      setNote(
        saved.warning
          ? { ok: false, message: saved.warning }
          : { ok: true, message: "Saved. These folders are read every two minutes." },
      );
    } catch (e) {
      setNote({ ok: false, message: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const importNow = async () => {
    setBusy(true);
    try {
      const run = await api.syncInbox();
      setNote({ ok: true, message: `Imported ${run.files.length} file(s).` });
    } catch (e) {
      setNote({ ok: false, message: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>Automatic import</h2>
      <p className="muted">
        Point these at the folders FitNotes and Gadgetbridge already back up to, and their
        data imports itself. The folders are only ever read — files stay where their own app
        put them. Anything dropped in <code>{current.ingest.inbox_dir}</code> is imported too.
      </p>

      <form onSubmit={save} className="stack-tight">
        <textarea
          rows={3}
          spellCheck={false}
          placeholder={"/storage/emulated/0/FitNotes\n/storage/emulated/0/Gadgetbridge"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <span className="muted" style={{ fontSize: 12 }}>
          One folder per line.
          {current.ingest.watch_source === "env" && " Currently taken from .env."}
        </span>
        <div className="row">
          <button type="submit" disabled={busy}>
            Save folders
          </button>
          <button type="button" className="link" onClick={importNow} disabled={busy}>
            import now
          </button>
        </div>
      </form>

      {current.ingest.watch_dirs.length > 0 && (
        <table>
          <tbody>
            {current.ingest.watch_dirs.map((d) => (
              <tr key={d.path}>
                <td>
                  <code>{d.path}</code>
                </td>
                <td>
                  <span className={d.exists ? "state state-good" : "state state-warning"}>
                    {d.exists ? "found" : "not found yet"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {note && <p className={note.ok ? "ok" : "error"}>{note.message}</p>}
    </section>
  );
}

export default function Settings() {
  const [current, setCurrent] = useState<SettingsPayload | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const load = () =>
    api
      .settings()
      .then((s) => {
        setCurrent(s);
        setModel(s.gemini.model);
      })
      .catch((e) => setResult({ ok: false, message: String(e) }));

  useEffect(() => {
    load();
  }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const saved = await api.saveGemini({
        api_key: apiKey.trim() || undefined,
        model: model.trim() || undefined,
      });
      setCurrent(saved);
      setApiKey("");
      setResult(
        saved.verified
          ? { ok: true, message: `Saved and verified against ${saved.gemini.model}.` }
          : { ok: false, message: saved.error ?? "Saved, but the key could not be verified." },
      );
    } catch (e) {
      setResult({ ok: false, message: String(e) });
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      await api.clearGemini();
      await load();
      setResult({ ok: true, message: "Key removed." });
    } finally {
      setBusy(false);
    }
  };

  if (!current) return <p className="muted">Loading…</p>;

  const { gemini } = current;

  return (
    <div className="stack">
      <section>
        <h2>Coach</h2>
        <p className="muted">
          The coach needs a Gemini API key. Get a free one at{" "}
          <a href={KEY_URL} target="_blank" rel="noreferrer">
            aistudio.google.com/apikey
          </a>
          . It is stored in your local database, never sent anywhere but Google.
        </p>

        <div className="tiles">
          <div className="tile">
            <span className="label">API key</span>
            <span className="value">{gemini.configured ? gemini.hint : "Not set"}</span>
            <span className="muted">
              {gemini.source === "ui"
                ? "entered here"
                : gemini.source === "env"
                  ? "from .env"
                  : "required for chat"}
            </span>
          </div>
          <div className="tile">
            <span className="label">Model</span>
            <span className="value" style={{ fontSize: "1rem" }}>
              {gemini.model}
            </span>
            <span className="muted">
              {gemini.model_source === "ui" ? "entered here" : "default"}
            </span>
          </div>
        </div>
      </section>

      <section>
        <h2>{gemini.configured ? "Replace key" : "Add key"}</h2>
        <form onSubmit={save} className="stack-tight">
          <input
            type="password"
            autoComplete="off"
            placeholder={gemini.configured ? "Enter a new key to replace it" : "Paste your API key"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <input
            type="text"
            placeholder="Model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <div className="row">
            <button type="submit" disabled={busy || (!apiKey.trim() && model === gemini.model)}>
              {busy ? "Checking…" : "Save and verify"}
            </button>
            {gemini.can_clear && (
              <button type="button" className="link" onClick={clear} disabled={busy}>
                remove key
              </button>
            )}
          </div>
        </form>

        {result && (
          <p className={result.ok ? "ok" : "error"}>{result.message}</p>
        )}

        {gemini.source === "env" && (
          <p className="muted">
            A key from <code>.env</code> is in use. Saving one here overrides it; removing that
            one means editing <code>.env</code>.
          </p>
        )}
      </section>

      <WatchFolders current={current} onSaved={setCurrent} />

      <section>
        <h2>Privacy</h2>
        <p className="muted">
          On Google's free tier, prompts and responses may be used to improve their products,
          including human review. The coach's prompts carry your training history, sleep and any
          injuries you mention. A paid key excludes your data from training.
        </p>
      </section>
    </div>
  );
}
