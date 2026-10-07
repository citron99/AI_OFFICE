import assert from "node:assert/strict";
import test from "node:test";
import {activeTaskStates, riskSnapshot} from "../src/officeUI.js";

test("risk snapshot uses only persisted process and accounting inputs", () => {
  const snapshot = riskSnapshot({
    tasks: [{state: "failed"}, {state: "waiting_approval"}],
    approvals: [{status: "pending"}],
    controls: {policy_decisions: {deny: 1}},
    finance: {
      total_receivable: "1000.00",
      total_outstanding: "1000.00",
      receivable_aging: {not_due: "100.00", "31_60": "900.00"},
    },
  });
  assert.equal(snapshot.failed, 1);
  assert.equal(snapshot.attention, 1);
  assert.equal(snapshot.pendingApprovals, 1);
  assert.equal(snapshot.denied, 1);
  assert.equal(snapshot.overdue, 900);
  assert.equal(snapshot.score, 67);
  assert.equal(snapshot.level, "high");
});

test("empty dashboard state reports no fabricated risk", () => {
  assert.deepEqual(riskSnapshot({}), {
    score: 0, level: "low", failed: 0, attention: 0, pendingApprovals: 0,
    denied: 0, overdue: 0, outstanding: 0,
  });
  assert.equal(activeTaskStates.has("running"), true);
  assert.equal(activeTaskStates.has("completed"), false);
});
