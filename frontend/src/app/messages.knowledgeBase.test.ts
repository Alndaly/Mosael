/**
 * 知识库已经删掉了,文案里不该还留着它。
 *
 * 用户在全局搜索框里看到「搜索页面、项目、素材、**知识库**…」—— 而那个东西整个不存在了:
 * 后端没有 dataset 节点、没有 dataset_id 字段,连 embedding 能力都没有任何消费者
 * (`domain/provider_defaults` 的注释就写着「知识库删掉之后 embedding 没有任何消费者」)。
 *
 * 最糟的三条不是搜索框那句,是这几句 **在教用户去做一件做不到的事**:
 *
 *   - 「资料和成稿请放知识库」
 *   - 「更长的内容请存进知识库」
 *   - 「超过 200KB 的文本请先放进知识库」
 *
 * 照着做的人会去找那个入口,找不到,然后怀疑是自己没找到。**一句写下来却兑现不了的话,
 * 比不写更糟** —— 这一整轮反复出现的就是这个形状。
 *
 * 删功能时把它的话一起删掉;这条测试负责在下一次漏掉时喊一声。
 */
import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";

const GONE = ["知识库", "knowledge base", "Knowledge base", "KB notes"];

describe("已删掉的功能不该在文案里活着", () => {
  it("没有一条文案还在提知识库", () => {
    const offenders: string[] = [];
    for (const [locale, table] of Object.entries(messages)) {
      for (const [key, value] of Object.entries(table as Record<string, unknown>)) {
        if (typeof value !== "string") continue;
        for (const gone of GONE) {
          if (value.includes(gone)) offenders.push(`${locale}.${key}: ${value.slice(0, 60)}`);
        }
      }
    }

    expect(offenders, "这些文案还在说一个已经不存在的东西:\n  " + offenders.join("\n  ")).toEqual([]);
  });
});
