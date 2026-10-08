/**
 * 给源码棘轮用的 import 图:一个模块在**运行时**引了哪些模块、从某个入口出发静态地能走到哪些。
 *
 * 只认静态的 `import … from` / `export … from` / `import "…"`;`import type …`、全是 `type` 的花括号、以及
 * 动态的 `import("…")`(按需加载的边界)都不算。路径认 `@/…` 和相对路径,补 `.ts` / `.tsx` / `index`;
 * 指向 npm 包的记成包名说明符,不往包里面走。
 *
 * 不是打包器 —— 判断的都是「入口能不能静态走到某个模块 / 某个包」这一类事。走到了会给出一条具体的链,
 * 判错了当场就看得出是扫描器的问题还是代码的问题。
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, normalize, relative } from "node:path";

export const SRC = join(import.meta.dirname, "..");

const STATIC_IMPORT = /^\s*(?:import|export)\s+([^;]*?)\s+from\s+["']([^"']+)["']/gms;
const SIDE_EFFECT_IMPORT = /^\s*import\s+["']([^"']+)["']/gm;

/** 一个说明符落到 src 下哪个文件(相对 src);指向 npm 包或解析不到时是 null。 */
export function resolveModule(spec: string, fromRel: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = normalize(join(SRC, dirname(fromRel), spec));
  else return null;
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx")]) {
    if (/\.tsx?$/.test(candidate) && existsSync(candidate) && statSync(candidate).isFile()) return relative(SRC, candidate);
  }
  return null;
}

function typeOnly(clause: string): boolean {
  const trimmed = clause.trim();
  if (/^type[\s{]/.test(trimmed)) return true;
  const braces = /^\{([^}]*)\}$/s.exec(trimmed);
  if (!braces) return false;
  const names = braces[1].split(",").map((name) => name.trim()).filter(Boolean);
  return names.length > 0 && names.every((name) => name.startsWith("type "));
}

export interface ModuleImports {
  /** src 下的模块(相对 src)。 */
  local: string[];
  /** npm 包的说明符,原样。 */
  packages: string[];
}

const cache = new Map<string, ModuleImports>();

/** 这个模块在运行时引了什么(相对 src 的路径)。 */
export function runtimeImports(rel: string): ModuleImports {
  const hit = cache.get(rel);
  if (hit) return hit;
  const code = readFileSync(join(SRC, rel), "utf8");
  const found: ModuleImports = { local: [], packages: [] };
  const add = (spec: string) => {
    const target = resolveModule(spec, rel);
    if (target) found.local.push(target);
    else if (!spec.startsWith(".") && !spec.startsWith("@/")) found.packages.push(spec);
  };
  for (const [, clause, spec] of code.matchAll(STATIC_IMPORT)) if (!typeOnly(clause)) add(spec);
  for (const [, spec] of code.matchAll(SIDE_EFFECT_IMPORT)) add(spec);
  cache.set(rel, found);
  return found;
}

/**
 * 从这些入口出发静态能走到的所有模块,以及走到每一个的那条链(入口在最前)。
 * `stopAt` 里的模块不往下走(用来问「去掉这一条边会怎样」)。
 */
export function staticClosure(entries: string[], stopAt: ReadonlySet<string> = new Set()): Map<string, string[]> {
  const chains = new Map<string, string[]>();
  const queue: string[] = [];
  for (const entry of entries) {
    chains.set(entry, [entry]);
    queue.push(entry);
  }
  while (queue.length) {
    const current = queue.shift()!;
    for (const next of runtimeImports(current).local) {
      if (chains.has(next) || stopAt.has(next)) continue;
      chains.set(next, [...chains.get(current)!, next]);
      queue.push(next);
    }
  }
  return chains;
}

/** 闭包里第一个引了某个包(说明符以 `prefix` 开头)的地方,连同那条链;没有就是 null。 */
export function firstPackageUse(closure: Map<string, string[]>, prefix: string): string[] | null {
  for (const [module, chain] of closure) {
    const spec = runtimeImports(module).packages.find((one) => one === prefix || one.startsWith(prefix));
    if (spec) return [...chain, spec];
  }
  return null;
}
