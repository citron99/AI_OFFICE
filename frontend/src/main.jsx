import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./design.css";
import "./styles/tokens.css";
import Finance from "./Finance";
import { createTaskSubmission } from "./taskSubmission";
import Dashboard from "./features/dashboard/Dashboard";
import ApprovalModal from "./features/approvals/ApprovalModal";
import { lazy, Suspense } from "react";

// Heavy feature views load on first navigation (route-level code splitting).
const TaskDagView = lazy(() => import("./features/tasks/TaskDagView"));
const AgentThread = lazy(() => import("./AgentThread"));
const ActivityAuditView = lazy(() => import("./features/activity/ActivityAuditView"));
const ConsultationView = lazy(() => import("./ConsultationView"));
const LegalRagView = lazy(() => import("./features/legal/LegalRagView"));
const ProcessControlsView = lazy(() => import("./features/processes/ProcessControlsView"));
import CommandPalette from "./CommandPalette";
import Navbar from "./components/ui/Navbar";
import ErrorBoundary from "./components/ui/ErrorBoundary";
import { createApiClient, publicApi } from "./api/client";
import {categories, filterTasks, filterInvoices} from "./workspaceView";

const states = {
  queued: "В очереди", running: "В работе", waiting_input: "Нужны сведения",
  waiting_approval: "На согласовании", completed: "Завершено", failed: "Ошибка",
  waiting_source: "Ждёт источник (Консультант+)", failed_safe: "Безопасная остановка",
  cancelled: "Отменено", pending: "Ожидает решения", approved: "Одобрено",
  rejected: "Отклонено", expired: "Срок истёк", classifying: "Определяем маршрут", planning: "Планируем",
};
const tabs = [
  ["dashboard", "Дашборд", "chart"], ["tasks", "Рабочий стол", "bot"],
  ["finance", "Бухгалтерия", "calculator"], ["approvals", "Согласования", "shield"],
  ["knowledge", "Legal RAG", "scale"], ["dag", "Граф выполнения", "network"],
  ["thread", "Agent Thread", "activity"], ["consultation", "Консилиум", "user"],
  ["activity", "Активность", "clock"],
  ["processes", "Управление", "layers"],
];
const riskLabels = {low: "Низкий риск", medium: "Средний риск", high: "Высокий риск", critical: "Критический риск"};
const policyLabels = {
  allow_read: "Разрешено (чтение)",
  allow_draft: "Разрешено (черновик)",
  require_owner_approval: "Требуется согласование владельца",
  deny: "Запрещено",
  escalate: "Эскалация специалисту",
  owner_only_outside_agent: "Только владелец, вне агентов",
};
const evidenceLabels = {sufficient: "Достаточно", insufficient: "Недостаточно", partial: "Частично достаточно"};
const agentLabels = {accountant: "Бухгалтер", lawyer: "Юрист", security: "Безопасность", orchestrator: "Оркестратор"};
const money = value => new Intl.NumberFormat("ru-RU", {
  style: "currency", currency: "RUB",
}).format(Number(value || 0));
const themeStorageKey = "ai-office-theme";

function App() {
  const [tab, setTab] = useState("dashboard");
  const [taskQuery, setTaskQuery] = useState("");
  const [taskFilter, setTaskFilter] = useState("all");
  const [invoiceQuery, setInvoiceQuery] = useState("");
  const [auth, setAuth] = useState({accessToken: "", refreshToken: "", mode: "demo"});
  const token = auth.accessToken;
  const [me, setMe] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [sources, setSources] = useState([]);
  const [processQuality, setProcessQuality] = useState(null);
  const [processControls, setProcessControls] = useState(null);
  const [selected, setSelected] = useState(null);
  const [trace, setTrace] = useState(null);
  const [processGraph, setProcessGraph] = useState(null);
  const [activity, setActivity] = useState(null);
  const [financeReport, setFinanceReport] = useState(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Проверь договор и счёт нового подрядчика");
  const [invoiceId, setInvoiceId] = useState("inv_100");
  const [country, setCountry] = useState("LV");
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [action, setAction] = useState("analyze");
  const [file, setFile] = useState(null);
  const [sourceTitle, setSourceTitle] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [theme, setTheme] = useState(() =>
    globalThis.localStorage?.getItem(themeStorageKey) === "dark" ? "dark" : "light");
  const submission = useRef(createTaskSubmission());
  const refreshInFlight = useRef(null);
  const resultRef = useRef(null);
  const [submissionState, setSubmissionState] = useState("idle");
  const [taskFile, setTaskFile] = useState(null);
  const [sourceCountry, setSourceCountry] = useState("LV");
  const [sourceDate, setSourceDate] = useState(new Date().toISOString().slice(0, 10));
  const [clarifyCountry, setClarifyCountry] = useState("LV");
  const [clarifyDate, setClarifyDate] = useState(new Date().toISOString().slice(0, 10));
  async function refreshAccess() {
    if (!auth.refreshToken) return null;
    if (!refreshInFlight.current) {
      refreshInFlight.current = publicApi.refreshSession(auth.refreshToken)
        .then(next => {
          setAuth(current => ({
            ...current,
            accessToken: next.access_token,
            refreshToken: next.refresh_token,
          }));
          return next.access_token;
        })
        .catch(error => {
          setAuth({accessToken: "", refreshToken: "", mode: "signed_out"});
          throw error;
        })
        .finally(() => { refreshInFlight.current = null; });
    }
    return refreshInFlight.current;
  }
  const client = useMemo(() => createApiClient({
    token,
    refresh: auth.refreshToken ? refreshAccess : undefined,
  }), [token, auth.refreshToken]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    globalThis.localStorage?.setItem(themeStorageKey, theme);
  }, [theme]);

  async function api(path, options = {}) {
    return client.request(path, options);
  }

  async function refresh() {
    const [identity, list, bills, decisions, prepared, knowledge, quality, controls, activityFeed] = await Promise.all([
      api("/me"), api("/tasks"), api("/accounting/invoices"),
      api("/approvals"), api("/drafts"), api("/knowledge/sources"), api("/processes/quality"), api("/processes/controls"), api("/activity"),
    ]);
    setMe(identity); setTasks(list); setInvoices(bills); setApprovals(decisions);
    setDrafts(prepared); setSources(knowledge); setProcessQuality(quality); setProcessControls(controls); setActivity(activityFeed);
  }

  async function run(operation) {
    setBusy(true); setError("");
    try { await operation(); } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function login(mode, credential) {
    return run(async () => {
      if (mode === "api_key") {
        setAuth({accessToken: credential, refreshToken: "", mode});
        return;
      }
      const session = mode === "oidc"
        ? await publicApi.startOidcSession(credential)
        : await publicApi.acceptInvitation(credential);
      setAuth({
        accessToken: session.access_token,
        refreshToken: session.refresh_token,
        mode,
      });
    });
  }
  async function logout() {
    setBusy(true); setError("");
    try {
      if (auth.refreshToken) await publicApi.logoutSession(auth.refreshToken);
    } catch (e) {
      setError(e.message);
    } finally {
      setAuth({accessToken: "", refreshToken: "", mode: "signed_out"});
      setMe(null);
      setBusy(false);
    }
  }
  useEffect(() => {
    setMe(null); setTasks([]); setInvoices([]); setApprovals([]); setDrafts([]);
    setSources([]); setProcessQuality(null); setProcessControls(null); setSelected(null); setTrace(null); setProcessGraph(null); setActivity(null); setFinanceReport(null);
    submission.current = createTaskSubmission();
    setSubmissionState("idle"); setTaskFile(null);
    run(refresh);
  }, [token]);
  useEffect(() => {
    if (!tasks.some(t => ["queued", "classifying", "planning", "running"].includes(t.state))) return;
    const timer = setInterval(() => {
      refresh().catch(() => {});
      if (selected) api("/tasks/" + selected.task_id).then(setSelected).catch(() => {});
    }, 2500);
    return () => clearInterval(timer);
  }, [tasks, token, selected?.task_id]);
  useEffect(() => {
    if (selected?.task_id) resultRef.current?.scrollIntoView({block: "start"});
  }, [selected?.task_id]);
  useEffect(() => {
    const onKeyDown = event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  async function openTask(task) {
    setSelected(task); setTrace(null); setProcessGraph(null);
    const [nextTrace, nextGraph] = await Promise.all([
      api("/tasks/" + task.task_id + "/trace"),
      api("/tasks/" + task.task_id + "/process-graph"),
    ]);
    setTrace(nextTrace); setProcessGraph(nextGraph);
  }
  async function upload() {
    if (!file) return null;
    const data = new FormData(); data.append("file", file);
    return api("/files", {method: "POST", body: data});
  }
  async function createTask(event) {
    event.preventDefault();
    if (busy || !me || me.role === "viewer") return;
    const current = submission.current;
    if (current.active) return;
    setSubmissionState("sending");
    await run(async () => {
      let task;
      try {
        task = await current.submit({
          owner: me.user_id,
          payload: {message, invoice_id: invoiceId || null, jurisdiction: country || null,
            effective_on: asOf || null, requested_action: action},
          file: taskFile,
          upload: async attachment => {
            const data = new FormData(); data.append("file", attachment);
            return api("/files", {method: "POST", body: data});
          },
          send: (payload, key) => api("/tasks", {method: "POST",
            headers: {"Idempotency-Key": key}, body: JSON.stringify(payload)}),
        });
      } catch (e) {
        if (submission.current !== current) return;
        setSubmissionState("uncertain");
        throw e;
      }
      if (!task || submission.current !== current) return;
      setSubmissionState("accepted");
      setSelected(task); setTrace(null);
      await refresh(); await openTask(task);
    });
  }
  async function makeDecision() {
    await run(async () => {
      const task = await api("/approvals/" + confirm.record.id + "/decision", {
        method: "POST", body: JSON.stringify({decision: confirm.decision}),
      });
      setConfirm(null); await refresh(); await openTask(task); setTab("tasks");
    });
  }
  // Читающие роли без права записи: auditor (см. RBAC ТЗ 10.5).
  const writable = Boolean(me) && me.role !== "auditor";
  const canApprove = me && ["owner", "admin"].includes(me.role);
  const pending = approvals.filter(a => a.status === "pending");
  const activeTaskCount = tasks.filter(t => ["queued", "classifying", "planning", "running"].includes(t.state)).length;
  const visibleTasks = filterTasks(tasks, taskQuery, taskFilter);
  const visibleInvoices = filterInvoices(invoices, invoiceQuery);
  const descriptions = {
    dashboard: "Обзор сохранённых процессов, контрольных точек и финансового риска.",
    tasks: "Делегируйте проверку. Изучайте основания. Принимайте решения.",
    finance: "Денежный поток, обязательства, дебиторская задолженность и факторы риска.",
    approvals: "Действия, которые не выполняются без вашего решения.",
    knowledge: "Проверяемые источники и поиск доказательств для юридического анализа.",
    dag: "Реальный граф сохранённого процесса: узлы, зависимости и блокировки.",
    thread: "Стенограмма шагов агентов и событий текущей задачи.",
    consultation: "Согласованная позиция участников текущего процесса.",
    activity: "Хронология сохранённых шагов и audit events выбранной задачи.",
  };

  return <div className="shell">
    <a className="skip-link" href="#workspace">Перейти к содержимому</a>
    <aside>
      <a className="brand" href="/"><span className="brand-mark">О</span><span>AI-офис<small>СОБСТВЕННИКА</small></span></a>
      <div className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <div className="sidebar-note"><span className="dot" />Контролируемый пилот<p>Все финансовые записи синтетические. Реальные платежи отключены.</p></div>
    </aside>
    <main id="workspace" tabIndex={-1}>
      <Navbar tabs={tabs} activeTab={tab} onNavigate={setTab}
        pendingApprovalsCount={pending.length} activeTasksCount={activeTaskCount}
        me={me} onLogin={login} onLogout={logout}
        theme={theme} onToggleTheme={() => setTheme(current => current === "light" ? "dark" : "light")}
        onOpenPalette={() => setPaletteOpen(true)} onRefresh={() => run(refresh)} busy={busy} />
      {error && <div className="error" role="alert">{error}</div>}
      {busy && <div role="status" className="working">Выполняется запрос…</div>}
      <section className="page-title"><div><span className="eyebrow">РЕШЕНИЯ С ПРОВЕРЯЕМЫМИ ОСНОВАНИЯМИ</span>
        <h1>{tabs.find(t => t[0] === tab)[1]}</h1>
        <p className="page-description">{descriptions[tab]}</p></div>
        <span className="pill">Демо • без реальных данных</span></section>

      <ErrorBoundary>
      {tab === "dashboard" && <Dashboard tasks={tasks} approvals={approvals} drafts={drafts}
        processQuality={processQuality} processControls={processControls} finance={financeReport} onNavigate={setTab} />}

      {tab === "tasks" && <>
        <div className="metrics"><Metric label="Задачи" value={tasks.length} hint="Последние 50" />
          <Metric label="На согласовании" value={pending.length} hint="Решение за вами" />
          <Metric label="Mock-черновики" value={drafts.length} hint="Не отправлены в банк" />
          <Metric label="Проверки результатов" value={processQuality?.pending_reviews ?? "—"}
            hint={processQuality ? `Покрыто review: ${Math.round(processQuality.review_rate * 100)}%` : "…"} />
          <Metric label="Контроль postflight" value={processControls ? `${Math.round(processControls.postflight_coverage * 100)}%` : "—"}
            hint={processControls ? `Блокировок policy: ${processControls.policy_decisions.deny}` : "…"} /></div>
        {processControls && <section className="card control-summary" aria-label="Контроль процесса">
          <strong>Postflight: {processControls.postflight_completed}/{processControls.office_results}</strong>
          <span className="muted">Флаги: {Object.keys(processControls.control_flags).length || "нет"}</span>
        </section>}
        <div className="work-grid"><section className="card composer"><h2>Новая задача</h2>
          <p className="muted">Сформулируйте вопрос. Бухгалтер, юрист и безопасность подготовят результат.</p>
          <form onSubmit={createTask}>
            <fieldset disabled={busy || submissionState !== "idle"} className="submission-fields">
            <label>Что нужно проверить?<textarea required rows="4" maxLength={20000}
              value={message} onChange={e => setMessage(e.target.value)} /></label>
            <label>Синтетический счёт<select value={invoiceId} onChange={e => setInvoiceId(e.target.value)}>
              <option value="">Без счёта</option>{invoices.map(i =>
                <option key={i.id} value={i.id}>{i.id} · {money(i.gross)}</option>)}</select></label>
            <div className="fields"><label>Юрисдикция<input value={country} maxLength={2}
              placeholder="LV" onChange={e => setCountry(e.target.value.toUpperCase())} /></label>
              <label>Дата проверки<input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label></div>
            <label>Вложение для проверки<input type="file" accept=".txt,.pdf,.docx"
              key={token} onChange={e => setTaskFile(e.target.files[0] || null)} /></label>
            {taskFile && <p className="muted">Выбран файл: {taskFile.name}</p>}
            <label>Действие<select value={action} onChange={e => setAction(e.target.value)}>
              <option value="analyze">Только анализ</option>
              <option value="prepare_payment_draft">Запросить mock-черновик через согласование</option>
            </select></label>
            </fieldset>
            {submissionState === "uncertain" && <p role="status" className="warning">
              Ответ не получен. Повторите отправку: если задача уже создана, откроется она же.
              До проверки результата не создавайте новую задачу и не перезагружайте вкладку.</p>}
            {submissionState === "accepted" && <p role="status" className="muted">
              Задача принята. Повторная отправка откроет ту же задачу.</p>}
            <button className="primary wide" disabled={busy || !writable}>
              {submissionState === "idle" ? "Начать проверку →" : "Повторить отправку безопасно"}</button>
            {submissionState !== "idle" && <button type="button" disabled={busy}
              className="quiet" onClick={() => {
                if (submissionState === "uncertain" && !window.confirm(
                  "Предыдущая задача могла быть создана. Новая отправка может создать дубликат. Начать новую задачу?"
                )) return;
                if (submission.current.reset()) {setSubmissionState("idle"); setError("");}
              }}>Новая задача</button>}
          </form>
        </section><section className="card"><div className="section-head"><h2>Последние задачи</h2>
          <span className="pill">{visibleTasks.length} / {tasks.length}</span></div>
          <label>Поиск задачи<input type="search" value={taskQuery} placeholder="ID или тип проверки"
            onChange={e => setTaskQuery(e.target.value)} /></label>
          <div className="segmented" role="group" aria-label="Фильтр задач">
            {[["all", "Все"], ["active", "В работе"], ["attention", "Нужно внимание"]].map(([id, label]) =>
              <button key={id} aria-pressed={taskFilter === id} onClick={() => setTaskFilter(id)}>{label}</button>)}
          </div>
          {!tasks.length && <Empty text="Создайте первую задачу — здесь появятся её статус и результат." />}
          {!!tasks.length && !visibleTasks.length && <Empty text="По этому фильтру задач нет. Измените поиск или выберите «Все»." />}
          <div className="task-list">{visibleTasks.map(task => <button key={task.task_id}
            className={"task-row " + (selected?.task_id === task.task_id ? "selected" : "")}
            disabled={busy} aria-pressed={selected?.task_id === task.task_id}
            onClick={() => run(() => openTask(task))}>
            <div><strong>{categories[task.category] || "Задача"}</strong>
              <small className="task-reference">…{task.task_id.slice(-8)}</small>
              <small>{new Date(task.created_at).toLocaleString("ru-RU")}</small></div>
            <Badge value={task.state} /></button>)}</div></section></div>
        <section className="overview-banner">
          <div><span className="eyebrow">КОНТРОЛЬ ОСТАЁТСЯ У ВАС</span>
            <h2>{pending.length ? "Есть решения, которые ждут вас" : "От вопроса — к обоснованному решению"}</h2>
            <p>Бухгалтерия, право и безопасность в одной проверке. Черновик создаётся только после вашего согласования.</p></div>
          <button onClick={() => setTab("approvals")}>Согласования · {pending.length} →</button>
        </section>
        {selected && <section ref={resultRef} className="card result"><div className="section-head">
          <h2>Результат проверки</h2><Badge value={selected.state} /></div>
          <p className="muted id">{selected.task_id}</p>
          <p>{selected.result?.summary || "Задача ещё выполняется."}</p>
          {selected.state === "waiting_input" && <div className="callout">
            <p>Укажите страну и дату, затем продолжите эту задачу.</p>
            <div className="fields"><label>Страна уточнения<input maxLength={2}
              value={clarifyCountry} onChange={e => setClarifyCountry(e.target.value.toUpperCase())} /></label>
              <label>Дата уточнения<input type="date" value={clarifyDate}
                onChange={e => setClarifyDate(e.target.value)} /></label></div>
            <button disabled={busy || !clarifyCountry || !clarifyDate || !writable} onClick={() => run(async () => {
              const task = await api("/tasks/" + selected.task_id + "/clarify", {method: "POST",
                body: JSON.stringify({jurisdiction: clarifyCountry, effective_on: clarifyDate})});
              await refresh(); await openTask(task);
            })}>Продолжить с указанным контекстом</button></div>}
          {["queued", "running", "waiting_input", "waiting_approval"].includes(selected.state) &&
            <button className="quiet" disabled={busy || !writable} onClick={() => run(async () => {
              const task = await api("/tasks/" + selected.task_id + "/cancel", {method: "POST"});
              await refresh(); await openTask(task);
            })}>Отменить задачу</button>}
          {selected.state === "failed" && <button disabled={busy || !writable} onClick={() => run(async () => {
            const task = await api("/tasks/" + selected.task_id + "/retry", {method: "POST"});
            await refresh(); await openTask(task);
          })}>Повторить новой задачей</button>}
          <Result result={selected.result} />
          <div className="actions result-navigation">
            <button className="quiet" onClick={() => setTab("dag")}>Граф выполнения</button>
            <button className="quiet" onClick={() => setTab("thread")}>Стенограмма</button>
            <button className="quiet" onClick={() => setTab("consultation")}>Консилиум</button>
            <button className="quiet" onClick={() => setTab("activity")}>Аудит</button>
          </div>
          {selected.run_budget && <div className="callout"><strong>Лимит запуска</strong>
            <p className="muted">Шаги: {selected.run_usage?.steps_started || 0}/{selected.run_budget.max_steps} · LLM: {selected.run_usage?.llm_calls || 0}/{selected.run_budget.max_llm_calls} · цикл доработки: {selected.rework_cycle || 0}/{selected.run_budget.max_rework_cycles}</p>
          </div>}
          <ResultReview task={selected} processGraph={processGraph} api={api} canReview={canApprove} busy={busy} />
          {processGraph && <details className="trace"><summary>{"\u0413\u0440\u0430\u0444 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f"}</summary>
            {processGraph.nodes.map(node => <p key={node.id}><strong>{node.kind === "result_review" ? "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430" : agentLabels[node.agent] || node.agent}</strong>
              {" · "}{states[node.state] || node.state}{" · "}{node.readiness}
              {node.depends_on.length > 0 && <small> ← {node.depends_on.join(", ")}</small>}</p>)}
          </details>}
          {trace && <details className="trace"><summary>Ход выполнения и аудит</summary>
            {trace.steps.map(s => <p key={s.id}><strong>{s.node_id || agentLabels[s.agent] || s.agent}</strong> — {states[s.state] || s.state} · попытка {s.attempt || 0}</p>)}
            {trace.audit.map(e => <p key={e.id}>{e.event} · {new Date(e.created_at).toLocaleString("ru-RU")}</p>)}
          </details>}
        </section>}
      </>}

      {tab === "finance" && <><Finance key={token} api={api} tasks={tasks} approvals={approvals} controls={processControls}
        onReportChange={setFinanceReport} /><section className="card"><div className="section-head"><h2>Реестр счетов</h2><span className="pill">Mock1C · {invoices.length} записей</span></div>
        <label>Поиск в реестре<input type="search" placeholder="Счёт, номер или контрагент" value={invoiceQuery}
          onChange={e => setInvoiceQuery(e.target.value)} /></label>
        <p className="muted">Суммы рассчитываются Decimal. Налоговая ставка — параметр тестовых данных, не правовая норма.</p>
        <div className="table-wrap"><table><thead><tr><th>Счёт</th><th>Контрагент</th><th>Срок</th><th>Сумма</th><th /></tr></thead>
          <tbody>{visibleInvoices.map(i => <tr key={i.id}><td><strong>{i.id}</strong><small>{i.number}</small></td>
            <td>{i.counterparty_id}</td><td>{i.due_on}</td><td className="numeric">{money(i.gross)}</td>
            <td><button className="quiet" disabled={busy || submissionState !== "idle"}
              title={submissionState !== "idle" ? "Сначала нажмите «Новая задача» на рабочем столе" : "Проверить счёт"}
              onClick={() => {setInvoiceId(i.id); setTab("tasks");}}>Проверить →</button></td></tr>)}</tbody></table></div>
        {!visibleInvoices.length && <Empty text="Счета не найдены. Измените поисковый запрос." />}
      </section></>}

      {tab === "approvals" && <><section className="callout"><strong>Вы подтверждаете только создание mock-черновика.</strong>
        <p>Это не юридическое одобрение и не разрешение на платёж. Банковское исполнение отсутствует.</p></section>
        {!approvals.length && <Empty text="Пока нет запросов на согласование." />}
        {approvals.map(a => <section className="card approval" key={a.id}><div className="section-head">
          <h2>{a.payload.invoice_id} · {money(a.payload.amount)}</h2><Badge value={a.status} /></div>
          <p>Действует до {new Date(a.expires_at).toLocaleString("ru-RU")}</p>
          <p className="muted id">Хеш действия: {a.payload_hash}</p>
          {a.status === "pending" && <div className="actions">
            <button className="primary" disabled={busy || !canApprove || new Date(a.expires_at) <= new Date()}
              onClick={() => setConfirm({record: a, decision: "approve"})}>Создать mock-черновик</button>
            <button disabled={busy || !canApprove} onClick={() => setConfirm({record: a, decision: "reject"})}>Отклонить</button>
          </div>}</section>)}
        {drafts.length > 0 && <section className="card"><h2>Созданные черновики</h2>{drafts.map(d =>
          <p key={d.id}><strong>{d.payload.invoice_id || "Синтетический черновик (в пределах лимита)"}</strong> · {money(d.payload.amount || 0)} <span className="muted">/ не отправлен</span></p>)}</section>}
      </>}

      <Suspense fallback={<section className="ops-panel" aria-busy="true"><p className="pill">Загрузка раздела…</p></section>}>
      {tab === "processes" && <ProcessControlsView api={api} writable={writable} />}
      {tab === "knowledge" && <><LegalRagView api={api} sources={sources} writable={writable} />
        <div className="work-grid"><section className="card"><h2>Добавить тестовый источник</h2>
        <p className="muted">Вложение задачи не становится источником права автоматически. Здесь регистрируются только явно выбранные тестовые источники.</p>
        <form onSubmit={e => {e.preventDefault(); run(async () => {
          const artifact = await upload();
          if (!artifact) throw new Error("Выберите файл источника.");
          await api("/knowledge/sources", {method: "POST", body: JSON.stringify({
            artifact_id: artifact.id, title: sourceTitle, document_type: "test_norm",
            jurisdiction: sourceCountry, authority: "SYNTHETIC TEST, NOT LAW", version: "demo-v1",
            effective_from: sourceDate, status: "ACTIVE", classification: "INTERNAL",
          })});
          setSourceTitle(""); await refresh();
        });}}>
          <label>Название<input required value={sourceTitle} onChange={e => setSourceTitle(e.target.value)} /></label>
          <label>Страна<input required maxLength={2} value={sourceCountry} onChange={e => setSourceCountry(e.target.value.toUpperCase())} /></label>
          <label>Действует с<input required type="date" value={sourceDate} onChange={e => setSourceDate(e.target.value)} /></label>
          <label>Файл<input required type="file" accept=".txt,.pdf,.docx" onChange={e => setFile(e.target.files[0] || null)} /></label>
          <button className="primary" disabled={busy || !writable}>Зарегистрировать источник</button>
        </form></section><section className="card"><h2>Источники</h2>
          {!sources.length && <Empty text="Источников пока нет. Без них юридические выводы не генерируются." />}
          {sources.map(s => <article className="source-row" key={s.id}><h3>{s.title}</h3>
            <p>{s.jurisdiction} · {s.version} · {s.chunk_count} фрагментов</p><small>{s.embedding_model}</small></article>)}
        </section></div></>}

      {tab === "dag" && <TaskDagView graph={processGraph} />}
      {tab === "thread" && <AgentThread trace={trace} />}
      {tab === "consultation" && <ConsultationView task={selected} graph={processGraph}
        onOpenThread={() => setTab("thread")}
        onOpenReview={() => { setTab("tasks"); window.setTimeout(() => resultRef.current?.scrollIntoView({block: "start"}), 0); }} />}
      {tab === "activity" && <ActivityAuditView trace={trace} activity={activity} onRefresh={() => run(async () => {
        await refresh(); if (selected) await openTask(selected);
      })} />}
      </Suspense>
      </ErrorBoundary>

      <footer>AI-офис собственника · Внутренний пилот <span>Результаты требуют проверки специалистами</span></footer>
    </main>
    {confirm && <ApprovalModal record={confirm.record} decision={confirm.decision} busy={busy}
      invoice={invoices.find(i => i.id === confirm.record.payload?.invoice_id) || null}
      onClose={() => setConfirm(null)} onConfirm={makeDecision} />}
    <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} tasks={tasks} approvals={approvals}
      onNavigate={setTab} onRefresh={() => run(refresh)} onOpenTask={task => run(async () => { setTab("tasks"); await openTask(task); })} />
  </div>;
}

function Metric({label, value, hint}) {
  return <section className="metric"><span>{label}</span><strong>{value}</strong><small>{hint}</small></section>;
}
function Badge({value}) { return <span className={"badge state-" + value}>{states[value] || value}</span>; }
function Empty({text}) { return <div className="empty">{text}</div>; }
function ResultReview({task, processGraph, api, canReview, busy}) {
  const [preview, setPreview] = useState(null);
  const [decision, setDecision] = useState("accepted");
  const [reason, setReason] = useState("");
  const [targets, setTargets] = useState([]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  useEffect(() => {
    let active = true;
    setPreview(null); setError(""); setReason(""); setTargets([]);
    api("/tasks/" + task.task_id + "/result-review")
      .then(value => { if (active) setPreview(value); })
      .catch(value => { if (active) setError(value.message); });
    return () => { active = false; };
  }, [task.task_id]);
  if (!preview) return error ? <p className="warning" role="status">{error}</p> : null;
  if (!preview.eligible) return null;
  if (preview.review) return <section className="callout" aria-label="Result review">
    <strong>{"\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d"}</strong>
    <p>{preview.review.decision} · {preview.review.reason}</p>
    {preview.review.rework_task_id && <p className="muted">Создана отдельная задача доработки: {preview.review.rework_task_id}</p>}
  </section>;
  async function submit(event) {
    event.preventDefault(); setSending(true); setError("");
    try {
      const review = await api("/tasks/" + task.task_id + "/result-review", {
        method: "POST", body: JSON.stringify({decision, reason, result_hash: preview.result_hash, target_node_ids: targets}),
      });
      setPreview({...preview, review});
    } catch (value) { setError(value.message); } finally { setSending(false); }
  }
  return <section className="callout" aria-label="Result review">
    <strong>{"\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430"}</strong>
    <p className="muted">{"\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0444\u0438\u043a\u0441\u0438\u0440\u0443\u0435\u0442 \u0432\u044b\u0432\u043e\u0434 \u0438 \u043d\u0435 \u0440\u0430\u0437\u0440\u0435\u0448\u0430\u0435\u0442 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435."}</p>
    {canReview ? <form onSubmit={submit}>
      <label>{"\u0420\u0435\u0448\u0435\u043d\u0438\u0435"}<select value={decision} onChange={e => setDecision(e.target.value)}>
        <option value="accepted">{"\u041f\u0440\u0438\u043d\u044f\u0442\u043e"}</option>
        <option value="rework_required">{"\u0414\u043e\u0440\u0430\u0431\u043e\u0442\u043a\u0430"}</option>
        <option value="rejected">{"\u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e"}</option>
      </select></label>
      <label>{"\u041e\u0441\u043d\u043e\u0432\u0430\u043d\u0438\u0435"}<textarea required rows="2" maxLength="2000" value={reason}
        onChange={e => setReason(e.target.value)} /></label>
      {decision === "rework_required" && <fieldset className="rework-targets"><legend>Узлы для доработки</legend>
        {processGraph?.nodes.filter(node => node.kind === "agent_step").map(node => <label key={node.id}>
          <input type="checkbox" checked={targets.includes(node.node_id || node.id)} onChange={e => setTargets(current => e.target.checked ? [...current, node.node_id || node.id] : current.filter(id => id !== (node.node_id || node.id)))} />
          {" "}{node.action || node.agent}
        </label>)}
      </fieldset>}
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={busy || sending || (decision === "rework_required" && targets.length === 0)}>{sending ? "…" : "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443"}</button>
    </form> : <p className="warning">{"\u0414\u043b\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 \u043d\u0443\u0436\u043d\u0430 \u0440\u043e\u043b\u044c \u0432\u043b\u0430\u0434\u0435\u043b\u044c\u0446\u0430 \u0438\u043b\u0438 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430."}</p>}
  </section>;
}
function Result({result}) {
  if (!result) return null;
  const legal = result.legal || (result.mode?.startsWith("legal_") ? result : null);
  return <>
    {result.accounting && <div className="callout"><strong>Бухгалтерия</strong><p>
      Оплачено: {money(result.accounting.paid)} · Остаток: {money(result.accounting.outstanding)}</p></div>}
    {result.policy_reasons?.length > 0 && <p className="muted">Решение политики: {policyLabels[result.policy_decision] || result.policy_decision} — {result.policy_reasons.join(", ")}</p>}
    {(result.findings || []).map((f, i) => <article key={i} className={"finding risk-" + f.risk_level}>
      <span className="eyebrow">{riskLabels[f.risk_level] || f.risk_level}</span><h3>{f.title}</h3><p>{f.description}</p>
      {f.citations.map((c, j) => <small key={j}>{c.title} · {c.locator || c.source_id}</small>)}
    </article>)}
    {legal && <section><h3>Юридическая часть</h3><p>{legal.summary}</p>
      {legal.evidence_assessment && <p>Достаточность по оценке модели: {evidenceLabels[legal.evidence_assessment.status] || legal.evidence_assessment.status}</p>}
      {legal.unresolved_questions.map((q, i) => <p className="callout" key={i}>{q}</p>)}
      {legal.evidence.map(hit => <details key={hit.chunk_id} className="evidence"><summary>{hit.title} · {hit.locator}</summary>
        <blockquote>{hit.text}</blockquote><small>{hit.jurisdiction} · {hit.version}</small></details>)}
      {legal.warnings.map((w, i) => <p key={i} className="warning">{w}</p>)}
    </section>}
    {(result.warnings || []).map((w, i) => <p key={i} className="warning">{w}</p>)}
    {result.requires_approval && <p className="callout">Действие ожидает решения в разделе «Согласования».</p>}
  </>;
}

const container = document.getElementById("root");
if (container) createRoot(container).render(<App />); // допускает SSR-смоук-тест без DOM

// Экспорт для SSR-смоук-тестов рендеринга (в браузере не используется).
export {App};
