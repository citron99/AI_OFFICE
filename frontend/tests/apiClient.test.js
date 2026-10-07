import test from "node:test";
import assert from "node:assert/strict";
import {createApiClient} from "../src/api/client.js";

/** Подменяет глобальный fetch на время теста и возвращает журнал вызовов. */
function mockFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url, options});
    return handler(url, options);
  };
  return {calls, restore: () => {globalThis.fetch = original;}};
}

const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: {"Content-Type": "application/json"},
});

test("client requests /api/v1 with bearer token and parses JSON", async () => {
  const mock = mockFetch(() => jsonResponse([{task_id: "task_1", state: "running"}]));
  try {
    const client = createApiClient({token: "secret-key"});
    const tasks = await client.getTasks();
    assert.deepEqual(tasks, [{task_id: "task_1", state: "running"}]);
    assert.equal(mock.calls[0].url, "/api/v1/tasks");
    assert.equal(mock.calls[0].options.headers.Authorization, "Bearer secret-key");
    assert.equal(mock.calls[0].options.headers["Content-Type"], "application/json");
  } finally { mock.restore(); }
});

test("decideApproval posts decision payload to the approval endpoint", async () => {
  const mock = mockFetch(() => jsonResponse({task_id: "task_1", state: "completed"}));
  try {
    const client = createApiClient({token: "k"});
    const task = await client.decideApproval("approval_9", "approve");
    assert.equal(task.state, "completed");
    assert.equal(mock.calls[0].url, "/api/v1/approvals/approval_9/decision");
    assert.equal(mock.calls[0].options.method, "POST");
    assert.deepEqual(JSON.parse(mock.calls[0].options.body), {decision: "approve"});
  } finally { mock.restore(); }
});

test("graph, trace and provider status use the documented endpoints", async () => {
  const mock = mockFetch(url => jsonResponse(url.endsWith("provider-status")
    ? {mode: "consultant_plus", status: "active", license_scope: ["RU"]}
    : {nodes: []}));
  try {
    const client = createApiClient();
    await client.getTaskGraph("task 1");
    await client.getTaskTrace("task 1");
    const provider = await client.getLegalProviderStatus();
    assert.equal(provider.mode, "consultant_plus");
    assert.deepEqual(mock.calls.map(call => call.url), [
      "/api/v1/tasks/task%201/process-graph",
      "/api/v1/tasks/task%201/trace",
      "/api/v1/legal/provider-status",
    ]);
    assert.equal(mock.calls[0].options.headers.Authorization, undefined);
  } finally { mock.restore(); }
});

test("http errors become readable messages without leaking stack details", async () => {
  const mock = mockFetch(url => {
    if (url.endsWith("/me")) {
      return new Response(JSON.stringify({detail: "Неверный ключ."}), {status: 401});
    }
    return jsonResponse({code: "NOT_FOUND"}, 404);
  });
  try {
    const client = createApiClient({token: "bad"});
    // 401 сознательно заменяется единым сообщением об авторизации (как в текущем UI).
    await assert.rejects(client.getMe(), /Введите ключ доступа к офису\./);
    const error = await client.getLegalProviderStatus().catch(reason => reason);
    assert.equal(error.message, "NOT_FOUND");
    assert.equal(error.status, 404);
  } finally { mock.restore(); }
});

test("server failures explain that the backend is unavailable", async () => {
  const mock = mockFetch(() => jsonResponse({}, 503));
  try {
    await assert.rejects(createApiClient().getTasks(),
      /Сервис временно недоступен/);
  } finally { mock.restore(); }
});

test("runtime controls read and update the process switches", async () => {
  const state = {
    process_id: "office_review",
    autonomy_level: "a2_draft",
    process_enabled: true,
    llm_enabled: true,
    write_tools_enabled: false,
  };
  const mock = mockFetch(url => jsonResponse(url.endsWith("/runtime") && mock.calls.length === 1
    ? state : {autonomy_level: "a2_draft", write_tools_enabled: true}));
  try {
    const client = createApiClient({token: "owner-key"});
    const loaded = await client.getProcessRuntime("office_review");
    assert.equal(loaded.process_enabled, true);
    const updated = await client.setProcessRuntime("office_review", {
      write_tools_enabled: true,
    });
    assert.equal(updated.write_tools_enabled, true);
    assert.equal(mock.calls[1].url, "/api/v1/processes/office_review/runtime");
    assert.equal(mock.calls[1].options.method, "POST");
    assert.deepEqual(JSON.parse(mock.calls[1].options.body), {write_tools_enabled: true});
    assert.equal(mock.calls[1].options.headers.Authorization, "Bearer owner-key");
  } finally { mock.restore(); }
});

test("auth bootstrap endpoints do not require an existing access token", async () => {
  const mock = mockFetch((_url, options) => jsonResponse({
    access_token: "access-1",
    refresh_token: "refresh-1",
    request: JSON.parse(options.body),
  }));
  try {
    const client = createApiClient();
    const oidc = await client.startOidcSession("provider-token");
    const invitation = await client.acceptInvitation("invitation-token");
    const refreshed = await client.refreshSession("refresh-token");
    await client.logoutSession("refresh-token-2");
    assert.equal(oidc.request.id_token, "provider-token");
    assert.equal(invitation.request.invitation_token, "invitation-token");
    assert.equal(refreshed.request.refresh_token, "refresh-token");
    assert.deepEqual(mock.calls.map(call => call.url), [
      "/api/v1/auth/oidc/session",
      "/api/v1/auth/invitations/accept",
      "/api/v1/auth/refresh",
      "/api/v1/auth/logout",
    ]);
    assert(mock.calls.every(call => call.options.headers.Authorization === undefined));
  } finally { mock.restore(); }
});

test("a refresh token rotation supplies a retry token", async () => {
  let protectedCalls = 0;
  let refreshCalls = 0;
  const client = createApiClient({
    token: "expired",
    fetch: async (_url, options) => {
      protectedCalls += 1;
      return options.headers.Authorization === "Bearer renewed"
        ? jsonResponse([{task_id: "task_renewed"}])
        : jsonResponse({detail: "expired"}, 401);
    },
    refresh: async () => { refreshCalls += 1; return "renewed"; },
  });
  const tasks = await client.getTasks();
  assert.deepEqual(tasks, [{task_id: "task_renewed"}]);
  assert.equal(protectedCalls, 2);
  assert.equal(refreshCalls, 1);
});
