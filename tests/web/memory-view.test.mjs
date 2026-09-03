import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {memoryError, displayTime, pageState, metadata} from "../../web/assets/memory-view.mjs";

test("empty list and pagination have explicit limits", () => {
  assert.deepEqual(pageState(0, 0, 25), {previous: false, next: false, label: "0 条"});
  assert.equal(pageState(26, 0, 25).next, true);
  assert.equal(pageState(26, 25, 25).label, "26–26 / 26");
  assert.equal(pageState(26, 50, 25).label, "当前页为空 / 共 26 条");
  assert.equal(pageState(100100, 100000, 25).next, false);
});
test("unknown valid time never falls back to recorded time", () => {
  assert.equal(displayTime(null), "未记录");
  const items = metadata({id: "synthetic", subject_id: "user:self", recorded_at: "2026-09-03T00:00:00Z"});
  assert.equal(items.find(([label]) => label === "事实生效时间")[1], "未记录");
});
test("errors distinguish stale confirmation from unknown outcome", () => {
  assert.ok(memoryError("memory_changed").includes("未执行删除"));
  assert.ok(memoryError("arbitrary_unknown").includes("结果可能未知"));
  assert.ok(!memoryError("<script>alert(1)</script>").includes("<script>"));
});
test("memory rendering uses text nodes and delete requires explicit confirmation", () => {
  const script = readFileSync(new URL("../../web/assets/memories.js", import.meta.url), "utf8");
  const html = readFileSync(new URL("../../web/memories.html", import.meta.url), "utf8");
  assert.ok(!/\.innerHTML|insertAdjacentHTML|document\.write|eval\(/.test(script));
  assert.ok(!/localStorage|sessionStorage/.test(script));
  assert.ok(script.includes("node.textContent = text"));
  assert.ok(script.includes('el("delete-dialog").showModal()'));
  assert.ok(script.includes("revision: selected.revision, confirm_delete: true"));
  assert.ok(!/(?:src|href)=["']https?:/.test(html));
  assert.ok(html.includes('id="delete-cancel"') && html.includes("autofocus"));
});
