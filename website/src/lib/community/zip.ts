/**
 * 在浏览器里读一个插件 zip,**提交之前**把清单、权限、文件列表摊给作者看。
 *
 * 不引一个 zip 库:只需要中央目录 + 读一个文件,stored / deflate 两种方法,deflate 交给平台的
 * `DecompressionStream("deflate-raw")`。
 *
 * 规则照着桌面后端的「从文件安装」(backend/app/domain/plugins/registry.py):符号链接、越出根目录的
 * 路径、解压后过大,都在这里先指出来;清单取**最浅的那一份** `mosael.plugin.json`(GitHub 下下来的
 * zip 外面总套一层 `repo-main/`)。**这里只是预览** —— 真正的校验在社区服务,和桌面应用过同一套
 * (ADR 0026 §1「和桌面应用共用格式校验」),这里的判断不作数、也不替服务放行。
 */

export const MANIFEST_NAME = "mosael.plugin.json";
/** 和桌面后端同一组上限。 */
export const MAX_ARCHIVE_BYTES = 64 * 1024 * 1024;
export const MAX_UNPACKED_BYTES = 256 * 1024 * 1024;

export type ZipEntry = {
  name: string;
  size: number;
  compressedSize: number;
  method: number;
  offset: number;
  directory: boolean;
  symlink: boolean;
};

export type ZipProblem =
  | { code: "not_zip" }
  | { code: "too_large" }
  | { code: "unpacked_too_large" }
  | { code: "symlink"; name: string }
  | { code: "path_escape"; name: string }
  | { code: "no_manifest" }
  | { code: "manifest_invalid"; detail: string }
  | { code: "unsupported_method"; name: string };

export type PluginArchive = {
  entries: ZipEntry[];
  /** 清单所在那一层的前缀(`repo-main/` 或空串)。 */
  root: string;
  manifest: Record<string, unknown> | null;
  problems: ZipProblem[];
};

const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;

function findEndOfCentralDirectory(view: DataView): number {
  // EOCD 在最后 22 字节 + 至多 65535 字节的注释里。从后往前找签名。
  const earliest = Math.max(0, view.byteLength - 22 - 0xffff);
  for (let offset = view.byteLength - 22; offset >= earliest; offset -= 1) {
    if (view.getUint32(offset, true) === EOCD_SIGNATURE) return offset;
  }
  return -1;
}

/** 按段看路径:绝对路径、`..` 段、盘符、反斜杠都算越界。 */
export function escapesRoot(name: string): boolean {
  if (name.startsWith("/") || name.includes("\\") || /^[a-zA-Z]:/.test(name)) return true;
  return name.split("/").some((segment) => segment === "..");
}

export function listEntries(buffer: ArrayBuffer): ZipEntry[] | null {
  const view = new DataView(buffer);
  if (view.byteLength < 22) return null;
  const end = findEndOfCentralDirectory(view);
  if (end < 0) return null;
  const count = view.getUint16(end + 10, true);
  let cursor = view.getUint32(end + 16, true);
  const decoder = new TextDecoder();
  const entries: ZipEntry[] = [];
  for (let index = 0; index < count; index += 1) {
    if (cursor + 46 > view.byteLength || view.getUint32(cursor, true) !== CENTRAL_SIGNATURE) return null;
    const method = view.getUint16(cursor + 10, true);
    const compressedSize = view.getUint32(cursor + 20, true);
    const size = view.getUint32(cursor + 24, true);
    const nameLength = view.getUint16(cursor + 28, true);
    const extraLength = view.getUint16(cursor + 30, true);
    const commentLength = view.getUint16(cursor + 32, true);
    const external = view.getUint32(cursor + 38, true);
    const offset = view.getUint32(cursor + 42, true);
    const name = decoder.decode(new Uint8Array(buffer, cursor + 46, nameLength));
    // 高 16 位是 unix 的 st_mode;0o120000 是符号链接。
    const mode = (external >>> 16) & 0o170000;
    entries.push({
      name,
      size,
      compressedSize,
      method,
      offset,
      directory: name.endsWith("/"),
      symlink: mode === 0o120000,
    });
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function readEntry(buffer: ArrayBuffer, entry: ZipEntry): Promise<Uint8Array> {
  const view = new DataView(buffer);
  if (view.getUint32(entry.offset, true) !== LOCAL_SIGNATURE) throw new Error("bad local header");
  const nameLength = view.getUint16(entry.offset + 26, true);
  const extraLength = view.getUint16(entry.offset + 28, true);
  const start = entry.offset + 30 + nameLength + extraLength;
  const raw = new Uint8Array(buffer, start, entry.compressedSize);
  if (entry.method === 0) return raw;
  if (entry.method === 8) return inflateRaw(raw);
  throw new Error(`unsupported method ${entry.method}`);
}

/** 最浅的那一份清单(和后端 `_manifest_root` 同一条规则)。 */
function manifestEntry(entries: ZipEntry[]): ZipEntry | null {
  const candidates = entries
    .filter((entry) => !entry.directory && (entry.name === MANIFEST_NAME || entry.name.endsWith(`/${MANIFEST_NAME}`)))
    .sort((a, b) => a.name.split("/").length - b.name.split("/").length);
  return candidates[0] ?? null;
}

export async function inspectPluginArchive(buffer: ArrayBuffer): Promise<PluginArchive> {
  const problems: ZipProblem[] = [];
  if (buffer.byteLength > MAX_ARCHIVE_BYTES) problems.push({ code: "too_large" });
  const entries = listEntries(buffer);
  if (!entries) return { entries: [], root: "", manifest: null, problems: [...problems, { code: "not_zip" }] };

  let unpacked = 0;
  for (const entry of entries) {
    if (entry.symlink) problems.push({ code: "symlink", name: entry.name });
    if (escapesRoot(entry.name)) problems.push({ code: "path_escape", name: entry.name });
    unpacked += entry.size;
  }
  if (unpacked > MAX_UNPACKED_BYTES) problems.push({ code: "unpacked_too_large" });

  const found = manifestEntry(entries);
  if (!found) return { entries, root: "", manifest: null, problems: [...problems, { code: "no_manifest" }] };
  const root = found.name.slice(0, found.name.length - MANIFEST_NAME.length);
  let manifest: Record<string, unknown> | null = null;
  try {
    const bytes = await readEntry(buffer, found);
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("manifest is not an object");
    manifest = parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("unsupported method")) {
      problems.push({ code: "unsupported_method", name: found.name });
    } else {
      problems.push({ code: "manifest_invalid", detail: error instanceof Error ? error.message : String(error) });
    }
  }
  return { entries, root, manifest, problems };
}

/** 清单里给人看的文字可以是字符串,也可以按语言分(和后端 `manifest.text_of` 同一套约定)。 */
export function manifestText(value: unknown, locale: string): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  const pick = record[locale] ?? record.en ?? Object.values(record).find((one) => typeof one === "string");
  return typeof pick === "string" ? pick : "";
}

/** 预览要用的几项:id、名字、版本、运行方式、权限、工具。 */
export function manifestSummary(manifest: Record<string, unknown>, locale: string) {
  const runtime = manifest.runtime as { kind?: unknown } | undefined;
  const tools = (manifest.tools as { declare?: unknown } | undefined)?.declare;
  return {
    id: typeof manifest.id === "string" ? manifest.id : "",
    name: manifestText(manifest.name, locale),
    version: typeof manifest.version === "string" ? manifest.version : "",
    runtime: runtime?.kind === "mcp" ? ("mcp" as const) : ("script" as const),
    permissions: Array.isArray(manifest.permissions) ? manifest.permissions.filter((one): one is string => typeof one === "string") : [],
    tools: Array.isArray(tools)
      ? tools
          .filter((tool): tool is { name: string; description?: unknown } => Boolean(tool) && typeof (tool as { name?: unknown }).name === "string")
          .map((tool) => ({ name: tool.name, description: manifestText(tool.description, locale) }))
      : [],
  };
}
