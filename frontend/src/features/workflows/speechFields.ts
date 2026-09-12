/**
 * 语音合成节点上,音色那一格该显示哪一个。
 *
 * 它有两条互斥的路:克隆音色(配音库里那把嗓子,存在 `voice_id`)和引擎音色(现成的嗓子,
 * 存在 `engine` + `engine_voice`)。**第一版把它们摊成了并排字段** —— 音色、引擎、引擎音色
 * 三格,两格名字里都带"音色",各自还写着"用另一个时留空"。用户一眼就说"重复了",而这种
 * 表单的典型结果是两个都填或者两个都空。
 *
 * 现在是一对「引擎 + 音色」:先选嗓子从哪来,音色那一格再按它列对应清单。存储上仍是两个键
 * (后端的两条路本来就要不同参数),但界面上**从不同时出现**。
 *
 * 抽成纯函数是因为它是一条规则,不是渲染:摆在 NodeInspector 那八百行里的话,它既读不出来
 * 也测不到。
 */

/** 留空视作克隆 —— 和执行体一致(见 executors/subjobs.synthesize_speech)。
 *  已经存下来的工作流里只有 voice_id,不能因为加了一条路就把它们显示成"选了引擎"。 */
export function speechUsesClonedVoice(engine: unknown): boolean {
  return (String(engine ?? "").trim() || "clone") === "clone";
}

/** 收同一对「引擎 + 音色」的节点。字幕配音和语音合成念的是同一套嗓子,表单也就该是同一个样子
 *  —— 按节点类型集合判而不是写死一个名字,是因为这条规则属于那对字段,不属于某一个节点。 */
const SPEECH_NODE_TYPES = new Set(["synthesize_speech", "dub_subtitles"]);

/** 这个节点收不收音色。音色清单、引擎清单、选中音色顺带填资源号——那几件事都跟着它走。 */
export function nodePicksVoice(nodeType: string): boolean {
  return SPEECH_NODE_TYPES.has(nodeType);
}

/** 这一格现在该不该出现在表单里。不收音色的节点,字段一律照旧。 */
export function speechFieldVisible(nodeType: string, key: string, engine: unknown): boolean {
  if (!SPEECH_NODE_TYPES.has(nodeType)) return true;
  const clone = speechUsesClonedVoice(engine);
  if (key === "voice_id") return clone;
  if (key === "engine_voice" || key === "engine_voice_resource") return !clone;
  return true;
}
