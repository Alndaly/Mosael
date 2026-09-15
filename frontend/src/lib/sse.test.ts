import { describe, expect, it } from "vitest";

import { readSseData } from "@/lib/sse";

function chunked(text: string, cuts: number[]): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  let start = 0;
  return new ReadableStream({
    start(controller) {
      for (const end of [...cuts, bytes.length]) {
        controller.enqueue(bytes.slice(start, end));
        start = end;
      }
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<string[]> {
  const values: string[] = [];
  for await (const value of readSseData(stream)) values.push(value);
  return values;
}

describe("readSseData", () => {
  it("survives arbitrary byte chunks, including a split UTF-8 character", async () => {
    const source = 'data: {"text":"你好"}\n\ndata: {"done":true}\n\n';
    const firstChineseByte = new TextEncoder().encode(source.slice(0, source.indexOf("你"))).length;
    await expect(collect(chunked(source, [2, firstChineseByte + 1, firstChineseByte + 4]))).resolves.toEqual([
      '{"text":"你好"}',
      '{"done":true}',
    ]);
  });

  it("joins every data field and ignores comments and event metadata", async () => {
    const source = ': keep-alive\r\nevent: update\r\nid: 7\r\ndata: {\r\ndata: "text": "ok"\r\ndata: }\r\n\r\n';
    await expect(collect(chunked(source, [17, 45]))).resolves.toEqual(['{\n"text": "ok"\n}']);
  });

  it("emits the final complete payload when the response closes without a blank line", async () => {
    await expect(collect(chunked("data: final", [4]))).resolves.toEqual(["final"]);
  });
});

