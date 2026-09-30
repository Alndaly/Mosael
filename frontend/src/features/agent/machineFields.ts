/**
 * 只有机器需要的字段。它们在摘要里毫无意义,在展开的明细里也只是噪音。
 *
 * 折叠行此前显示的是 `browser_open fd8620bd80ec4c88a03d73b8b17b7f6b` —— 那是 workspace_id,
 * 因为老的取法是「对象里第一个字符串值」,而参数里第一个往往就是它。一串 32 位十六进制
 * 占满整行,而真正说明这一步在干什么的 url 被挤掉了。
 *
 * 工具调用行(ToolCalls)和确认卡的参数列表(confirmationPayload)共用这一份。
 */
export const NOISE_KEYS = new Set([
  "workspace_id",
  "project_id",
  "session_id",
  "confirmation_id",
  "requested_by",
  "instance_id",
]);
