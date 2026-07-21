/**
 * 重组 llama.cpp 系 byte-fallback token。
 *
 * 本地推理服务(Ollama / LM Studio)对词表外字符(常见 emoji)逐字节输出
 * `<0xF0>` 字面 token,UI 于是看到 `<0xF0><0x9F><0x97><0x84>`(🗄 的 UTF-8
 * 四字节)。后端落库前已重组(app/ai/agent/textclean.py);这里是渲染兜底,
 * 主要覆盖**流式中**的文本(delta 尚未落库)与历史存量消息。
 * 解不出合法 UTF-8 的串原样保留。
 */

const BYTE_RUN = /(?:<0[xX][0-9a-fA-F]{2}>)+/g;
const BYTE = /<0[xX]([0-9a-fA-F]{2})>/g;

export function decodeByteFallback(text: string): string {
  if (!text.includes("<0x") && !text.includes("<0X")) return text;
  return text.replace(BYTE_RUN, (run) => {
    const bytes = [...run.matchAll(BYTE)].map((m) => parseInt(m[1], 16));
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes));
    } catch {
      return run;
    }
  });
}
