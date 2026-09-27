import { registerHooks } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

//: 被测模块用 `@/` 别名 import(Next 的 tsconfig paths)。node 自己不认它 —— 在这里把
//: `@/x` 指到 src/x.ts,测试读的就是页面构建时用的那一份,不另抄一份逻辑。
//: 先 import 这个文件,再 `await import()` 被测模块。
const SRC = path.resolve(import.meta.dirname, "..", "..", "src");
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      return nextResolve(pathToFileURL(path.join(SRC, `${specifier.slice(2)}.ts`)).href, context);
    }
    return nextResolve(specifier, context);
  },
});
