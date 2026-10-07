import test from "node:test";
import assert from "node:assert/strict";
import {filterTasks, filterInvoices} from "../src/workspaceView.js";

const tasks = [
  {task_id: "task_one", category: "legal", state: "waiting_input"},
  {task_id: "task_two", category: "accounting", state: "running"},
  {task_id: "task_three", category: "mixed", state: "completed"},
  {task_id: "task_four", category: "security", state: "failed"},
];
test("task filters isolate active and attention states", () => {
  assert.deepEqual(filterTasks(tasks, "", "active").map(t => t.task_id), ["task_two"]);
  assert.deepEqual(filterTasks(tasks, "", "attention").map(t => t.task_id), ["task_one", "task_four"]);
});
test("search supports Russian category labels and case-insensitive IDs", () => {
  assert.equal(filterTasks(tasks, " ЮРИДИЧЕСКИЙ ", "all")[0].task_id, "task_one");
  assert.equal(filterTasks(tasks, "TASK_TWO", "all")[0].task_id, "task_two");
  assert.equal(filterTasks(tasks, "unknown", "all").length, 0);
});
test("search and state filter combine without mutating data", () => {
  const before = structuredClone(tasks);
  assert.equal(filterTasks(tasks, "task_three", "active").length, 0);
  assert.deepEqual(tasks, before);
});
test("invoice search matches number, identifier and counterparty", () => {
  const invoices = [{id: "inv_100", number: "BILL-42", counterparty_id: "cp_12"}];
  for (const query of [" INV_100 ", "bill-42", "CP_12", ""]) {
    assert.deepEqual(filterInvoices(invoices, query), invoices);
  }
  assert.deepEqual(filterInvoices(invoices, "other"), []);
});
