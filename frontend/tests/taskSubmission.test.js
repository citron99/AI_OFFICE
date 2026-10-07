import test from "node:test";
import assert from "node:assert/strict";
import { createTaskSubmission } from "../src/taskSubmission.js";

const request = (overrides = {}) => ({
  owner: "owner", payload: {message: "Check", invoice_id: "inv_100"}, file: null,
  upload: async () => ({id: "artifact-1"}),
  send: async (payload, key) => ({payload, key}), ...overrides,
});

test("lost response retains key and uploaded attachment", async () => {
  let uploads = 0;
  const calls = [];
  const submission = createTaskSubmission(() => "stable-key");
  const input = request({file: {}, upload: async () => {
    uploads++; return {id: "artifact-1"};
  }, send: async (payload, key) => {
    calls.push({payload, key});
    if (calls.length === 1) throw new TypeError("Network error");
    return {task_id: "one"};
  }});
  await assert.rejects(submission.submit(input), /Network error/);
  assert.deepEqual(await submission.submit(input), {task_id: "one"});
  assert.equal(uploads, 1);
  assert.deepEqual(calls[0], calls[1]);
  assert.deepEqual(calls[1].payload.attachment_ids, ["artifact-1"]);
});

test("double click is ignored synchronously and cannot reset pending request", async () => {
  let release;
  const submission = createTaskSubmission(() => "key");
  const first = submission.submit(request({send: () => new Promise(resolve => {release = resolve;})}));
  assert.equal(submission.active, true);
  assert.equal(await submission.submit(request()), null);
  assert.equal(submission.reset(), false);
  release({task_id: "one"});
  await first;
  assert.equal(submission.active, false);
  assert.equal(submission.reset(), true);
});

test("success replay reuses key; explicit new task gets new key", async () => {
  let sequence = 0;
  const submission = createTaskSubmission(() => `key-${++sequence}`);
  const first = await submission.submit(request());
  assert.deepEqual(await submission.submit(request()), first);
  submission.reset();
  assert.notEqual((await submission.submit(request())).key, first.key);
});

test("changed body or file is rejected until explicitly reset", async () => {
  const submission = createTaskSubmission(() => "key");
  await submission.submit(request());
  await assert.rejects(submission.submit(request({payload: {message: "Other"}})), /Новая задача/);
  await assert.rejects(submission.submit(request({file: {}})), /Новая задача/);
});

test("different owner receives new key and new upload", async () => {
  let sequence = 0;
  const submission = createTaskSubmission(() => `key-${++sequence}`);
  const file = {};
  const first = await submission.submit(request({file}));
  const second = await submission.submit(request({file, owner: "other",
    upload: async () => ({id: "artifact-2"})}));
  assert.notEqual(first.key, second.key);
  assert.deepEqual(second.payload.attachment_ids, ["artifact-2"]);
});

test("upload failure does not submit a task; retry can upload", async () => {
  let uploads = 0;
  let sends = 0;
  const submission = createTaskSubmission(() => "key");
  const input = request({file: {}, upload: async () => {
    if (++uploads === 1) throw new Error("Upload failed");
    return {id: "artifact-1"};
  }, send: async () => {sends++; return {task_id: "one"};}});
  await assert.rejects(submission.submit(input));
  assert.equal(sends, 0);
  await submission.submit(input);
  assert.equal(sends, 1);
});

test("server error keeps original request for a safe retry", async () => {
  let sequence = 0;
  const submission = createTaskSubmission(() => `key-${++sequence}`);
  await assert.rejects(submission.submit(request({send: async () => {throw new Error("503");}})));
  assert.equal((await submission.submit(request())).key, "key-1");
});
