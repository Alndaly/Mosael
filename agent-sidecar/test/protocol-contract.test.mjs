import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = JSON.parse(readFileSync(join(HERE, "..", "..", "contracts", "sidecar-protocol.json"), "utf8"));
const SOURCE = readFileSync(join(HERE, "..", "src", "protocol.ts"), "utf8");
const PI = readFileSync(join(HERE, "..", "src", "pi.ts"), "utf8");

function eventTypes() {
  const start = SOURCE.indexOf("export type Event =");
  const end = SOURCE.indexOf("\nexport ", start + 1);
  return [...SOURCE.slice(start, end).matchAll(/type:\s*"([a-z_]+)"/g)].map((m) => m[1]);
}

function requestTypes() {
  return [...SOURCE.matchAll(/export interface (\w*Request)\s*\{/g)]
    .map((m) => {
      const match = SOURCE.slice(m.index).match(/type:\s*"([a-z_]+)"/);
      return match?.[1];
    })
    .filter(Boolean);
}

test("protocol.ts request/event names match contracts/sidecar-protocol.json", () => {
  assert.deepEqual([...new Set(eventTypes())].sort(), [...CONTRACT.events].sort());
  assert.deepEqual([...new Set(requestTypes())].sort(), [...CONTRACT.requests].sort());
});

/** 一段 `"a" | "b" | …` 字符串联合里的成员。 */
function unionMembers(text) {
  return [...text.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
}

test("error 事件的 code 与 pi.ts 的 StallCode 都是契约里那组 error_codes", () => {
  const start = SOURCE.indexOf('type: "error";');
  const code = SOURCE.slice(start).match(/code\?:\s*([^;]+);/);
  assert.ok(code, "protocol.ts 的 error 事件没有 code 字段了?");
  assert.deepEqual(unionMembers(code[1]), [...CONTRACT.error_codes].sort());
  const stall = PI.match(/export type StallCode =([^;]+);/);
  assert.ok(stall, "pi.ts 没有 StallCode 了?");
  assert.deepEqual(unionMembers(stall[1]), [...CONTRACT.error_codes].sort());
});
