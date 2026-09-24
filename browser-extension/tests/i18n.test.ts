import { describe, expect, it } from "vitest";

import { localeFromLanguage, localizeMessage, messages, translate } from "../src/i18n";
import { localizedError } from "../src/shared/localized-error";

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

  it("translates errors raised in page scripts in the side panel's language", () => {
    const error = localizedError("captionServiceHttpError", { status: 403 });
    expect(localizeMessage("en", error.message)).toBe("Caption service request failed (403)");
    expect(localizeMessage("zh-CN", error.message)).toBe("字幕服务请求失败（403）");
    expect(localizeMessage("en", localizedError("videoHasNoCaptions").message)).toBe("This video has no captions");
  });

  it("passes other error text through unchanged", () => {
    expect(localizeMessage("en", "Workspace not found")).toBe("Workspace not found");
    expect(localizeMessage("en", "i18n:notARealKey")).toBe("i18n:notARealKey");
  });
});
