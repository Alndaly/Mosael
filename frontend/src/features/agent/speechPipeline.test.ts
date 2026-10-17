/**
 * 对话类的「按句流水线」:第一句合成完就播,播的同时合成下一句。
 *
 * 这些用例钉的是**顺序和时序**,不是文案:
 * ① 第一句的音频在第二句合成完成之前就开始播;
 * ② 播到一半取消 → 后续句子不再合成、不再播;
 * ③ 第 N 句失败要说清,前面已经播的照常结束(不能静默变成念了一半);
 * ④ 「等整段」与「先出声」两种取值都生效。
 */

import { describe, expect, it, vi } from "vitest";

import { PARAGRAPH_GAP_MS, splitSpeech } from "@/lib/speechText";
import { speakText, type SpeakTextOptions } from "@/features/agent/speechPipeline";

function texts(text: string): string[] {
  return splitSpeech(text).map((chunk) => chunk.text);
}

/** Blob 没有 name 字段;测试里用 Object.defineProperty 标一下,好认出播的是哪一句。 */
function named(name: string): Blob {
  const blob = new Blob([name]);
  Object.defineProperty(blob, "name", { value: name });
  return blob;
}

function nameOf(blob: Blob): string {
  return (blob as Blob & { name?: string }).name ?? "";
}

function gate<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

/** 让已经排队的微任务全部落定,但不推进受控 promise。 */
async function settle(): Promise<void> {
  for (let round = 0; round < 12; round += 1) await Promise.resolve();
}

const REPLY = "这是第一句。这是第二句。这是第三句。";

describe("按句切分", () => {
  it("按句末标点切,引号里那句算一句", () => {
    expect(texts("第一句。第二句！第三句？")).toEqual(["第一句。", "第二句！", "第三句？"]);
    //: 引号里的句号不切;收引号跟着前一句走。
    expect(texts("他说：“你好。世界。”然后走了。")).toEqual(["他说：“你好。世界。”", "然后走了。"]);
    expect(texts('He said, "Really? I doubt it." Then left.')).toEqual([
      'He said, "Really? I doubt it."',
      "Then left.",
    ]);
  });

  it("省略号不切", () => {
    expect(texts("等等...然后呢？")).toEqual(["等等...然后呢？"]);
    expect(texts("等等……好吧。")).toEqual(["等等……好吧。"]);
  });

  it("URL、小数、版本号里的点不切", () => {
    expect(texts("看这个 https://example.com/a.b?x=1. 然后再说。")).toEqual([
      "看这个 https://example.com/a.b?x=1.",
      "然后再说。",
    ]);
    expect(texts("版本是 1.2.3，没问题。")).toEqual(["版本是 1.2.3，没问题。"]);
    expect(texts("Mr. Smith went home. Then he slept.")).toEqual(["Mr. Smith went home.", "Then he slept."]);
  });

  it("行内代码里不切", () => {
    expect(texts("看 `a.b` 这段。再说。")).toEqual(["看 `a.b` 这段。", "再说。"]);
  });

  it("代码块里不切", () => {
    const chunks = texts("先看代码：\n```ts\nconst a = 1.5;\nconsole.log(a);\n```\n完成。");
    expect(chunks).toEqual(["先看代码：", "```ts\nconst a = 1.5;\nconsole.log(a);\n```", "完成。"]);
  });

  it("段落之间留一段自然间隙", () => {
    const chunks = splitSpeech("第一段。\n\n第二段。");
    expect(chunks.map((chunk) => chunk.text)).toEqual(["第一段。", "第二段。"]);
    expect(chunks[0].gapAfterMs).toBe(PARAGRAPH_GAP_MS);
    expect(chunks[1].gapAfterMs).toBe(0);
  });

  it("空白不念", () => {
    expect(splitSpeech("  \n ")).toEqual([]);
  });
});

describe("按句流水线", () => {
  it("① 第一句在第二句合成完成之前就开始播", async () => {
    const gates = [gate<Blob>(), gate<Blob>(), gate<Blob>()];
    const calls: string[] = [];
    const played: string[] = [];
    const options: SpeakTextOptions = {
      text: REPLY,
      synthesize: (text) => {
        calls.push(text);
        return gates[calls.length - 1].promise;
      },
      play: async (blob) => {
        played.push(nameOf(blob));
      },
    };

    const running = speakText(options);
    await settle();
    //: 一次只先取一句;第二句在第一句开始播之后才去取。
    expect(calls).toEqual(["这是第一句。"]);

    gates[0].resolve(named("s1"));
    await settle();
    expect(played).toEqual(["s1"]);
    expect(calls).toEqual(["这是第一句。", "这是第二句。"]);
    //: 第二句还挂着 —— 第一句却已经在播了。
    expect(gates[1].promise).toBeInstanceOf(Promise);

    gates[1].resolve(named("s2"));
    await settle();
    expect(calls).toEqual(["这是第一句。", "这是第二句。", "这是第三句。"]);
    expect(played).toEqual(["s1", "s2"]);

    gates[2].resolve(named("s3"));
    await expect(running).resolves.toBe("done");
    expect(played).toEqual(["s1", "s2", "s3"]);
  });

  it("② 播到一半取消:在途的合成作废,后续不再合成也不再播", async () => {
    const gates = [gate<Blob>(), gate<Blob>(), gate<Blob>()];
    const calls: string[] = [];
    const played: string[] = [];
    const playback = gate<void>();
    let cancelled = false;

    const running = speakText({
      text: REPLY,
      synthesize: (text) => {
        calls.push(text);
        return gates[calls.length - 1].promise;
      },
      play: async (blob) => {
        played.push(nameOf(blob));
        await playback.promise;
      },
      cancelled: () => cancelled,
    });

    gates[0].resolve(named("s1"));
    await settle();
    //: 第一句在播,第二句已经在途中 —— 这正是打断要作废的那一个。
    expect(played).toEqual(["s1"]);
    expect(calls).toEqual(["这是第一句。", "这是第二句。"]);

    cancelled = true;
    playback.resolve();
    gates[1].resolve(named("s2"));
    await expect(running).resolves.toBe("cancelled");

    expect(played).toEqual(["s1"]);
    expect(calls).toEqual(["这是第一句。", "这是第二句。"]);
    expect(calls).not.toContain("这是第三句。");
  });

  it("③ 第二句合成失败:报出来,第一句已经正常播完", async () => {
    const gates = [gate<Blob>(), gate<Blob>(), gate<Blob>()];
    const events: string[] = [];
    const failure = vi.fn();

    const running = speakText({
      text: REPLY,
      synthesize: (text) => {
        events.push(`synth:${text}`);
        return gates[(events.filter((one) => one.startsWith("synth:")).length - 1)].promise;
      },
      play: async (blob) => {
        events.push(`play:${nameOf(blob)}`);
      },
      onFailure: (error) => {
        events.push("fail");
        failure(error);
      },
    });

    gates[0].resolve(named("s1"));
    await settle();
    const boom = new Error("第二句合成失败");
    gates[1].reject(boom);

    await expect(running).resolves.toBe("failed");
    expect(failure).toHaveBeenCalledWith(boom);
    //: 下一句的合成和这一句的播放同时在跑;失败是在这一句**播完之后**才报的。
    expect(events).toEqual(["synth:这是第一句。", "synth:这是第二句。", "play:s1", "fail"]);
  });

  it("③ 播放失败也要报,不是静默停下", async () => {
    const failure = vi.fn();
    const played: string[] = [];
    const running = speakText({
      text: "第一句要长一点。第二句也要长一点。",
      synthesize: async (text) => named(text),
      play: async (blob) => {
        played.push(nameOf(blob));
        throw new Error("播放器坏了");
      },
      onFailure: failure,
    });

    await expect(running).resolves.toBe("failed");
    expect(failure).toHaveBeenCalledOnce();
    expect(played).toEqual(["第一句要长一点。"]);
  });

  it("④ 「等整段」只取一次,行为和今天一致", async () => {
    const calls: string[] = [];
    const played: string[] = [];
    await expect(
      speakText({
        text: REPLY,
        whole: true,
        synthesize: async (text) => {
          calls.push(text);
          return named("all");
        },
        play: async (blob) => {
          played.push(nameOf(blob));
        },
      }),
    ).resolves.toBe("done");
    expect(calls).toEqual([REPLY]);
    expect(played).toEqual(["all"]);
  });

  it("④ 单句 / 很短的话也一次取完 —— 同一份输出,只是不走队列", async () => {
    for (const text of ["就这一句。", "好。走。"]) {
      const calls: string[] = [];
      await speakText({
        text,
        synthesize: async (one) => {
          calls.push(one);
          return new Blob([one]);
        },
        play: async () => undefined,
      });
      expect(calls).toEqual([text]);
    }
  });
});
