/**
 * 这几条字幕,这个引擎念得了吗 —— 在**点下去之前**回答。
 *
 * 后端会拦住确知念不了的组合(见 audio/tts_language),但那是在任务排队之后:用户点了「配音」、
 * 等一下、收到一条错误。而这个判断在选引擎的那一刻就能做出来 —— 文本就在眼前。
 *
 * 判据与后端同一套:**只认书写系统**。假名只出现在日文里、谚文只出现在韩文里,这是硬证据;
 * 汉字中日共用、拉丁字母几十种语言共用,证明不了任何事,所以不据此提示。
 */

/** 平假名 + 片假名。 */
const KANA = /[぀-ヿ]/g;
/** 谚文。 */
const HANGUL = /[가-힯ᄀ-ᇿ]/g;
/** 计入分母的「实字」:去掉空白、数字、标点。 */
const MEANINGFUL = /[^\s\d\p{P}\p{S}_]/gu;

const MIN_SHARE = 0.1;
const MIN_COUNT = 2;

export type DubScript = "ja" | "ko" | "";

/** 能确证的书写系统;证明不了就是空串(**不代表是中文**,只代表没有硬证据)。 */
export function detectScript(text: string): DubScript {
  const total = (text.match(MEANINGFUL) ?? []).length;
  if (total === 0) return "";
  for (const [script, pattern] of [["ja", KANA], ["ko", HANGUL]] as const) {
    const hits = (text.match(pattern) ?? []).length;
    if (hits >= MIN_COUNT && hits / total >= MIN_SHARE) return script;
  }
  return "";
}

/** Edge 音色 id 自带 locale(`ja-JP-NanamiNeural`);其余引擎看 `zh_female_…` 那种前缀。 */
const VOICE_ID_LANGS = new Set(["zh", "en", "ja", "ko", "es", "fr", "de", "ru", "pt", "it", "ar", "hi", "th", "vi", "id"]);

export function voiceLanguage(engine: string, voice: string): string {
  if (!voice) return "";
  if (engine === "edge") {
    const head = voice.split("-", 1)[0]?.toLowerCase() ?? "";
    return head.length === 2 ? head : "";
  }
  const prefix = /^([a-z]{2})_/.exec(voice)?.[1] ?? "";
  // 白名单,不是「任意两个字母」—— 否则 `my_custom_voice` 里的 `my_` 会被当成语言代码。
  return VOICE_ID_LANGS.has(prefix) ? prefix : "";
}

/**
 * 这组选择念不了这段文本吗 —— 返回念不了的那个语言,能念(或拿不准)就返回空串。
 *
 * **拿不准一律当能念**:多语言引擎、账号里的自定义音色都属于这一类。提示是帮忙,不是设卡,
 * 而一条错误的警告会让用户开始怀疑所有警告。
 */
export function unspeakable(
  texts: string[],
  engine: string,
  voice: string,
  /** 本地克隆**现在**念得了的书写系统 —— 由这台机器上装了哪几份权重决定(见 /api/tts/f5-models)。 */
  cloneLanguages: readonly string[] = [],
): DubScript {
  const script = detectScript(texts.join("\n"));
  if (!script) return "";
  // 克隆引擎不是「只认中英」—— 那是**权重**的属性,而权重可以再下一份。写死在这里的话,
  // 用户下完日语模型仍然会被告知念不了(后端已经改成按权重判,前端一度还写着死的)。
  if (engine === "clone") return cloneLanguages.includes(script) ? "" : script;
  const language = voiceLanguage(engine, voice);
  return language && language !== script ? script : "";
}


/** 这条字幕真正要念出来的那部分 —— 与后端 audio/subtitle_dub.dub_text 同一套规则。 */
export function dubTextOf(clip: { text_override?: string | null }, line: "all" | "first" | "last"): string {
  const lines = (clip.text_override ?? "").split("\n").map((part) => part.trim()).filter(Boolean);
  if (lines.length === 0) return "";
  if (line === "first") return lines[0];
  if (line === "last") return lines[lines.length - 1];
  return lines.join("\n");
}


/**
 * 从这个引擎的音色里挑一个**念得了这段文本**的。挑不出来返回空串。
 *
 * 有它才不必让用户自己去对:选了 Edge、字幕是日文,就该直接落在日语音色上,而不是先落在
 * 「晓晓」上、再弹一条警告让他猜要改什么(用户就是这么被绕进去的)。
 */
export function pickVoiceFor(
  script: DubScript,
  engine: string,
  choices: readonly { value: string }[],
): string {
  if (!script) return "";
  return choices.find((item) => voiceLanguage(engine, item.value) === script)?.value ?? "";
}

/** 这个引擎的音色里,有没有念得了这段文本的 —— 决定提示该说「换音色」还是「换引擎」。 */
export function hasVoiceFor(script: DubScript, engine: string, choices: readonly { value: string }[]): boolean {
  return Boolean(pickVoiceFor(script, engine, choices));
}
