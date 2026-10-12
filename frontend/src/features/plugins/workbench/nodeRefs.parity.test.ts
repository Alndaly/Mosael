/**
 * 节点形状契约的**前端一侧**:跑 `contracts/node-shapes.json` 的 `canvas_path`。
 *
 * 助手回复里的 `#12` / `#12:5` 指的必须和后端 `comfy_locate`、插件的 `canvas_edit` 认的是**同一个位置**:
 * 一串形状对不上的引用不会报错 —— 它只是**没变成链接**(点了没反应),或者更糟:变成了链接而画布上
 * 定位不到。而这条链上的正则有三份(前端 `NODE_REF`、宿主 `workbench_agent._NODE_REF`、插件
 * `canvas_edit._PATH`),各自手写。
 *
 * 所以这里**不重抄一遍用例**:`12` / `-3` / `12:5` / 16 段 / 17 段这些边界从契约里读,逐条喂给真函数
 * (`linkNodeRefs`)。宿主那两条 parity(`backend/tests/test_node_shapes_parity.py`)读的是同一份文件
 * —— 改判据只改一处时,两侧同时红。
 *
 * 这一份也**不重写一遍「什么算引用」**:`#12` 只在正文里换,围栏代码块、行内代码、网址、HTML 实体、
 * 连着单词的一律不动 —— 那是 `nodeRefs.ts` 自己的事,由 `nodeRefs.test.ts` 钉着。这里量的是形状。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../../contracts/node-shapes.json";
import { MARKDOWN_REF } from "@/components/markdown/markdownRefs";
import { NODE_REF, linkNodeRefs } from "./nodeRefs";

const shape = (() => {
  const found = contract.shapes.find((one) => one.name === "canvas_path");
  if (!found) throw new Error("契约里没有 canvas_path —— 它被删了还是改名了?");
  return found;
})();

/** 契约那一串自己编的正则(**锚定**的)—— 和前端 `NODE_REF` 比「能不能收下同一批串」。 */
const oracle = new RegExp(`^(?:${shape.pattern})$`);

const link = (ref: string) => `[#${ref}](${MARKDOWN_REF}${ref})`;

describe("节点形状契约的前端一侧(canvas_path)", () => {
  it("契约记的那一串就是 NODE_REF 里嵌着的那一串", () => {
    //: `NODE_REF` 外面还套了 `#` 前缀和「别把代码块 / 网址 / 连着单词的算进来」那几层,
    //: 所以它不会整条相等 —— 断言的是「契约那一截原样在里面」(`source` 里就是带反斜杠的写法)。
    expect(NODE_REF.source).toContain(shape.pattern);
  });

  it("收下的每一条都真的变成定位链接", () => {
    for (const one of shape.cases.ok) {
      expect(oracle.test(one), `契约用例 ${one} 自己该收`).toBe(true);
      expect(linkNodeRefs(`看 #${one} 这一格`), `#${one} 该变成一个定位链接`).toBe(`看 ${link(one)} 这一格`);
    }
  });

  it("拒的每一条都不链出来(而契约自己也拒)", () => {
    for (const one of shape.cases.bad) {
      expect(oracle.test(one), `契约用例 ${one} 自己该拒`).toBe(false);
      if (one === "") continue; //: 空串在正文里没有意义(连 `#` 都没有),`linkNodeRefs` 对它什么都不做
      //: 判据不是「整行不变」:`#12:` 这种会按**能认的那一截**链 —— 因为 `12` 本身就是一条合法的引用。
      //: 这里量的是「不会把整条 `bad` 串当成一个引用链出来」。
      expect(linkNodeRefs(`#${one}`), `${one} 不该整条变成一个链接`).not.toBe(link(one));
    }
  });

  it("还认负号、`#` 后面跟冒号说明、紧挨着括号 —— 那些是正文里的写法,不是形状", () => {
    expect(linkNodeRefs("见 (#-2) 和 #7:1:2")).toBe(`见 (${link("-2")}) 和 ${link("7:1:2")}`);
    expect(linkNodeRefs("#4: KSampler"), "后面跟冒号说明的也认").toBe(`${link("4")}: KSampler`);
  });

  it("契约 divergence 记的那处差异:往里走的每一段不带负号", () => {
    //: `-3:-5` 在契约的 `bad` 里 —— 负号只属于画布上那一层(子图输入口是 `-10`),
    //: 而往里走的每一段是子图定义里的节点号,那些是正的。前端这一侧不能把它整条链起来。
    expect(shape.cases.bad).toContain("-3:-5");
    expect(linkNodeRefs("#-3:-5")).not.toContain(link("-3:-5"));
  });

  it("17 段那条:契约说拒,前端也不链(深度上限两侧相同)", () => {
    const tooDeep = "1:2:3:4:5:6:7:8:9:10:11:12:13:14:15:16:17:18:19:20";
    expect(shape.cases.bad).toContain(tooDeep);
    expect(linkNodeRefs(`#${tooDeep}`)).toBe(`#${tooDeep}`);
  });
});
