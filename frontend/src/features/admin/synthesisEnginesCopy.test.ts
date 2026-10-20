import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";

/**
 * 管理 → 引擎里的那一节,范围是**可下载的语音合成引擎权重**,不是"声音克隆"。
 *
 * 它装着三种引擎:克隆引擎(F5-TTS / Fish Speech)和预置音色引擎(Qwen3-TTS)。标题、说明、
 * 下拉此前全是克隆专属,于是 Qwen3-TTS 被读成"克隆引擎",和它自己那句「不克隆、不要参考音频」
 * 当场矛盾 —— 用户装好它,回到这一节只在「引擎」下拉里看见 F5/Fish,结论是"装了却选不到它"。
 *
 * 这里钉住文案层面的两件事:标题与说明覆盖两种能力,以及那个下拉自己承认只管克隆。
 * 分组渲染在 VoiceCloneSection.groups.dom.test.tsx 里钉。
 */
describe("「声音克隆」这一节的标题与说明改成覆盖两种能力", () => {
  it("中文标题是「语音合成引擎」,不再说成克隆专属", () => {
    expect(messages["zh-CN"].voiceCloneTitle).toBe("语音合成引擎");
  });

  it("英文标题同样讲合成,不再只说克隆", () => {
    const title = messages["en-US"].voiceCloneTitle;
    expect(title).toBe("Speech synthesis engines");
    expect(title.toLowerCase()).not.toContain("cloning");
  });

  it("中文说明:两类引擎都讲,并说清权重都在这里下载、装好去哪选", () => {
    const desc = messages["zh-CN"].voiceCloneDesc;
    // 两类能力都得点名 —— 只写"TTS 引擎"等于没说清 Qwen 为什么在这里。
    expect(desc).toContain("克隆引擎");
    expect(desc).toContain("预置音色");
    // 权重都在这一节下。
    expect(desc).toContain("下载");
    // 真正的切换入口:剪辑台的「配音」、创作页的「语音」(两处都存在,见 VoicePanel / createKindSpeech)。
    expect(desc).toContain("配音");
    expect(desc).toContain("语音");
  });

  it("英文说明同义,不能只改中文", () => {
    const desc = messages["en-US"].voiceCloneDesc;
    expect(desc.toLowerCase()).toContain("clone engines");
    expect(desc.toLowerCase()).toContain("preset-voice");
    expect(desc.toLowerCase()).toContain("download");
    expect(desc).toContain("Dubbing");
    expect(desc).toContain("Speech");
  });

  it("下拉的名字自己就说明只管克隆 —— 叫「引擎」会让人以为所有引擎都在这儿切", () => {
    expect(messages["zh-CN"].voiceCloneEngine).toBe("默认克隆引擎");
    expect(messages["en-US"].voiceCloneEngine).toBe("Default clone engine");
  });

  it("两组的组头与说明中英都有", () => {
    for (const locale of ["zh-CN", "en-US"] as const) {
      expect(messages[locale].voiceCloneGroupClones.length).toBeGreaterThan(0);
      expect(messages[locale].voiceCloneGroupClonesDesc.length).toBeGreaterThan(0);
      expect(messages[locale].voiceCloneGroupPreset.length).toBeGreaterThan(0);
      expect(messages[locale].voiceCloneGroupPresetDesc.length).toBeGreaterThan(0);
      expect(messages[locale].voiceClonePickElsewhere.length).toBeGreaterThan(0);
    }
    expect(messages["zh-CN"].voiceCloneGroupClones).toBe("克隆引擎");
    expect(messages["zh-CN"].voiceCloneGroupPreset).toBe("预置音色引擎");
    expect(messages["en-US"].voiceCloneGroupClones).toBe("Clone engines");
    expect(messages["en-US"].voiceCloneGroupPreset).toBe("Preset-voice engines");
  });
});
