import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {turnSummary, renderTurn} from "../../web/assets/chat-view.mjs";

test("real lowercase operations and unknown writes are not confused", () => {
  assert.match(turnSummary({status: "completed", writes: [{operation: "add"}, {operation: "noop"}], user_saved: true, duration_ms: 3}), /新增 1 条，复用 1 条/);
  assert.match(turnSummary({status: "failed", writes: null, user_saved: false}), /写入结果未提供/);
  assert.match(turnSummary({status: "failed", writes: [], user_saved: true}), /新增 0 条/);
});

test("render data as text including malicious model and evidence strings", () => {
  const document = {createElement(tag) {return {tag, children: [], append(...items) {this.children.push(...items);}};}};
  const malicious = '<script>alert("synthetic")</script>';
  const node = renderTurn(document, {input: malicious, answer: malicious, writes: [], status: "completed", retrieved: [{content: malicious}], memory_context: malicious});
  assert.equal(node.children[1].textContent, malicious);
  assert.equal(node.children[3].textContent, malicious);
  assert.ok(node.children[4].children[1].textContent.includes("<script>"));
  const script = readFileSync(new URL("../../web/assets/chat.js", import.meta.url), "utf8");
  const view = readFileSync(new URL("../../web/assets/chat-view.mjs", import.meta.url), "utf8");
  const html = readFileSync(new URL("../../web/chat.html", import.meta.url), "utf8");
  assert.ok(!/innerHTML|insertAdjacentHTML|document\.write|eval\(|localStorage|sessionStorage/.test(script + view));
  assert.ok(!/(?:src|href)=["']https?:/.test(html));
  assert.ok(!/setInterval|setTimeout/.test(script)); // 不靠轮询重发写入。
});
