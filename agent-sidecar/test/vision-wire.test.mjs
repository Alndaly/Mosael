/** A vision-capable selected agent model must receive the attached image in its real request. */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.vision-wire.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { runPiTurn } = await import(pathToFileURL(outfile).href);

async function captureRequest(vision) {
  const original = globalThis.fetch;
  let captured = null;
  globalThis.fetch = async (_url, init) => {
    if (captured === null && init?.body) captured = JSON.parse(String(init.body));
    return new Response("stubbed", { status: 500 });
  };
  try {
    await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "图片里是什么？",
        images: [{ type: "image", data: "aW1hZ2U=", mimeType: "image/png" }],
        provider: { baseUrl: "https://example.test/v1", apiKey: "k", vendor: "openai", vision },
        model: "vision-model",
        tools: [],
        apiBase: "http://127.0.0.1:1",
        token: "t",
      },
      {
        onDelta: () => {},
        onThinking: () => {},
        onThinkingEnd: () => {},
        onToolStart: () => {},
        onToolEnd: () => {},
      },
    );
  } catch {
    // The stub deliberately returns 500; only the outgoing payload matters.
  } finally {
    globalThis.fetch = original;
  }
  return captured;
}

test("vision model receives attached pixels", async () => {
  const body = await captureRequest(true);
  const content = body.messages.at(-1).content;
  assert.ok(Array.isArray(content));
  assert.equal(content[1].type, "image_url");
  assert.equal(content[1].image_url.url, "data:image/png;base64,aW1hZ2U=");
});

test("text-only model does not receive unsupported image content", async () => {
  const body = await captureRequest(false);
  assert.ok(!body.messages.at(-1).content.some((part) => part.type === "image_url"));
});
