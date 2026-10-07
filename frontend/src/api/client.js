/**
 * Единый API-клиент фронтенда к существующему FastAPI backend (/api/v1).
 *
 * Правила объединения:
 *  - единственный backend — FastAPI; методы не содержат ни демо-данных,
 *    ни вычислений денег (расчёты остаются на сервере);
 *  - ошибки нормализуются в человекочитаемые сообщения на русском;
 *  - fetch можно подменить (тесты и серверный рендер), по умолчанию — globalThis.fetch.
 */

/**
 * @typedef {{token?: string, baseUrl?: string, fetch?: typeof fetch,
 *   refresh?: () => Promise<string|null>}} ApiClientOptions
 */

/**
 * Нормализует ответ fetch в Error с понятным сообщением.
 * @param {Response} response
 * @param {string} body
 * @returns {Error}
 */
function responseError(response, body) {
  let parsed = {};
  try { parsed = body ? JSON.parse(body) : {}; } catch { /* не JSON — используем статус */ }
  const message = response.status === 401 ? "Введите ключ доступа к офису." :
    typeof parsed.detail === "string" ? parsed.detail :
    parsed.message || parsed.code || (response.status >= 500 ?
      "Сервис временно недоступен. Повторите запрос после запуска серверной части." :
      "Запрос не выполнен (" + response.status + ")");
  const error = new Error(message);
  error.status = response.status;
  error.code = parsed.code;
  return error;
}

/**
 * Создаёт клиент к /api/v1.
 * @param {ApiClientOptions} [options]
 */
export function createApiClient(options = {}) {
  const baseUrl = options.baseUrl || "/api/v1";
  // Resolve the global implementation at call time so tests/service workers
  // can replace fetch without recreating the public auth client.
  const doFetch = options.fetch || ((...args) => globalThis.fetch(...args));

  /**
   * Базовый запрос. `path` начинается с "/" и добавляется к baseUrl.
   * @param {string} path
   * @param {RequestInit} [requestOptions]
   * @returns {Promise<any>}
   */
  async function request(path, requestOptions = {}) {
    const {skipAuthRefresh = false, ...fetchOptions} = requestOptions;
    const body = requestOptions.body;
    async function send(token) {
      const headers = {
        ...(body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...requestOptions.headers,
      };
      return doFetch(baseUrl + path, { ...fetchOptions, headers });
    }

    let response = await send(options.token);
    if (response.status === 401 && options.refresh && !skipAuthRefresh) {
      const refreshedToken = await options.refresh();
      if (refreshedToken) response = await send(refreshedToken);
    }
    if (!response.ok) {
      throw responseError(response, await response.text().catch(() => ""));
    }
    return response.json();
  }

  return {
    request,

    /** @returns {Promise<{user_id: string, role: string}>} */
    getMe: () => request("/me"),

    /** Exchange an IdP assertion for a local access/refresh session. */
    startOidcSession: idToken => request("/auth/oidc/session", {
      method: "POST", body: JSON.stringify({id_token: idToken}), skipAuthRefresh: true,
    }),
    /** Redeem a one-time invitation and bootstrap a complete session. */
    acceptInvitation: invitationToken => request("/auth/invitations/accept", {
      method: "POST", body: JSON.stringify({invitation_token: invitationToken}),
      skipAuthRefresh: true,
    }),
    /** Rotate a refresh token; no live access token is required. */
    refreshSession: refreshToken => request("/auth/refresh", {
      method: "POST", body: JSON.stringify({refresh_token: refreshToken}),
      skipAuthRefresh: true,
    }),
    logoutSession: refreshToken => request("/auth/logout", {
      method: "POST", body: JSON.stringify({refresh_token: refreshToken}),
      skipAuthRefresh: true,
    }),

    /** @returns {Promise<Array>} список последних задач */
    getTasks: () => request("/tasks"),
    /** @param {string} taskId */
    getTask: taskId => request(`/tasks/${encodeURIComponent(taskId)}`),
    /** Сохранённый ход выполнения и audit events. @param {string} taskId */
    getTaskTrace: taskId => request(`/tasks/${encodeURIComponent(taskId)}/trace`),
    /** Сохранённый граф процесса (process DAG). @param {string} taskId */
    getTaskGraph: taskId => request(`/tasks/${encodeURIComponent(taskId)}/process-graph`),

    /** @returns {Promise<Array>} список согласований */
    getApprovals: () => request("/approvals"),
    /**
     * Решение собственника по согласованию (создание/отклонение mock-черновика).
     * @param {string} approvalId
     * @param {"approve"|"reject"} decision
     */
    decideApproval: (approvalId, decision) => request(
      `/approvals/${encodeURIComponent(approvalId)}/decision`,
      { method: "POST", body: JSON.stringify({ decision }) }),

    getDrafts: () => request("/drafts"),
    getInvoices: () => request("/accounting/invoices"),

    /**
     * Финансовый отчёт за период. Все деньги считает сервер.
     * @param {{start: string, end: string, planned_cash_in?: string|null, planned_cash_out?: string|null}} period
     */
    financialReport: period => request("/accounting/financial-report", {
      method: "POST",
      body: JSON.stringify({
        start: period.start, end: period.end,
        planned_cash_in: period.planned_cash_in ?? null,
        planned_cash_out: period.planned_cash_out ?? null,
      }),
    }),

    getKnowledgeSources: () => request("/knowledge/sources"),
    /** @param {{query: string, jurisdiction: string, effective_on: string, top_k?: number}} body */
    searchKnowledge: body => request("/knowledge/search", {
      method: "POST", body: JSON.stringify(body) }),

    /** Сводные показатели процесса для дашборда. */
    getProcessQuality: () => request("/processes/quality"),
    getProcessControls: () => request("/processes/controls"),
    /** Журнал активности (persisted audit). */
    getActivity: () => request("/activity"),

    /** Kill switch и лестница автономности процесса (GET). */
    getProcessRuntime: processId =>
      request(`/processes/${encodeURIComponent(processId)}/runtime`),
    /**
     * Переключатели процесса (только OWNER): process_enabled, llm_enabled,
     * write_tools_enabled, autonomy_level. Выше потолка паспорта API вернёт 409.
     * @param {string} processId
     * @param {{process_enabled?: boolean, llm_enabled?: boolean,
     *          write_tools_enabled?: boolean, autonomy_level?: string}} patch
     */
    setProcessRuntime: (processId, patch) => request(
      `/processes/${encodeURIComponent(processId)}/runtime`,
      { method: "POST", body: JSON.stringify(patch) }),

    /** Статус юридического провайдера (mode/status/license_scope). 404 → ошибка с кодом. */
    getLegalProviderStatus: () => request("/legal/provider-status"),

    /** @param {string} taskId */
    getResultReview: taskId => request(`/tasks/${encodeURIComponent(taskId)}/result-review`),
    submitResultReview: (taskId, review) => request(
      `/tasks/${encodeURIComponent(taskId)}/result-review`,
      { method: "POST", body: JSON.stringify(review) }),

    /**
     * Создание задачи с ключом идемпотентности.
     * @param {object} payload
     * @param {string} idempotencyKey
     */
    createTask: (payload, idempotencyKey) => request("/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    }),
    /** @param {string} taskId */
    cancelTask: taskId => request(`/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" }),
    clarifyTask: (taskId, payload) => request(`/tasks/${encodeURIComponent(taskId)}/clarify`, {
      method: "POST", body: JSON.stringify(payload) }),
    retryTask: taskId => request(`/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST" }),

    /** @param {File} file */
    uploadFile: file => {
      const data = new FormData();
      data.append("file", file);
      return request("/files", { method: "POST", body: data });
    },
  };
}

/** Клиент без авторизации — для экрана входа и тестов. */
export const publicApi = createApiClient();
