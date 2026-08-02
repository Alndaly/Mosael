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

/**
 * 同名的深色版在哪。`/media/screens/x.png` → `/media/screens/dark/x.png`。
 *
 * 录制脚本(scripts/record-doc-media.py)把深色那套放在各目录的 `dark/` 子目录里、文件名
 * 保持一致 —— 于是文档正文里的 `![](/media/screens/x.png)` 一个字都不用改。
 */
export function darkTwin(src: string): string {
  const at = src.lastIndexOf("/");
  return at < 0 ? src : `${src.slice(0, at)}/dark${src.slice(at)}`;
}

/**
 * 配图的版本号,拼进 URL 当查询串。
 *
 * **重录之后文件变了、路径没变**,于是 `/_next/image?url=…` 这个 key 一模一样 —— 浏览器
 * 和 CDN 都会继续吐旧那张,而 Next 给图片响应带的是长缓存。表现是"我明明换了图,页面上
 * 还是老的",只能让每个人手动强刷一次,不现实。
 *
 * 取文件的大小 + mtime 而不是内容哈希:构建期要过几十张图,读一遍全部字节不值得,
 * 而这两个数只要文件被重写过就一定会变。
 */
export function mediaVersion(src: string): string {
  const file = path.join(process.cwd(), "public", src.replace(/^\//, ""));
  if (!fs.existsSync(file)) return "";
  const stat = fs.statSync(file);
  // `>>> 0` 转成无符号:异或结果可能是负数,而 URL 里挂一个 `?v=-gr8gad` 很难看。
  return ((stat.size ^ Math.floor(stat.mtimeMs)) >>> 0).toString(36);
}

/** 深色版可能还没录(脚本只覆盖了一部分场景),没有就退回浅色那张。 */
export function hasImage(src: string): boolean {
  return fs.existsSync(path.join(process.cwd(), "public", src.replace(/^\//, "")));
}

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
