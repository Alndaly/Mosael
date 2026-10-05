import { type JsonLd as JsonLdData, serializeJsonLd } from "@/lib/structured-data";

/**
 * schema.org 结构化数据。服务端组件:随静态 HTML 一起出,不靠客户端脚本 —— 百度的爬虫基本不跑 JS。
 *
 * 用 dangerouslySetInnerHTML 是因为 `<script>` 的内容不能经 React 的文本转义(`&quot;` 会让 JSON 失效);
 * 安全由 {@link serializeJsonLd} 负责:`<` 一律转义,数据关不掉脚本块。
 */
export function JsonLd({ data }: { data: JsonLdData | JsonLdData[] }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }} />;
}
