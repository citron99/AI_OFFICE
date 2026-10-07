import React, {useState} from "react";
import FinancialRiskView from "./FinancialRiskView";

const money = value => new Intl.NumberFormat("ru-RU", {style: "currency", currency: "RUB"}).format(Number(value));
const buckets = {not_due: "Срок не наступил", "1_30": "1–30 дней", "31_60": "31–60 дней", "61_90": "61–90 дней", over_90: "Более 90 дней"};

export default function Finance({api, tasks = [], approvals = [], controls = null, onReportChange}) {
  const [start, setStart] = useState("2026-07-01");
  const [end, setEnd] = useState("2026-07-31");
  const [plannedIn, setPlannedIn] = useState("");
  const [plannedOut, setPlannedOut] = useState("");
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [syncRuns, setSyncRuns] = useState([]);
  const [syncKey, setSyncKey] = useState(null);
  async function syncSnapshot(create) {
    setBusy(true); setError("");
    try {
      if (create) {
        const key = syncKey || crypto.randomUUID(); setSyncKey(key);
        await api("/accounting/sync", {method: "POST", body: JSON.stringify({request_key: key})});
        setSyncKey(null);
      }
      setSyncRuns(await api("/accounting/sync-runs"));
    } catch (e) {setError(e.message);} finally {setBusy(false);}
  }
  async function calculate(event) {
    event.preventDefault(); setBusy(true); setError(""); setReport(null);
    try {
      const nextReport = await api("/accounting/financial-report", {method: "POST", body: JSON.stringify({
        start, end, planned_cash_in: plannedIn === "" ? null : plannedIn,
        planned_cash_out: plannedOut === "" ? null : plannedOut,
      })});
      setReport(nextReport); onReportChange?.(nextReport);
    } catch (e) {setError(e.message);} finally {setBusy(false);}
  }
  return <section className="card finance-report">
    <div className="section-head"><h2>Финансовый отчёт</h2><span className="pill">Синтетические данные · RUB</span></div>
    <div className="actions">
      <button disabled={busy} onClick={() => syncSnapshot(true)}>Проверить синтетический снимок</button>
      <button disabled={busy} className="quiet" onClick={() => syncSnapshot(false)}>Журнал чтения</button>
    </div>
    <p className="muted">Фиксируются версия, количество записей и контрольная сумма. Это не импорт из реальной 1С.</p>
    {syncRuns.length > 0 && <details><summary>Последние проверки снимка: {syncRuns.length}</summary>
      {syncRuns.map(s => <p key={s.id}>{new Date(s.created_at).toLocaleString("ru-RU")} · {s.dataset_version} · {s.counts.invoices} счетов, {s.counts.accrual_entries} начислений<small className="id">SHA-256: {s.snapshot_hash}</small></p>)}
    </details>}
    <p className="muted">Синтетические данные · российский рубль · границы периода включены. План задаётся только для этого расчёта.</p>
    <form onSubmit={calculate}>
      <div className="fields">
        <label>Начало периода<input type="date" required value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>Конец периода<input type="date" required min={start} value={end} onChange={e => setEnd(e.target.value)} /></label>
      </div>
      <div className="fields">
        <label>План поступлений, ₽<input type="number" min="0" step="0.01" value={plannedIn} required={plannedOut !== ""} onChange={e => setPlannedIn(e.target.value)} /></label>
        <label>План выплат, ₽<input type="number" min="0" step="0.01" value={plannedOut} required={plannedIn !== ""} onChange={e => setPlannedOut(e.target.value)} /></label>
      </div>
      <button disabled={busy} className="primary">{busy ? "Расчёт…" : "Сформировать отчёт"}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {report && <>
      <h3>Денежный поток: {report.current.start} — {report.current.end}</h3>
      <div className="metrics">
        <section className="metric"><span>Поступления</span><strong>{money(report.current.incoming)}</strong><small>За выбранный период</small></section>
        <section className="metric"><span>Выплаты</span><strong>{money(report.current.outgoing)}</strong><small>За выбранный период</small></section>
        <section className="metric"><span>Чистый денежный поток</span><strong>{money(report.current.net)}</strong><small>Не является прибылью</small></section>
      </div>
      <FinancialRiskView report={report} tasks={tasks} approvals={approvals} controls={controls} />
      <div className="table-wrap"><table><thead><tr><th>Показатель</th><th>Текущий период</th><th>Предыдущий период</th></tr></thead><tbody>
        <tr><td>Поступления</td><td>{money(report.current.incoming)}</td><td>{money(report.previous.incoming)}</td></tr>
        <tr><td>Выплаты</td><td>{money(report.current.outgoing)}</td><td>{money(report.previous.outgoing)}</td></tr>
        <tr><td>Чистый денежный поток</td><td>{money(report.current.net)}</td><td>{money(report.previous.net)}</td></tr>
      </tbody></table></div>
      <p>Сравнение с {report.previous.start} — {report.previous.end}: изменение потока {money(report.net_change)}.</p>
      {report.plan_fact && <div className="callout"><strong>План-факт: факт минус план</strong>
        <p>Поступления: {money(report.plan_fact.incoming_variance)} · Выплаты: {money(report.plan_fact.outgoing_variance)} · Чистый поток: {money(report.plan_fact.net_variance)}</p>
        <small>Положительное отклонение выплат означает превышение плана расходов.</small>
      </div>}
      <h3>Задолженность поставщикам на {report.payables_as_of}</h3>
      <p>Всего: {money(report.total_outstanding)} · Переплаты отдельно: {money(report.total_overpayment)}</p>
      <div className="table-wrap"><table><thead><tr><th>Срок просрочки</th><th>Остаток</th></tr></thead><tbody>
        {Object.entries(report.aging).map(([key, value]) => <tr key={key}><td>{buckets[key]}</td><td>{money(value)}</td></tr>)}
      </tbody></table></div>
      <h3>Дебиторская задолженность на {report.receivables_as_of}</h3>
      <p>К получению: {money(report.total_receivable)}</p>
      <div className="table-wrap"><table><thead><tr><th>Срок просрочки</th><th>К получению</th></tr></thead><tbody>
        {Object.entries(report.receivable_aging).map(([key, value]) => <tr key={key}><td>{buckets[key]}</td><td>{money(value)}</td></tr>)}
      </tbody></table></div>
      <details><summary>Расшифровка дебиторской задолженности: {report.receivables.length}</summary>
        <div className="table-wrap"><table><thead><tr><th>Требование</th><th>Контрагент</th><th>Срок</th><th>Получено</th><th>Остаток</th></tr></thead><tbody>
          {report.receivables.map(r => <tr key={r.receivable_id}><td>{r.receivable_id}</td><td>{r.counterparty_id}</td><td>{r.due_on}</td><td>{money(r.received)}</td><td>{money(r.outstanding)}</td></tr>)}
        </tbody></table></div>
      </details>
      <h3>Остатки денежных средств</h3>
      {report.balances_as_of ? <>
        <p>На {report.balances_as_of}: {money(report.total_bank_balance)}</p>
        <div className="table-wrap"><table><thead><tr><th>Счёт</th><th>Остаток</th></tr></thead><tbody>
          {report.account_balances.map(b => <tr key={b.id}><td>{b.account_name}</td><td>{money(b.amount)}</td></tr>)}
        </tbody></table></div>
      </> : <p className="warning">На выбранную дату нет снимка банковских остатков.</p>}
      <details><summary>Расшифровка счетов и исходные записи</summary>
        <div className="table-wrap"><table><thead><tr><th>Счёт</th><th>Оплачено</th><th>Остаток</th><th>Переплата</th><th>Платежи</th></tr></thead><tbody>
          {report.payables.map(p => <tr key={p.invoice_id}><td>{p.invoice_id}</td><td>{money(p.paid)}</td><td>{money(p.outstanding)}</td><td>{money(p.overpayment)}</td><td>{p.payment_ids.join(", ") || "Нет"}</td></tr>)}
        </tbody></table></div>
        <p className="muted">Операции текущего периода: {report.current.transaction_ids.join(", ") || "Нет"}</p>
      </details>
      <Profit report={report.profit_and_loss} />
      <p className="warning">Денежные операции и оплаты счетов — отдельные тестовые наборы без сверки. Исходные аномалии включены; отчёт не разрешает оплату.</p>
    </>}
  </section>;
}

function Profit({report}) {
  if (!report) return <p className="warning">P&L недоступен: провайдер не предоставил журнал начислений.</p>;
  const rows = [["revenue", "Выручка после корректировок"], ["cost_of_sales", "Себестоимость"],
    ["gross_profit", "Валовая прибыль"], ["operating_expense", "Операционные расходы"],
    ["depreciation", "Амортизация"], ["operating_profit", "Операционная прибыль"]];
  return <section>
    <h3>P&L · метод начисления</h3>
    <p className="muted">Регистр {report.journal_version} · покрытие {report.coverage_start} — {report.coverage_end}. Суммы без НДС.</p>
    <div className="table-wrap"><table><thead><tr><th>Показатель</th><th>Текущий период</th><th>Предыдущий период</th></tr></thead><tbody>
      {rows.map(([key, label]) => <tr key={key}><td>{label}</td><td>{report.current ? money(report.current[key]) : "Нет полного покрытия"}</td><td>{report.previous ? money(report.previous[key]) : "Нет полного покрытия"}</td></tr>)}
    </tbody></table></div>
    <p>Изменение операционной прибыли: {report.operating_profit_change === null ? "Недостаточно данных" : money(report.operating_profit_change)}</p>
    {[report.current, report.previous].filter(Boolean).map(period => <details key={period.start}>
      <summary>Начисления {period.start} — {period.end}: {period.entries.length} записей</summary>
      <div className="table-wrap"><table><thead><tr><th>Запись / основание</th><th>Дата</th><th>Статья</th><th>Сумма</th></tr></thead><tbody>
        {period.entries.map(e => <tr key={e.id}><td>{e.id}<small>{e.source_reference}</small></td><td>{e.recognized_on}</td><td>{rows.find(r => r[0] === e.category)?.[1] || e.category}</td><td>{e.reversal ? "−" : ""}{money(e.amount)}</td></tr>)}
      </tbody></table></div>
    </details>)}
    <p className="warning">Учебный регистр, не бухгалтерская книга двойной записи. Нет финансовых расходов и налога на прибыль: результат не является чистой прибылью. Начисления и денежные операции — независимые тестовые наборы без сверки.</p>
  </section>;
}
