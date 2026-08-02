import fs from "node:fs";
import path from "node:path";

/**
 * 从文件头读图片尺寸。
 *
 * next/image 要真实的 width/height —— 它按这两个数算出宽高比来占位,填错了图会被拉变形。
 * 文档正文里的 `![]()` 只给得出路径,所以尺寸在构建时从 public/ 下的文件里读。
 *
 * 只认 PNG 和 GIF:这两种就是 `scripts/record-doc-media.py` 的全部产物。多出第三种格式时
 * 这里会明确抛错,而不是悄悄回落到一个猜的比例。
 */
const cache = new Map<string, { width: number; height: number }>();

export function imageSize(src: string): { width: number; height: number } {
  const cached = cache.get(src);
  if (cached) return cached;

  const file = path.join(process.cwd(), "public", src.replace(/^\//, ""));
  const head = Buffer.alloc(32);
  const fd = fs.openSync(file, "r");
  try {
    fs.readSync(fd, head, 0, head.length, 0);
  } finally {
    fs.closeSync(fd);
  }

  let size: { width: number; height: number };
  if (head.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    // PNG:IHDR 是必须的第一个块,宽高是它的头两个 uint32(大端)。
    size = { width: head.readUInt32BE(16), height: head.readUInt32BE(20) };
  } else if (head.subarray(0, 3).toString("latin1") === "GIF") {
    // GIF:逻辑屏幕描述符紧跟 6 字节签名,宽高是两个 uint16(小端)。
    size = { width: head.readUInt16LE(6), height: head.readUInt16LE(8) };
  } else {
    throw new Error(`无法识别的图片格式(只支持 PNG / GIF):${src}`);
  }

  cache.set(src, size);
  return size;
}
