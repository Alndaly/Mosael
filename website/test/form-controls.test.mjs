import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: 官网表单控件的验收契约:原生 `<select>` / `<option>` / `<textarea>` / `<label>` 全部退场,
//: 换成 `components/ui/` 下的 shadcn 组件(Input / Textarea / Select / Label)。
//:
//: ② 的棘轮扫的是**业务源码**,排除 `components/ui/**` —— 组件内部当然还是原生标签,
//: 原生标签正是 shadcn 组件的实现方式。唯一放行的例外是 `<input type="file">`:文件选择
//: 只能由浏览器原生文件框完成(见 `upload-form.tsx` 的隐藏 input + 按钮)。
//:
//: ④ 是一条真键盘交互测试:用 monorepo 里已经装好的 jsdom + @testing-library/user-event
//: (来自 frontend 的 devDependencies,官网自身**没有**新增依赖)渲染 `ui/select.tsx`,
//: 走 Enter 开菜单 / 方向键移动 / Enter 确认 / Esc 关闭。若这套测试环境不在(例如只装了
//: website 一个包),这条测试会跳过,但③的结构断言仍然会守住「select 是 Radix 的」。
const ROOT = path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "src");
const UI = path.join(SRC, "components", "ui");

const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const exists = (relative) => fs.existsSync(path.join(ROOT, relative));

const walk = (dir) =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });

const businessSources = walk(SRC)
  .filter((file) => /\.(ts|tsx)$/.test(file))
  .filter((file) => !file.startsWith(UI + path.sep))
  .map((file) => ({ file: path.relative(ROOT, file), source: fs.readFileSync(file, "utf8") }));

/** 注释里写的示例标签不算「用了原生控件」,扫之前先去掉块注释和整行注释。 */
const stripComments = (source) =>
  source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");

/**
 * 取出一段源码里某个标签的完整开标签。
 *
 * 不能用 `/<input\b[^>]*>/`:JSX 属性里的箭头函数(`onChange={(event) => ...}`)带一个 `>`,
 * 正则会把它当成标签结束,后半截属性就漏扫了。这里按引号和花括号深度走,遇到顶层的 `>` 才停。
 */
const openingTags = (source, tag) => {
  const tags = [];
  const pattern = new RegExp(`<${tag}\\b`, "g");
  let found = pattern.exec(source);
  while (found) {
    let index = found.index + found[0].length;
    let braces = 0;
    let quote = null;
    for (; index < source.length; index += 1) {
      const char = source[index];
      if (quote) {
        if (char === quote && source[index - 1] !== "\\") quote = null;
        continue;
      }
      if (char === '"' || char === "'") quote = char;
      else if (char === "{") braces += 1;
      else if (char === "}") braces = Math.max(0, braces - 1);
      else if (char === ">" && braces === 0) break;
    }
    tags.push(source.slice(found.index, index + 1));
    pattern.lastIndex = index + 1;
    found = pattern.exec(source);
  }
  return tags;
};

const packageJson = JSON.parse(read("package.json"));

test("① 上传页的两个下拉都是 shadcn Select,没有原生 <select> / <option>", () => {
  const upload = read("src/components/community/upload-form.tsx");
  assert.doesNotMatch(stripComments(upload), /<select\b/, "上传页还有原生 <select>");
  assert.doesNotMatch(stripComments(upload), /<option\b/, "上传页还有原生 <option>");
  assert.match(upload, /from "@\/components\/ui\/select"/, "上传页没有引入 ui/select");
  assert.match(upload, /<Select\s+value=\{kind\}/, "类型没有用 Select");
  assert.match(upload, /<SelectTrigger id="share-kind"/, "类型下拉的 trigger 没有挂 id(和 Label 对不上)");
  assert.match(upload, /<SelectItem value="workflow">/, "类型下拉缺少 workflow 选项");
  assert.match(upload, /<SelectItem value="board">/, "类型下拉缺少 board 选项");
  assert.match(upload, /<Select\s+value=\{license \|\| "none"\}/, "许可没有用 Select");
  assert.match(upload, /<SelectTrigger id="share-license"/, "许可下拉的 trigger 没有挂 id(和 Label 对不上)");
  // Radix Select 的 Item 不能用空字符串做 value;「未声明」用一个显式哨兵,提交时再折回空串。
  assert.match(upload, /<SelectItem value="none">/, "没有把「未声明」做成显式选项");
  assert.match(upload, /license: license \|\| undefined/, "提交时没有把「未声明」折回 undefined");
});

test("② 业务源码里没有原生 select / option / textarea / label,<input> 只剩 type=\"file\"", () => {
  const native = businessSources.flatMap(({ file, source }) => {
    const clean = stripComments(source);
    return ["select", "option", "textarea", "label"].flatMap((tag) =>
      openingTags(clean, tag).map((match) => `${file}: ${match.replace(/\s+/g, " ")}`),
    );
  });
  assert.deepEqual(native, [], "还有原生表单标签");

  const inputs = businessSources.flatMap(({ file, source }) =>
    openingTags(stripComments(source), "input").map((tag) => ({ file, tag })),
  );
  const nativeInputs = inputs.filter(({ tag }) => !/\btype="file"/.test(tag));
  assert.deepEqual(nativeInputs, [], "还有非文件类型的原生 <input>");
  assert.deepEqual(
    inputs.filter(({ tag }) => /\btype="file"/.test(tag)).map(({ file }) => file),
    ["src/components/community/upload-form.tsx"],
    "文件选择之外不该再有原生 input",
  );
});

test("③ ui/ 下补齐 shadcn 组件;select.tsx 是 radix-ui 的 Select,不是 div 拼的", () => {
  for (const name of ["input.tsx", "textarea.tsx", "select.tsx", "label.tsx"]) {
    assert.ok(exists(`src/components/ui/${name}`), `缺少 shadcn 组件 ui/${name}`);
  }
  const select = read("src/components/ui/select.tsx");
  assert.match(select, /from "radix-ui"/, "select 没基于 radix-ui");
  assert.match(select, /Select as SelectPrimitive/, "select 没从 radix-ui 取 Select 原子");
  for (const primitive of ["Root", "Trigger", "Value", "Content", "Item", "ItemText", "ItemIndicator", "Viewport"]) {
    assert.match(select, new RegExp(`SelectPrimitive\\.${primitive}\\b`), `select 没有用 Radix 的 ${primitive}`);
  }
  assert.doesNotMatch(select, /role="combobox"/, "select 在自己手写 combobox 角色,而不是交给 Radix");
  assert.doesNotMatch(select, /role="listbox"/, "select 在自己手写 listbox 角色,而不是交给 Radix");
  assert.doesNotMatch(stripComments(select), /<select\b/, "select.tsx 自己还在用原生 select");

  for (const name of ["input.tsx", "textarea.tsx", "select.tsx"]) {
    const source = read(`src/components/ui/${name}`);
    // 环的宽度不钉死(站点用 ring-4,shadcn 默认 ring-3 也行),但必须有焦点环。
    assert.match(source, /focus-visible:[a-z-]*(ring|border-primary)/, `${name} 没写聚焦环`);
    assert.match(source, /aria-invalid:/, `${name} 没写 aria-invalid 样式`);
    assert.match(source, /disabled:/, `${name} 没写禁用态`);
    assert.match(source, /dark:/, `${name} 没写深色档样式`);
  }

  // 没用到 checkbox,就不为了「凑齐」加一个死组件。
  assert.equal(exists("src/components/ui/checkbox.tsx"), false, "没有用到 checkbox,不该新增");
  assert.equal(packageJson.dependencies["@testing-library/react"], undefined, "官网不该为了测试新增运行依赖");
  assert.equal(packageJson.devDependencies?.jsdom, undefined, "官网不该为了测试新增 jsdom 依赖");
  assert.ok(packageJson.dependencies["radix-ui"], "radix-ui 不该从依赖里消失");
});

test("⑤ Label 通过 htmlFor / id 与控件关联,错误也仍在 aria-describedby 里", () => {
  const files = [
    "src/components/account/form-controls.tsx",
    "src/components/community/upload-form.tsx",
    "src/components/community/identity-form.tsx",
    "src/components/community/share-detail.tsx",
  ];
  for (const file of files) {
    const source = stripComments(read(file));
    if (/<Label\b[^>]*htmlFor=\{id\}/.test(source)) {
      // 账号表单是通用零件:htmlFor / id 都来自调用方传进来的同一个 id,静态比字面量没有意义。
      assert.match(source, /<Input\b[\s\S]*?\bid=\{id\}/, `${file} 的 Label htmlFor={id} 没有接到 Input 的 id={id}`);
      continue;
    }
    const labels = [...source.matchAll(/<Label\b[^>]*htmlFor="([^"]+)"/g)].map((match) => match[1]);
    assert.ok(labels.length > 0, `${file} 没有用 Label`);
    for (const id of labels) {
      assert.ok(
        new RegExp(`id="${id}"`).test(source),
        `${file} 的 Label htmlFor="${id}" 找不到对应控件 id`,
      );
    }
  }
  // 账号表单的 hint / error 仍进 aria-describedby,没为了换组件丢掉错误关联。
  const controls = read("src/components/account/form-controls.tsx");
  assert.match(controls, /aria-describedby=\{describedBy\}/, "账号字段丢了 aria-describedby");
  assert.match(controls, /aria-invalid=\{Boolean\(error\)\}/, "账号字段丢了 aria-invalid");
  assert.match(controls, /role="alert"/, "账号字段丢了错误提示");
  const upload = read("src/components/community/upload-form.tsx");
  assert.match(upload, /aria-describedby=\{titleError \? "share-title-error" : undefined\}/, "标题字段丢了错误关联");
  assert.match(upload, /<Label htmlFor="share-title">/, "标题字段没有用 Label");
});

test("④ 键盘可用:Enter 开菜单、方向键移动、Enter 确认、Esc 关闭(真交互)", {
  skip: keyboardHarnessMissing() || false,
}, async () => {
  const harness = await openKeyboardHarness();
  try {
    const { React, render, screen, userEvent } = harness;
    const user = userEvent.setup({ document: harness.window.document });
    const view = render(React.createElement(harness.Demo));

    // Label 与 trigger 的关联先立住:by label 找得到 combobox。
    const trigger = screen.getByLabelText("Kind");
    assert.equal(trigger.getAttribute("role"), "combobox");
    assert.equal(trigger.getAttribute("aria-expanded"), "false");

    trigger.focus();
    await user.keyboard("{Enter}");
    assert.equal(screen.queryAllByRole("listbox").length, 1, "Enter 没有打开下拉");
    assert.equal(trigger.getAttribute("aria-expanded"), "true");

    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");
    assert.equal(screen.getByTestId("value").textContent, "board", "方向键 + Enter 没有选中下一项");
    assert.equal(screen.queryAllByRole("listbox").length, 0, "选中后菜单没有关闭");

    trigger.focus();
    await user.keyboard("{Enter}");
    assert.equal(screen.queryAllByRole("listbox").length, 1, "第二次 Enter 没有打开下拉");
    await user.keyboard("{Escape}");
    assert.equal(screen.queryAllByRole("listbox").length, 0, "Esc 没有关闭下拉");
    assert.equal(harness.window.document.activeElement, trigger, "Esc 关闭后焦点没有回到 trigger");
    assert.equal(trigger.getAttribute("aria-expanded"), "false");

    view.unmount();
  } finally {
    harness.close();
  }
});

/** 交互测试的依赖在 monorepo 里已有(frontend 的 devDependencies + 根上的 esbuild),官网不新增。 */
function keyboardHarnessMissing() {
  const candidates = [
    path.join(ROOT, "..", "node_modules", "esbuild", "lib", "main.js"),
    path.join(ROOT, "..", "frontend", "node_modules", "jsdom", "lib", "api.js"),
    path.join(ROOT, "..", "frontend", "node_modules", "@testing-library", "react", "package.json"),
    path.join(ROOT, "..", "frontend", "node_modules", "@testing-library", "user-event", "package.json"),
  ];
  const missing = candidates.filter((file) => !fs.existsSync(file));
  return missing.length === 0 ? false : `缺少交互测试环境: ${missing.map((file) => path.relative(ROOT, file)).join(", ")}`;
}

async function openKeyboardHarness() {
  const WEBSITE = ROOT;
  const FRONTEND = path.join(ROOT, "..", "frontend", "node_modules");
  const ESBUILD = path.join(ROOT, "..", "node_modules", "esbuild", "lib", "main.js");
  const esbuild = await import(pathToFileURL(ESBUILD).href);
  const { JSDOM } = await import(pathToFileURL(path.join(FRONTEND, "jsdom", "lib", "api.js")).href);

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-select-"));
  const entry = path.join(tmp, "entry.tsx");
  const bundle = path.join(tmp, "bundle.mjs");
  fs.writeFileSync(
    entry,
    [
      'import * as React from "react";',
      `import { render, screen } from ${JSON.stringify(path.join(FRONTEND, "@testing-library", "react"))};`,
      `import userEvent from ${JSON.stringify(path.join(FRONTEND, "@testing-library", "user-event"))};`,
      'import { Label } from "@/components/ui/label";',
      'import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";',
      "",
      "function Demo() {",
      '  const [value, setValue] = React.useState("workflow");',
      "  return (",
      "    <div>",
      '      <Label htmlFor="kind">Kind</Label>',
      '      <Select value={value} onValueChange={setValue}>',
      '        <SelectTrigger id="kind">',
      "          <SelectValue />",
      "        </SelectTrigger>",
      "        <SelectContent>",
      '          <SelectItem value="workflow">Workflow</SelectItem>',
      '          <SelectItem value="board">Board</SelectItem>',
      "        </SelectContent>",
      "      </Select>",
      '      <output data-testid="value">{value}</output>',
      "    </div>",
      "  );",
      "}",
      "",
      "export { Demo, render, screen, userEvent, React };",
      "",
    ].join("\n"),
  );

  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    format: "esm",
    platform: "browser",
    jsx: "automatic",
    outfile: bundle,
    logLevel: "silent",
    // 组件和测试库必须共用同一份 React,否则 hooks 会报「Invalid hook call」。
    alias: {
      react: path.join(WEBSITE, "node_modules", "react"),
      "react-dom": path.join(WEBSITE, "node_modules", "react-dom"),
      "react/jsx-runtime": path.join(WEBSITE, "node_modules", "react", "jsx-runtime.js"),
      "react/jsx-dev-runtime": path.join(WEBSITE, "node_modules", "react", "jsx-dev-runtime.js"),
    },
    plugins: [
      {
        name: "at-alias",
        setup(build) {
          build.onResolve({ filter: /^@\// }, (args) => {
            const base = path.join(SRC, args.path.slice(2));
            for (const suffix of ["", ".tsx", ".ts", ".jsx", ".js"]) {
              if (fs.existsSync(base + suffix) && fs.statSync(base + suffix).isFile()) {
                return { path: base + suffix };
              }
            }
            return { path: base };
          });
        },
      },
    ],
  });

  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "http://localhost/",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  // 这几个名字在 Node 里已经有一份(undici 的 Event、global EventTarget 等),
  // 但它们和 jsdom 的元素不是同一个 realm,必须换成 jsdom 的,否则 dispatchEvent 会拒收。
  for (const key of [
    "Event",
    "CustomEvent",
    "KeyboardEvent",
    "MouseEvent",
    "PointerEvent",
    "FocusEvent",
    "InputEvent",
    "CompositionEvent",
    "UIEvent",
    "EventTarget",
    "Node",
    "Element",
    "HTMLElement",
    "HTMLInputElement",
    "HTMLFormElement",
    "HTMLButtonElement",
    "DocumentFragment",
    "DOMRect",
    "SVGElement",
    "MutationObserver",
    "NodeFilter",
    "Range",
    "Selection",
    "AbortController",
    "AbortSignal",
    "getComputedStyle",
    "requestAnimationFrame",
    "cancelAnimationFrame",
  ]) {
    if (window[key] !== undefined) {
      Object.defineProperty(globalThis, key, { value: window[key], configurable: true, writable: true });
    }
  }
  for (const key of Object.getOwnPropertyNames(window)) {
    if (["window", "document", "navigator", "globalThis", "self"].includes(key)) continue;
    if (key in globalThis) continue;
    try {
      const value = window[key];
      if (typeof value === "function" || (value && typeof value === "object")) {
        Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
      }
    } catch {
      // 有些 getter 只读,跳过即可;真正要用的那几个在下面单独挂。
    }
  }
  globalThis.window = window;
  globalThis.document = window.document;
  globalThis.self = window;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  globalThis.ResizeObserver = window.ResizeObserver;
  window.Element.prototype.scrollIntoView = function scrollIntoView() {};
  window.Element.prototype.hasPointerCapture = () => false;
  window.Element.prototype.setPointerCapture = function setPointerCapture() {};
  window.Element.prototype.releasePointerCapture = function releasePointerCapture() {};
  window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });

  const mod = await import(`${pathToFileURL(bundle).href}?v=${Date.now()}`);
  return {
    window,
    React: mod.React,
    Demo: mod.Demo,
    render: mod.render,
    screen: mod.screen,
    userEvent: mod.userEvent,
    close() {
      window.close();
      fs.rmSync(tmp, { recursive: true, force: true });
    },
  };
}
