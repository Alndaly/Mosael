import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONTRACT = JSON.parse(readFileSync(join(HERE, "..", "..", "contracts", "sidecar-protocol.json"), "utf8"));
const SOURCE = readFileSync(join(HERE, "..", "src", "protocol.ts"), "utf8");

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
