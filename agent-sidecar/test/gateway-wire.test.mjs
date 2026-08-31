/** Gateway is a plain completion: OAuth-capable model resolution, but no Agent tools or memory. */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.gateway-wire.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { runGatewayCompletion } = await import(pathToFileURL(outfile).href);

test("gateway sends a tool-free completion with sampling options and image pixels", async () => {
  const original = globalThis.fetch;
  let captured = null;
  globalThis.fetch = async (_url, init) => {
    if (captured === null && init?.body) captured = JSON.parse(String(init.body));
    return new Response("stubbed", { status: 500 });
  };
  try {
    await runGatewayCompletion({
      systemPrompt: "只给正文",
      prompt: "看图写一句",
      images: [{ type: "image", data: "aW1hZ2U=", mimeType: "image/png" }],
      provider: { baseUrl: "https://example.test/v1", apiKey: "k", vendor: "openai", vision: true },
      model: "vision-model",
      apiBase: "http://127.0.0.1:1",
      token: "ephemeral",
      options: { temperature: 0.7, maxTokens: 128, samplingParams: { top_p: 0.8 } },
    });
  } catch {
    // Deliberate 500: the actual supplier request is the assertion target.
  } finally {
    globalThis.fetch = original;
  }

  assert.ok(captured);
  assert.equal(captured.temperature, 0.7);
  assert.equal(captured.max_tokens ?? captured.max_completion_tokens, 128, JSON.stringify(captured));
  assert.equal(captured.top_p, 0.8);
  assert.equal(captured.messages[0].role, "system");
  assert.equal(captured.messages.at(-1).role, "user");
  assert.ok(captured.messages.at(-1).content.some((part) => part.type === "image_url"));
  assert.equal(captured.tools, undefined);
});
