/**
 * 表单输入的几条规则:手机号收成 E.164、登录后跳回哪儿、handle 与密码的格式。
 *
 * 规则的**权威在社区服务**(它会拒绝不合格的输入并给出译好的错误);这里只挡住明显填错的,
 * 让人在点「发送验证码」之前就知道,而不是等一条短信的额度被浪费掉。
 */

/**
 * 手机号 → E.164。国内用户不会自己打 `+86`:11 位、以 1 开头的就当中国大陆号码;带 `+` 的
 * 原样收(去掉空格和横线)。认不出来返回 null。
 */
export function toE164(input: string): string | null {
  const compact = input.replace(/[\s\-()]/g, "");
  if (/^\+[1-9]\d{6,14}$/.test(compact)) return compact;
  if (/^(?:0086|86)?1[3-9]\d{9}$/.test(compact)) return `+86${compact.slice(-11)}`;
  return null;
}

/** handle:3–24 位,小写字母、数字、下划线、短横,字母开头。和作者主页的 URL 一段对得上。 */
export function validHandle(handle: string): boolean {
  return /^[a-z][a-z0-9_-]{2,23}$/.test(handle);
}

/** 密码至少 8 位。更细的强度规则由服务定。 */
export const MIN_PASSWORD = 8;

export function validPassword(password: string): boolean {
  return password.length >= MIN_PASSWORD && password.length <= 128;
}

/** 六位数字验证码。 */
export function validCode(code: string): boolean {
  return /^\d{6}$/.test(code.trim());
}

/**
 * 登录之后跳回哪儿。`?next=` 是外面给的 —— 只收**本站同语言下的相对路径**,不收
 * `//evil.com`、`/\evil.com`、`https://…`,免得登录页成了一个开放跳转。
 */
export function safeNext(next: string | null | undefined, locale: string): string {
  const fallback = `/${locale}/account`;
  if (!next || !next.startsWith(`/${locale}/`)) return fallback;
  if (/^\/[/\\]/.test(next) || next.includes("\\") || [...next].some((char) => char.charCodeAt(0) < 0x20)) return fallback;
  try {
    const url = new URL(next, "https://mosael.invalid");
    if (url.origin !== "https://mosael.invalid") return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}

/** 设备授权的 user_code:`ABCD-EFGH`,大小写、空格、少了横线都收。 */
export function normalizeUserCode(input: string): string {
  const letters = input.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return letters.length > 4 ? `${letters.slice(0, 4)}-${letters.slice(4)}` : letters;
}

/** 逗号、顿号、空格分开的标签,去重、去空,最多 8 个,各不超过 24 字。 */
export function parseTags(input: string): string[] {
  const seen = new Set<string>();
  for (const raw of input.split(/[,，、\s]+/)) {
    const tag = raw.trim().replace(/^#/, "").slice(0, 24);
    if (tag) seen.add(tag.toLowerCase());
  }
  return [...seen].slice(0, 8);
}
