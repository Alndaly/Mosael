/**
 * 内嵌浏览器(electron/browser)的分层:每一块只往下依赖,文件之间也不许成环。
 *
 * 从下往上:
 *
 *   根(types / errors / log / trace)  各块共用的形状与日志
 *   driver/   页面驱动与纯页面操作(读页、取图、坐标换算):只认一个 webContents,不认识视图怎么摆
 *   views/    视图管理器、浮层、悬浮面板、下载,以及在主窗口里建它们的视图宿主(viewHost)
 *   page/     顶栏的页面工具(截图、取图、读页、下载):作用于前台那个视图
 *   comfy/    ComfyUI 工作台:借宿主的视图开工作台会话
 *   publish/  发布执行器与平台适配器:借宿主的视图跑发布、登录、复检
 *   pool/     浏览器池的 RPA / 智能体执行器:动作要用到顶栏的页面工具,工作台调用交给 comfy
 *
 * 此前四块互相认识:页面驱动和顶栏工具同在 page/ 里,视图管理器要用驱动、顶栏工具又要用视图管理器;RPA 为了
 * 调一次 ComfyUI 工作台要 import 发布执行器(工作台和视图宿主都写在 publishWorker 里);共用的 types 回头 import
 * 发布的平台表。改一块就得懂另外三块。
 */
import fs from "node:fs";
import path from "node:path";

import { expect, it } from "vitest";

const ROOT = path.dirname(new URL(import.meta.url).pathname);
type Layer = "root" | "driver" | "views" | "page" | "comfy" | "publish" | "pool";

/** 每一块能依赖哪几块(自己那一块随便用)。 */
const ALLOWED: Record<Layer, Layer[]> = {
  root: [],
  driver: ["root"],
  views: ["root", "driver"],
  page: ["root", "driver", "views"],
  comfy: ["root", "driver", "views"],
  publish: ["root", "driver", "views"],
  pool: ["root", "driver", "views", "page", "comfy"],
};

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "fixtures" ? [] : sources(full);
    if (!/\.(ts|cjs)$/.test(entry.name) || /\.test\.ts$|\.d\.cts$/.test(entry.name)) return [];
    return [full];
  });
}

function layerOf(file: string): Layer | null {
  const rel = path.relative(ROOT, file);
  if (rel.startsWith("..") || rel === "index.ts") return null;
  const head = rel.split(path.sep)[0];
  if (!rel.includes(path.sep)) return "root";
  return head in ALLOWED ? (head as Layer) : null;
}

function resolveImport(from: string, spec: string): string | null {
  if (!spec.startsWith(".")) return null;
  const base = path.resolve(path.dirname(from), spec);
  for (const candidate of [base, `${base}.ts`, `${base}.cjs`, path.join(base, "index.ts")]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** 这个文件引了浏览器里的哪些文件(import / export from / require / 动态 import;只看 `import type` 以外的也算 —— 类型也是认识)。 */
function importsOf(file: string): string[] {
  const text = fs.readFileSync(file, "utf8");
  const specs = [...text.matchAll(/(?:from\s+|require\(\s*|import\(\s*)["'](\.[^"']+)["']/g)].map((match) => match[1]);
  return specs.map((spec) => resolveImport(file, spec)).filter((target): target is string => target !== null && layerOf(target) !== null);
}

const FILES = sources(ROOT).filter((file) => layerOf(file) !== null);
const GRAPH = new Map(FILES.map((file) => [file, importsOf(file)]));

it("每一块只往下依赖(见文件顶上的分层)", () => {
  const violations: string[] = [];
  for (const [file, targets] of GRAPH) {
    const from = layerOf(file)!;
    for (const target of targets) {
      const to = layerOf(target)!;
      if (to !== from && !ALLOWED[from].includes(to)) {
        violations.push(`${path.relative(ROOT, file)} → ${path.relative(ROOT, target)}(${from} 不该认识 ${to})`);
      }
    }
  }
  expect(violations).toEqual([]);
});

it("文件之间没有环", () => {
  const state = new Map<string, "visiting" | "done">();
  const cycles: string[] = [];
  const visit = (file: string, trail: string[]) => {
    if (state.get(file) === "done") return;
    if (state.get(file) === "visiting") {
      cycles.push([...trail.slice(trail.indexOf(file)), file].map((one) => path.relative(ROOT, one)).join(" → "));
      return;
    }
    state.set(file, "visiting");
    for (const target of GRAPH.get(file) ?? []) visit(target, [...trail, file]);
    state.set(file, "done");
  };
  for (const file of FILES) visit(file, []);
  expect(cycles).toEqual([]);
});

it("扫描面自己也有人看着:每一块都扫到了文件", () => {
  const seen = new Set(FILES.map((file) => layerOf(file)));
  expect([...seen].sort()).toEqual(Object.keys(ALLOWED).sort());
});
