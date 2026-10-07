import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const css = readFileSync(new URL("../src/design.css", import.meta.url), "utf8");
function token(name) {
  const hex = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]+)`))[1];
  return hex.length === 4 ? "#" + [...hex.slice(1)].map(c => c + c).join("") : hex;
}
function luminance(hex) {
  return [1, 3, 5].map((offset, i) => {
    const c = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return (c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][i];
  }).reduce((a, b) => a + b, 0);
}
test("core text and status token pairs retain at least 4.5:1 contrast", () => {
  for (const [fg, bg] of [["text", "surface"], ["muted", "surface"], ["surface", "accent"],
    ["success", "success-soft"], ["warning", "warning-soft"], ["danger", "danger-soft"]]) {
    const a = luminance(token(fg)), b = luminance(token(bg));
    assert.ok((Math.max(a, b) + .05) / (Math.min(a, b) + .05) >= 4.5, `${fg}/${bg}`);
  }
});
test("motion opt-out and keyboard focus rules stay in the design system", () => {
  assert.ok(css.includes("prefers-reduced-motion: reduce"));
  assert.ok(css.includes(":focus-visible"));
  assert.ok(css.includes("min-height: 44px"));
});
