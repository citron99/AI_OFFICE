import React, {useEffect, useState} from "react";

const PROCESSES = [
  {id: "office_review", title: "Проверка задачи AI-офисом"},
  {id: "daily_cash_and_receivable_risk", title: "Ежедневный контроль денег"},
];

const LEVELS = [
  ["a0_shadow", "A0 — Shadow (наблюдает)"],
  ["a1_recommendation", "A1 — Recommendation"],
  ["a2_draft", "A2 — Draft (черновики)"],
  ["a3_approved_action", "A3 — Approved action"],
];

const SWITCHES = [
  ["process_enabled", "Процесс включён", "Немедленная остановка контура; новые запуски паркуются в ручной режим."],
  ["llm_enabled", "Внешний LLM", "Выключение убирает внешний анализ; детерминированные шаги продолжают работать."],
  ["write_tools_enabled", "Инструменты записи", "Выключение превращает подготовку черновиков в DENY."],
];

/**
 * Управление процессами (ACC-10): kill switch, лестница автономности.
 * Изменения доступны только OWNER (backend возвращает 403 прочим ролям).
 */
export default function ProcessControlsView({api, writable}) {
  const [processId, setProcessId] = useState(PROCESSES[0].id);
  const [runtime, setRuntime] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setRuntime(null); setDraft(null); setError(""); setSaved("");
    api(`/processes/${encodeURIComponent(processId)}/runtime`)
      .then(state => { if (alive) { setRuntime(state); setDraft(state); } })
      .catch(reason => { if (alive) setError(reason.message); });
    return () => { alive = false; };
  }, [processId]);

  function toggle(key) {
    setDraft(current => ({...current, [key]: !current[key]}));
  }

  async function save(event) {
    event.preventDefault(); setBusy(true); setError(""); setSaved("");
    const patch = {};
    for (const [key] of SWITCHES) if (draft[key] !== runtime[key]) patch[key] = draft[key];
    if (draft.autonomy_level !== runtime.autonomy_level) patch.autonomy_level = draft.autonomy_level;
    try {
      const state = await api(`/processes/${encodeURIComponent(processId)}/runtime`, {
        method: "POST", body: JSON.stringify(patch),
      });
      setRuntime(state); setDraft(state); setSaved("Сохранено");
    } catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }

  const dirty = runtime && draft && SWITCHES.some(([key]) => draft[key] !== runtime[key])
    || runtime && draft && draft.autonomy_level !== runtime.autonomy_level;

  return <section className="process-controls" aria-label="Управление процессами">
    <div className="ops-panel legal-hero"><div>
      <span className="eyebrow">PROCESS CONTROLS · OWNER ONLY</span>
      <h2>Управление процессами</h2>
      <p>Kill switch и лестница автономности. Изменения применяются немедленно и
        без изменения кода; каждое изменение фиксируется с автором и временем.</p>
    </div></div>
    <div className="ops-grid legal-grid"><section className="ops-panel">
      <div className="ops-panel-head"><div><span className="eyebrow">КОНТУР</span><h3>Процесс</h3></div></div>
      <label>Процесс
        <select value={processId} onChange={event => setProcessId(event.target.value)}>
          {PROCESSES.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
      </label>
      {!runtime && !error && <p className="pill">Загрузка…</p>}
      {error && <p className="pill" role="alert">{error}</p>}
      {runtime && <form onSubmit={save}>
        {SWITCHES.map(([key, label, hint]) => (
          <label key={key} className="runtime-switch">
            <input type="checkbox" checked={Boolean(draft[key])}
                   disabled={!writable || busy} onChange={() => toggle(key)} />
            <span><strong>{label}</strong><small>{hint}</small></span>
          </label>
        ))}
        <label>Уровень автономности
          <select value={draft.autonomy_level} disabled={!writable || busy}
                  onChange={event => setDraft({...draft, autonomy_level: event.target.value})}>
            {LEVELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button className="primary" disabled={!writable || busy || !dirty}>
          {writable ? (busy ? "Сохраняем…" : "Применить") : "Только OWNER"}
        </button>
        {!writable && <small>Изменения доступны роли OWNER.</small>}
        {saved && <small>{saved}</small>}
        {runtime.updated_by && <small>
          Последнее изменение: {runtime.updated_by}, {new Date(runtime.updated_at).toLocaleString("ru-RU")}
        </small>}
      </form>}
    </section></div>
  </section>;
}
