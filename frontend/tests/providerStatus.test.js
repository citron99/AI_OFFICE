import assert from "node:assert/strict";
import test from "node:test";

import {formatLicenseScope, providerIsActive} from "../src/features/legal/legalProviderStatus.js";

test("structured legal license scope is converted to renderable text", () => {
  const formatted = formatLicenseScope({
    jurisdictions: ["DE", "LV", "RU"],
    allowed_channels: ["mock_licensed_export"],
    scope_owner: "MVP synthetic integration owner",
    valid_until: null,
  });

  assert.equal(typeof formatted, "string");
  assert.match(formatted, /DE, LV, RU/);
  assert.match(formatted, /mock_licensed_export/);
  assert.match(formatted, /MVP synthetic integration owner/);
});

test("legacy scope shapes and provider health statuses remain supported", () => {
  assert.equal(formatLicenseScope(["RU", "LV"]), "RU, LV");
  assert.equal(formatLicenseScope("RU only"), "RU only");
  assert.equal(formatLicenseScope(null), null);
  assert.equal(providerIsActive("ok"), true);
  assert.equal(providerIsActive("active"), true);
  assert.equal(providerIsActive("unavailable"), false);
});
