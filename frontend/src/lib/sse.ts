/**
 * Incremental Server-Sent Events decoder.
 *
 * Fetch streams can split anywhere, including inside a UTF-8 code point or between the two
 * newlines that terminate an event.  Keeping that transport state here lets chat surfaces consume
 * complete `data` payloads instead of each carrying a subtly different parser.
 */

function dataOf(block: string): string | null {
  const lines: string[] = [];
  for (const line of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    if (field !== "data") continue;
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    lines.push(value);
  }
  return lines.length > 0 ? lines.join("\n") : null;
}

/** Yield one complete `data` payload per SSE event, joining repeated data fields per the spec. */
export async function* readSseData(stream: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });

      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = dataOf(block);
        if (data !== null) yield data;
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
      if (done) break;
    }

    // A closed response is a complete transport boundary. Accept its last event even if a proxy
    // stripped the final blank line; malformed JSON remains the consumer's responsibility.
    const finalData = dataOf(buffer);
    if (finalData !== null) yield finalData;
  } finally {
    reader.releaseLock();
  }
}

