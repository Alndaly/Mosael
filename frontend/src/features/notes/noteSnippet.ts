/**
 * 笔记正文的一行摘要:去掉 Markdown 记号,只留读得懂的字。笔记列表和「选择笔记」弹窗共用。
 *
 * 此前挑笔记的弹窗直接截正文前 200 个字符,于是一行里是「```shell echo a ``` ![](https://…png) | da | das |」——
 * 代码块的围栏、图片地址、表格竖线全露出来,真正写的字反而被挤到省略号后面。
 */
export function noteSnippet(markdown: string, max = 120): string {
  const text = markdown
    // 图片整个去掉(地址对挑笔记的人没意义),链接留文字。
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    // 代码块的围栏和语言名去掉,里面的字留着。
    .replace(/```[\w+-]*/g, " ")
    // 表格:分隔行整行去掉,竖线换成空格。
    .replace(/^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{0,}:?\s*$/gm, " ")
    .replace(/\|/g, " ")
    // 行首的标题、引用、列表记号。
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/[*_~`#>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > max ? `${text.slice(0, max)}…` : text;
}
