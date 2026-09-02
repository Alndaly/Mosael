import { describe, expect, it } from "vitest";

import { localeFromLanguage, messages, translate } from "../src/i18n";

describe("extension i18n", () => {
  it("maps browser language variants to a supported UI locale", () => {
    expect(localeFromLanguage("zh-CN")).toBe("zh-CN");
    expect(localeFromLanguage("zh-TW")).toBe("zh-CN");
    expect(localeFromLanguage("en-US")).toBe("en");
    expect(localeFromLanguage("fr-FR")).toBe("en");
  });

  it("keeps every locale on the same typed message contract", () => {
    expect(Object.keys(messages.en).sort()).toEqual(Object.keys(messages["zh-CN"]).sort());
    expect(translate("en", "generateTranscript")).toBe("Generate with Mosael");
    expect(translate("zh-CN", "generateTranscript")).toBe("使用 Mosael 生成逐字稿");
  });
});
