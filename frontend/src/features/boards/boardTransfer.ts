import type { BoardCanvas } from "@/api/client";
import type { MessageKey } from "@/app/messages";

/**
 * 创意画板的文件格式:导出 / 导入**只导画布结构**,不导素材二进制、原图或缩略图。
 *
 * 这份文件和社区是同一份东西:
 * - 导出的 `<画板名>.mosael-board.json` 就是用户会传到社区的那份 `.json`(上传表单的 `kind=board` 收 JSON);
 * - 从社区下载回来的 `.json`,用同一条导入读进来 —— 不需要深链,也不做自动导入。
 *
 * **大小上限和社区对齐:2 MiB(2,097,152 字节)**,量的也是**紧凑 JSON 的 UTF-8 字节数**
 * (不是磁盘上带缩进的文件大小)。社区后端 `MAX_PAYLOAD_BYTES` 和官网 `share-utils.ts` 的
 * `MAX_SHARE_BYTES` 是同一个数值、同一把尺子 —— 这样这里导出的文件传得上去,那边下载的文件
 * 也一定导得进来,不会出现「本地说没超、社区回 413」。
 */
export const MAX_BOARD_FILE_BYTES = 2 * 1024 * 1024;
export const BOARD_FILE_FORMAT = "mosael.board";
export const BOARD_FILE_VERSION = 1;

/** 落成文件的那一份。`canvas` 是加载中的画布**原样**,不裁剪、不把素材展开成二进制。 */
export interface BoardFile {
  format: typeof BOARD_FILE_FORMAT;
  version: typeof BOARD_FILE_VERSION;
  name: string;
  canvas: BoardCanvas;
}

export interface ImportedBoardFile {
  /** 文件里的 `name`;没写就退回文件名。 */
  name: string;
  canvas: BoardCanvas;
  /** 紧凑 JSON 的 UTF-8 字节数(和社区同一把尺子)。 */
  bytes: number;
}

export type BoardFileProblem = "invalidJson" | "notBoard" | "noCanvas" | "tooLarge" | "version";

/** 导入被拒的原因(给代码看);给用户看的那一句在 `boardImportErrorText`。 */
export class BoardFileError extends Error {
  constructor(
    readonly problem: BoardFileProblem,
    /** 不认识的版本号(给人看的那一句里要带上它)。 */
    readonly version?: string,
  ) {
    super(problem);
    this.name = "BoardFileError";
  }
}

const PROBLEM_KEYS: Record<BoardFileProblem, MessageKey> = {
  invalidJson: "boardsImportInvalidJson",
  notBoard: "boardsImportNotBoard",
  noCanvas: "boardsImportNoCanvas",
  tooLarge: "boardsImportTooLarge",
  version: "boardsImportVersion",
};

/** 导入失败时给用户看的那一句 —— **不是错误码**。 */
export function boardImportErrorText(t: (key: MessageKey) => string, error: BoardFileError): string {
  return t(PROBLEM_KEYS[error.problem]).replace("{version}", error.version ?? "?");
}

/** 当前这份画布 + 名字 -> 文件内容。`canvas` 原样带上(引用同一个对象,不复制、不裁字段)。 */
export function boardFileOf(name: string, canvas: BoardCanvas): BoardFile {
  return { format: BOARD_FILE_FORMAT, version: BOARD_FILE_VERSION, name, canvas };
}

/** Windows / macOS / Linux 都不该出现在文件名里的那些字符。 */
// eslint-disable-next-line no-control-regex
const ILLEGAL_FILENAME = /[\u0000-\u001f<>:"/\\|?*]/g;

/** 名字最多留多少:80 个码点,同时不超过 200 个 UTF-8 字节 —— Linux 的文件名上限是 255 字节,
 *  给 `.mosael-board.json` 这 18 个字节留够,中文名也存得下(一个汉字 3 字节)。 */
const MAX_STEM_CHARS = 80;
const MAX_STEM_BYTES = 200;

function clampStem(value: string): string {
  const encoder = new TextEncoder();
  let out = "";
  let bytes = 0;
  for (const char of Array.from(value).slice(0, MAX_STEM_CHARS)) {
    const size = encoder.encode(char).length;
    if (bytes + size > MAX_STEM_BYTES) break;
    out += char;
    bytes += size;
  }
  return out;
}

/**
 * 导出文件名:`<画板名>.mosael-board.json`。
 *
 * 非法字符换成 `_`,结尾的点和空格去掉(Windows 存不下),名字按码点和 UTF-8 字节双重封顶再拼
 * 扩展名 —— 文件系统会在 255 字节左右截断,截掉了扩展名用户就不知道该拿它干什么。按码点截,
 * 不会把一个 emoji 劈成两半。
 */
export function boardExportFilename(name: string): string {
  const safe = Array.from(name.trim().replace(ILLEGAL_FILENAME, "_"))
    .join("")
    .replace(/[. ]+$/g, "")
    .trim();
  const stem = clampStem(safe) || "board";
  return `${stem}.mosael-board.json`;
}

/**
 * 导入时新画板的名字:文件里的名字,和已有画板重名就加「副本」后缀;副本也重名就再编号
 * (`灵感 副本 2`、`灵感 副本 3`……),不会悄悄覆盖或并存两张同名板。
 */
export function uniqueBoardName(
  name: string,
  existing: Iterable<string>,
  copyName: (name: string) => string,
): string {
  const taken = new Set(existing);
  if (!taken.has(name)) return name;
  const base = copyName(name);
  let candidate = base;
  for (let n = 2; taken.has(candidate); n += 1) candidate = `${base} ${n}`;
  return candidate;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function compactBytes(value: unknown): number {
  const encoded = JSON.stringify(value);
  return encoded === undefined ? 0 : new TextEncoder().encode(encoded).length;
}

/** 文件里没写名字时,退回文件名(`我的画板.mosael-board.json` -> `我的画板`)。 */
function nameFromFilename(filename: string): string {
  const base = filename.trim().replace(/\\/g, "/").split("/").pop() ?? "";
  return base.replace(/\.mosael-board\.json$/i, "").replace(/\.json$/i, "").trim();
}

/**
 * 读一份画板文件。按顺序校验:JSON、大小(紧凑 JSON 字节数)、`format`、`version`、`canvas` 是对象。
 * 任何一条不过都抛 `BoardFileError`,由界面翻成一句人话。
 */
export function parseBoardFile(text: string, filename = ""): ImportedBoardFile {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new BoardFileError("invalidJson");
  }
  const bytes = compactBytes(data);
  if (bytes > MAX_BOARD_FILE_BYTES) throw new BoardFileError("tooLarge");
  if (!isRecord(data) || data.format !== BOARD_FILE_FORMAT) throw new BoardFileError("notBoard");
  if (data.version !== BOARD_FILE_VERSION) {
    throw new BoardFileError("version", typeof data.version === "number" || typeof data.version === "string" ? String(data.version) : "?");
  }
  if (!isRecord(data.canvas)) throw new BoardFileError("noCanvas");
  const name =
    typeof data.name === "string" && data.name.trim() ? data.name.trim() : nameFromFilename(filename);
  return { name, canvas: data.canvas as unknown as BoardCanvas, bytes };
}

/**
 * 从选中的文件读。**明显过大时先按文件大小挡掉,不读进内存**(和社区上传表单同一条):
 * 文件本身超过上限的 8 倍时,即便全是缩进和空白,紧凑 JSON 也一定超;接近上限的仍要解析后精确量。
 */
export async function readBoardFile(file: Pick<File, "size" | "text" | "name">): Promise<ImportedBoardFile> {
  if (file.size > MAX_BOARD_FILE_BYTES * 8) throw new BoardFileError("tooLarge");
  return parseBoardFile(await file.text(), file.name);
}
