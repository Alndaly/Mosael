# MCP 接入范例

**这个插件没有一行代码。** 它只是声明"去连这个 MCP server",工具清单由那个 server 自己提供。

越来越多平台自己就发 MCP server。碰到那种情况,再写一个 Python 脚本去把 stdin 的 JSON 翻译成
一次 HTTP 调用、再把结果翻译回 stdout,是在重新实现一个已经存在的东西 —— 而且每加一个端点都
要改代码。声明式接进来就够了。

接进来之后,它的工具和内置工具走的是同一条路:

- **智能体**:展开成一等公民工具(`plugin__<插件>__<工具>`),模型直接看到名字和入参模式,
  不需要先"想到"可能有插件能帮忙。
- **工作流**:「插件工具」节点的下拉里直接选得到。

## 两种传输

**stdio**(本例):spawn 一个子进程。环境只有 PATH / HOME / LANG,加上这个插件自己声明的凭据 ——
和本地脚本类插件同一条规矩,拿不到应用的任何密钥。

```jsonc
"mcp": { "transport": "stdio", "command": "npx", "args": ["-y", "@scope/some-server"] }
```

**http**:连一个远端 MCP server。url 和 headers 里可以用 `${KEY}` 引用 manifest 声明的凭据 ——
那些字段是 JSON 字符串,进不了子进程环境,所以走占位符展开。

```jsonc
"mcp": {
  "transport": "http",
  "url": "https://example.com/mcp",
  "headers": { "Authorization": "Bearer ${SOME_API_KEY}" }
},
"credentials": [{ "key": "SOME_API_KEY", "label": "API Key", "secret": true }]
```

## 工具清单什么时候拉

启用时拉一次,填完凭据后再拉一次,之后可以在插件页点「刷新工具」。**不在 manifest 里手抄一份** ——
手抄的清单会随 server 升级而烂,而且烂得很安静。

## 只读标记

MCP server 报上来的工具默认**不算只读**,所以子智能体拿不到它们。这是刻意保守的:一个没有确认门
的插件工具照样可能发请求、写文件,而子智能体是用来"帮我查一下"的。要放开,在 manifest 的
`tools` 里按名字覆盖声明 `"read_only": true`。
