/**
 * 生成节点的输入素材,在配置里存成**每行一条 `素材id` 或 `素材id:角色`** 的文本。
 *
 * 存成文本是有道理的:工作流里这一格常常不是一个固定的素材,而是上游节点的输出
 * (`{{ai-generate-1.asset_id}}`)—— 那种东西只有模板串装得下,下拉装不下。
 *
 * 但**让用户直接写这段文本不行**。角色名要背(first_frame 还是 firstFrame?),冒号要记,
 * 写错了不报错 —— 后端拿不到角色就按默认走,于是"我明明挂了尾帧"的片子里没有尾帧。
 *
 * 所以界面按角色一行一格,这里只管两边的翻译。往返要**稳**:解析再序列化必须回到原样,
 * 否则每打开一次检查器,配置就被悄悄改一次,而 diff 里全是噪音。
 */

/** 一条素材:值(素材 id 或模板串)+ 它的用途。 */
export interface SourceAssetLine {
  value: string;
  role: string;
}

/**
 * 把文本解析成一条条素材。
 *
 * 不写角色的行**保留空角色**,而不是替它猜一个 —— 后端有自己的默认(图生视频按首帧、
 * 图生图按参考图),在这里猜等于把那条默认抄第二遍,而两份默认迟早会不一致。
 */
export function parseSourceAssets(text: string): SourceAssetLine[] {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      // 模板串里可能带冒号(`{{a.b:c}}` 少见但合法),所以从**右边**找分隔符,
      // 而且只认后半段是纯角色名的那一种。
      const at = line.lastIndexOf(":");
      if (at <= 0) return { value: line, role: "" };
      const role = line.slice(at + 1).trim();
      return /^[a-z_]+$/.test(role) ? { value: line.slice(0, at).trim(), role } : { value: line, role: "" };
    });
}

/** 反过来。空值的行直接丢掉 —— 一个只有角色没有素材的条目对后端毫无意义。 */
export function serializeSourceAssets(lines: SourceAssetLine[]): string {
  return lines
    .filter((line) => line.value.trim())
    .map((line) => (line.role ? `${line.value.trim()}:${line.role}` : line.value.trim()))
    .join("\n");
}

/** 取某个角色现在填的值(没有就是空串)—— 界面上一格对一个角色。 */
export function valueForRole(lines: SourceAssetLine[], role: string): string {
  return lines.find((line) => line.role === role)?.value ?? "";
}

/**
 * 改某个角色的值,其余原样保留。
 *
 * **保留顺序**:角色相同的那条就地替换,不是删了再追加到末尾 —— 那样每改一次,行的顺序就
 * 变一次,配置的 diff 里全是搬家。
 */
export function withRole(lines: SourceAssetLine[], role: string, value: string): SourceAssetLine[] {
  const trimmed = value.trim();
  const existing = lines.findIndex((line) => line.role === role);
  if (existing >= 0) {
    if (!trimmed) return lines.filter((_, index) => index !== existing);
    return lines.map((line, index) => (index === existing ? { ...line, value: trimmed } : line));
  }
  return trimmed ? [...lines, { value: trimmed, role }] : lines;
}

/** 不属于任何已知角色的行 —— 手写过的、或模型换了之后角色不再被支持的。 */
export function extraLines(lines: SourceAssetLine[], knownRoles: readonly string[]): SourceAssetLine[] {
  return lines.filter((line) => !line.role || !knownRoles.includes(line.role));
}
