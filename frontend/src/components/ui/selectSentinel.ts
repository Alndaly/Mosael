/**
 * 「不选」在下拉里也得是一个**有值的**选项。
 *
 * radix 的 `Select` 把空字符串当成「还没选」的哨兵:`<SelectItem value="">` 选中之后,
 * `SelectValue` 认为无值可显示,于是触发器一片空白 —— 用户明明点了「不用」,看到的却是没选。
 *
 * 所以「不用 / 自动」这类语义要有自己的字面值,只在**送出去的那一刻**翻译回 `null`。
 * 这个坑在这个仓库里一次写出了两处(配音的权重、从链接导入的登录身份),所以收成一份,
 * 并由 `selectSentinel.test.ts` 盯着不再有 `SelectItem value=""`。
 */
export const NONE = "__none__";

/** 下拉的值 → 送给后端的值。哨兵变 null,其余原样。 */
export function optionalValue(value: string): string | null {
  return value === NONE || value === "" ? null : value;
}
