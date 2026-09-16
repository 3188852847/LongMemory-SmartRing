import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {statusView, resultView, validTarget, errorMessage} from "../../web/assets/state.mjs";

test("offline and service failure are distinct; neither enables control", () => {
  const offline = statusView({connection_count: 0, ready: false});
  assert.equal(offline.bridge, "已连接");
  assert.equal(offline.set, false);
  assert.equal(statusView({error: "bridge_unavailable"}).bridge, "未连接");
});
test("only a single ready device with both tools enables writes", () => {
  const status = {connection_count: 1, ready: true, read_volume_supported: true, set_volume_supported: true};
  assert.equal(statusView(status).set, true);
  assert.equal(statusView({...status, connection_count: 2}).set, false);
  assert.equal(statusView({...status, read_volume_supported: false}).set, false);
});
test("target range is integer 5 through 100", () => {
  for (const v of [5, 30, 60, 100]) assert.equal(validTarget(v), true);
  for (const v of [4, 101, 30.1, NaN, "30", true]) assert.equal(validTarget(v), false);
});
test("ack without matching readback is not displayed as success", () => {
  const result = {requested_volume: 30, acknowledged: true, verified: false, readback_volume: null};
  assert.equal(resultView(result, "set").tone, "warning");
  assert.equal(resultView({...result, verified: true, readback_volume: 29}, "set").tone, "warning");
  assert.equal(resultView({...result, verified: true, readback_volume: 30}, "set").tone, "good");
});
test("server error and HTML strings never become display markup", () => {
  const attack = "<script>alert('synthetic')</script>";
  assert.ok(!errorMessage(attack).includes("<script>"));
  assert.equal(resultView({error: attack}, "set").tone, "error");
  const source = readFileSync(new URL("../../web/assets/app.js", import.meta.url), "utf8");
  assert.ok(!/\.innerHTML|insertAdjacentHTML|document\.write|eval\(/.test(source));
  assert.ok(!/Authorization|device-control\.token/.test(source));
  const html = readFileSync(new URL("../../web/index.html", import.meta.url), "utf8");
  assert.ok(!/(?:src|href)=["']https?:/.test(html));
  assert.ok(!/on(?:click|load|error)=/.test(html));
});
