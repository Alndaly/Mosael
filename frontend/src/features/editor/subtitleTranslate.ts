/**
 * 字幕翻译时「送去翻哪部分、译文怎么落回去」。
 *
 * 双语字幕在这个应用里是一条 `原文\n译文`(勾了「保留原文」翻出来的就是这个形状,导出时拆成两行)。
 * 此前再翻一次是把整条(原文 + 旧译文)送去翻、再在前面拼上整条:`原文\n旧译文\n新译文`,
 * 每翻一次多一行。规则:**只翻第一行(原文),译文替换第二行**。
 */

function lines(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean);
}

/** 送去翻的文字:多行时只取第一行(原文)。 */
export function translationSource(text: string): string {
  return lines(text)[0] ?? "";
}

/** 译文落回字幕:保留原文时是「原文\n译文」(原来的第二行被替换),否则就是译文。 */
export function translatedCue(text: string, translated: string, bilingual: boolean): string {
  const original = translationSource(text);
  return bilingual ? `${original}\n${translated.trim()}` : translated.trim();
}
