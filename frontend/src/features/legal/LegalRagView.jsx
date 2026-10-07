import React, {useEffect, useState} from "react";
import {formatDate} from "../../officeUI";
import ProviderStatus from "./ProviderStatus";

/**
 * Legal RAG — проверяемые источники и поиск оснований.
 * Сверху добавлен статус юридического провайдера (Консультант+/provider-status),
 * перенесённый из дизайн-проекта и привязанный к GET /api/v1/legal/provider-status.
 */
export default function LegalRagView({api, sources, writable}) {
  const [query, setQuery] = useState("проверка договора и ответственности сторон");
  const [jurisdiction, setJurisdiction] = useState("RU");
  const [effectiveOn, setEffectiveOn] = useState(new Date().toISOString().slice(0, 10));
  const [response, setResponse] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [radarRuns, setRadarRuns] = useState([]);
  const [baselineId, setBaselineId] = useState("");
  const [currentId, setCurrentId] = useState("");
  const [radarSubject, setRadarSubject] = useState("contract payment acceptance");
  const [radarError, setRadarError] = useState("");
  const [reviewReason, setReviewReason] = useState("Проверено по указанным источникам и дате действия.");
  useEffect(() => {
    let active = true;
    api("/legal/change-radar/runs").then(runs => { if (active) setRadarRuns(runs); })
      .catch(reason => { if (active) setRadarError(reason.message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!baselineId && sources[0]) setBaselineId(sources[0].id);
    if (!currentId && sources[1]) setCurrentId(sources[1].id);
  }, [sources, baselineId, currentId]);
  async function search(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { setResponse(await api("/knowledge/search", {method: "POST", body: JSON.stringify({query, jurisdiction, effective_on: effectiveOn, top_k: 8})})); }
    catch (reason) { setError(reason.message); } finally { setBusy(false); }
  }
  async function compare(event) {
    event.preventDefault(); setBusy(true); setRadarError("");
    try {
      const run = await api("/legal/change-radar/runs", {
        method: "POST",
        headers: {"Idempotency-Key": `radar-${globalThis.crypto.randomUUID()}`},
        body: JSON.stringify({baseline_source_id: baselineId, current_source_id: currentId,
          subject: radarSubject, jurisdiction, effective_on: effectiveOn}),
      });
      setRadarRuns(items => [run, ...items.filter(item => item.id !== run.id)]);
    } catch (reason) { setRadarError(reason.message); } finally { setBusy(false); }
  }
  async function review(run, decision) {
    setBusy(true); setRadarError("");
    try {
      const updated = await api(`/legal/change-radar/runs/${encodeURIComponent(run.id)}/review`, {
        method: "POST", body: JSON.stringify({decision, reason: reviewReason}),
      });
      setRadarRuns(items => items.map(item => item.id === updated.id ? updated : item));
    } catch (reason) { setRadarError(reason.message); } finally { setBusy(false); }
  }
  const latestRun = radarRuns[0] || null;
  return <section className="legal-rag-view" aria-label="Legal RAG">
    <ProviderStatus request={api} />
    <div className="ops-panel legal-hero"><div><span className="eyebrow">LEGAL RAG · OWNER-ISOLATED SOURCES</span><h2>Юридическая база и доказательства</h2>
      <p>Поиск использует только явно зарегистрированные источники текущего владельца. Результат не является юридическим заключением.</p></div><span className="legal-source-count">{sources.length}<small> источников</small></span></div>
    <section className="ops-panel change-radar"><div className="ops-panel-head"><div><span className="eyebrow">LEGAL CHANGE RADAR · HUMAN REVIEW</span><h3>Что изменилось в правовой норме</h3><p>Сравнение версий с effective-date gate, точными цитатами и независимым следом поиска Консультант+.</p></div>{latestRun && <span className="pill">{latestRun.result.changes.length} изменений</span>}</div>
      <form className="radar-form" onSubmit={compare}><div className="fields"><label>Предыдущая версия<select required value={baselineId} onChange={event => setBaselineId(event.target.value)}><option value="">Выберите источник</option>{sources.map(source => <option key={source.id} value={source.id}>{source.title} · {source.version}</option>)}</select></label><label>Текущая версия<select required value={currentId} onChange={event => setCurrentId(event.target.value)}><option value="">Выберите источник</option>{sources.map(source => <option key={source.id} value={source.id}>{source.title} · {source.version}</option>)}</select></label></div><label>Предмет мониторинга<input required value={radarSubject} onChange={event => setRadarSubject(event.target.value)} /></label><div className="fields"><label>Юрисдикция<input maxLength="2" value={jurisdiction} onChange={event => setJurisdiction(event.target.value.toUpperCase())} /></label><label>Дата применимости<input type="date" value={effectiveOn} onChange={event => setEffectiveOn(event.target.value)} /></label></div><button className="primary" disabled={busy || !baselineId || !currentId || baselineId === currentId || sources.length < 2}>{busy ? "Сверяем…" : "Сравнить версии"}</button></form>
      {sources.length < 2 && <p className="warning">Для Radar нужны минимум две зарегистрированные версии одного источника.</p>}
      {radarError && <p className="error" role="alert">{radarError}</p>}
      {latestRun && <div className="radar-report"><div className="radar-kpis"><article><span>High attention</span><strong>{latestRun.result.counts.high_attention || 0}</strong></article><article><span>Добавлено</span><strong>{latestRun.result.counts.added || 0}</strong></article><article><span>Изменено</span><strong>{latestRun.result.counts.modified || 0}</strong></article><article><span>Удалено</span><strong>{latestRun.result.counts.removed || 0}</strong></article></div><p className="warning">{latestRun.result.disclaimer}</p>{latestRun.result.changes.slice(0, 10).map(change => <article className={`radar-change signal-${change.impact_signal}`} key={change.change_id}><header><b>{change.summary}</b><span>{change.impact_signal}</span></header>{change.matched_terms.length > 0 && <small>Маркеры: {change.matched_terms.join(", ")}</small>}<div className="radar-citations">{change.before && <blockquote><b>Было · {change.before.version} · {change.before.locator}</b>{change.before.quote}</blockquote>}{change.after && <blockquote><b>Стало · {change.after.version} · {change.after.locator}</b>{change.after.quote}</blockquote>}</div></article>)}<footer><span>Консультант+: {latestRun.result.consultant_plus.queries.length} карточек источников · полный лицензированный текст не копируется</span><span>{latestRun.jurisdiction} · {formatDate(latestRun.effective_on, {dateStyle: "medium"})}</span></footer>{!latestRun.review && <div className="radar-review"><label>Комментарий юриста/владельца<input value={reviewReason} onChange={event => setReviewReason(event.target.value)} /></label><div className="actions"><button disabled={busy || reviewReason.trim().length < 8} onClick={() => void review(latestRun, "accepted")}>Принять после проверки</button><button disabled={busy || reviewReason.trim().length < 8} onClick={() => void review(latestRun, "changes_requested")}>Вернуть на уточнение</button></div></div>}{latestRun.review && <p className="callout"><strong>Human review:</strong> {latestRun.review.decision} · {latestRun.review.reason}</p>}</div>}
    </section>
    <div className="ops-grid legal-grid"><section className="ops-panel"><div className="ops-panel-head"><div><span className="eyebrow">RETRIEVAL</span><h3>Поиск оснований</h3></div>{response && <span className="pill">{response.embedding_model}</span>}</div>
      <form onSubmit={search} className="rag-form"><label>Запрос<textarea rows="3" required value={query} onChange={event => setQuery(event.target.value)} /></label>
        <div className="fields"><label>Юрисдикция<input maxLength="2" value={jurisdiction} onChange={event => setJurisdiction(event.target.value.toUpperCase())} /></label>
          <label>Дата действия<input type="date" value={effectiveOn} onChange={event => setEffectiveOn(event.target.value)} /></label></div>
        <button className="primary" disabled={busy || !query.trim()}>{busy ? "Ищем…" : "Найти источники"}</button></form>
      {error && <p className="error" role="alert">{error}</p>}
      {response && <div className="rag-results"><p className="muted">Версия retrieval: {response.retrieval_version} · найдено: {response.hits.length}</p>
        {response.hits.map(hit => <article className="rag-hit" key={hit.chunk_id}><header><b>{hit.title}</b><span>score {Number(hit.score).toFixed(3)}</span></header>
          <p>{hit.text}</p><footer>{hit.jurisdiction} · {hit.document_type} · {hit.locator || hit.article || "без локатора"} · {formatDate(hit.effective_from, {dateStyle: "medium"})}</footer></article>)}
        {!response.hits.length && <div className="ops-empty">Подходящих фрагментов нет. Проверьте юрисдикцию, дату действия или загрузите источник.</div>}
        {response.warnings?.map(warning => <p className="warning" key={warning}>{warning}</p>)}</div>}
    </section><section className="ops-panel source-catalog"><div className="ops-panel-head"><div><span className="eyebrow">SOURCE CATALOG</span><h3>Доступные источники</h3></div><span className="pill">{writable ? "можно пополнять" : "только чтение"}</span></div>
      {!sources.length && <div className="ops-empty">Источники ещё не зарегистрированы. Добавьте документ в нижнем блоке этого раздела.</div>}
      {sources.map(source => <article className="source-card" key={source.id}><b>{source.title}</b><p>{source.jurisdiction} · {source.document_type} · {source.version}</p>
        <small>{source.chunk_count} фрагментов · {source.embedding_model} · {source.classification}</small></article>)}</section></div>
  </section>;
}
