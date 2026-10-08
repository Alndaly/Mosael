import { registerHooks } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

//: 让测试直接 import 站点源码(`src/**/*.ts`):Next 认 `@/x` 这个别名、也认不写扩展名的相对路径,Node 两样都不认。
//: 这里只补这两条 —— 其余照 Node 自己的解析走。TSX(组件)照旧 import 不了,要测的逻辑放在 .ts 里。
const SRC = path.resolve(import.meta.dirname, "..", "src");

export function registerSourceAliases() {
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier.startsWith("@/")) {
        return nextResolve(pathToFileURL(path.join(SRC, `${specifier.slice(2)}.ts`)).href, context);
      }
      const fromSource = context.parentURL?.startsWith("file:") && fileURLToPath(context.parentURL).startsWith(SRC);
      if (fromSource && specifier.startsWith(".") && !path.extname(specifier)) {
        return nextResolve(`${specifier}.ts`, context);
      }
      return nextResolve(specifier, context);
    },
  });
}
