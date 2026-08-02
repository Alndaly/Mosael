# Plugin Manifest

插件是 `~/.open-studio/plugins/<目录>` 下的一个目录,里面有一份 `open-studio.plugin.json`
(也接受 `plugin.json`;更名前的 `mibu.plugin.json` 仍然认,否则用户磁盘上的既有插件会直接消失)。

插件页的空态会显示这个目录的**真实路径** —— Windows 上它不是 `~/.open-studio/`,别照着这里拼。

## 两种插件

### 本地脚本(默认)

```jsonc
{
  "id": "dev.example.text",           // 稳定唯一 id
  "name": "示例工具",
  "version": "0.1.0",
  "entry": "tools/main.py",           // 相对插件目录;必须在目录内
  "permissions": ["network:example"], // 自由字符串,逐项授权,deny-by-default
  "credentials": [
    { "key": "EXAMPLE_API_KEY", "label": "API Key", "help": "在哪儿拿", "secret": true, "required": true }
  ],
  "skills": [{ "id": "example", "description": "给别的智能体看的能力描述。" }],
  "tools": [
    {
      "name": "count_words",
      "description": "模型据此决定要不要调它。写清楚它**不是**用来做什么的。",
      "read_only": true,              // 见下面「只读」
      "input_schema": { "type": "object", "properties": { "text": { "type": "string" } }, "required": ["text"] }
    }
  ]
}
```

**执行协议**:spawn `<python> entry`,cwd = 插件目录,stdin 一个 JSON 请求,stdout 一个 JSON 响应。

```
stdin : {"tool": str, "input": {...}}
stdout: {"ok": true, "output": {...}} | {"ok": false, "error": str}
```

超时 60 秒,输出上限 1MB。进程崩了、超时了、吐了非 JSON —— 失败的是这次调用,不是应用。

### MCP 服务

```jsonc
{
  "id": "com.example.thing", "name": "示例", "version": "1.0.0",
  "kind": "mcp",
  "mcp": { "transport": "stdio", "command": "npx", "args": ["-y", "@scope/server"] },
  "credentials": [{ "key": "SOME_API_KEY", "label": "API Key", "secret": true }]
}
```

远端服务用 `http` 传输。`url` 和 `headers` 里可以用 `${KEY}` 引用凭据 —— 那些字段是 JSON 字符串,
进不了子进程环境,所以走占位符展开:

```jsonc
"mcp": {
  "transport": "http",
  "url": "https://example.com/mcp",
  "headers": { "Authorization": "Bearer ${SOME_API_KEY}" }
}
```

**工具清单从服务现拉**,不写在 manifest 里 —— 手抄的清单会随服务升级而烂,而且烂得很安静。
启用时拉一次,填完凭据后再拉一次,之后可以手动刷新。

MCP 插件的 `tools` 字段不是第二份清单,而是**按名字的覆盖层**,且只认 `read_only` 一个键。

## 字段

| 字段 | 说明 |
| --- | --- |
| `id` / `name` / `version` | 必填。id 是稳定标识,改了等于换了个插件。 |
| `kind` | `"process"`(默认)或 `"mcp"`。 |
| `entry` | 本地脚本的入口,相对插件目录。必须落在目录内。 |
| `mcp` | MCP 插件的连接配置:`transport` / `command` / `args` / `url` / `headers`。 |
| `permissions` | 自由字符串。逐项授权,**全部授予**之后工具才可用。 |
| `credentials` | 见下。 |
| `skills` | 给别的智能体看的高层能力描述,进 `/api/agent/skills`。 |
| `tools` | `name` / `description` / `input_schema`(JSON Schema)/ `read_only`。 |

## 凭据

`credentials` 每项:`key`(必须是合法环境变量名)、`label`、`help`、`secret`(默认 true)、
`required`(默认 true)。

用户在插件页填,运行时把**这个插件自己声明的、且已填的**键注入它自己的进程环境。

插件拿不到 Open Studio 的任何凭据 —— 供应商 key、数据库、API token 一个都没有。这是有意的隔离:
插件因此绕不过确认卡和权限系统。凭据注入没有破坏它,只是让插件自己的密钥有地方放。

必填凭据没填时,该插件的工具不进 `/api/plugins/tools`,也不进智能体的工具表。

## 只读

`read_only` 决定这个工具会不会给**子智能体**用。默认 `false`。

内置工具的只读判据是「没有确认门」—— 会改东西的都走确认卡。插件工具没有这个对应关系:它跑的
是别人的代码,没有确认门也照样能发请求、写文件。所以默认落在保守那侧,要 manifest 明写才算。
宁可让子智能体少一个工具,也不要让它在一次「帮我查一下」里替用户发了条微博。

## 接口

| | |
| --- | --- |
| `POST /api/plugins/scan` | 扫描插件目录;目录已不在的记录顺手清掉 |
| `GET /api/plugins/dir` | 插件目录的真实绝对路径 |
| `PATCH /api/plugins/{id}` | 启用 / 停用 |
| `DELETE /api/plugins/{id}` | 卸载:删目录 + 删记录(权限/凭据/调用记录随外键级联) |
| `GET`/`PATCH` `/api/plugins/{id}/permissions` | 权限授予 |
| `GET`/`PATCH` `/api/plugins/{id}/credentials` | 凭据(密文回显为掩码,原样提交 = 不改) |
| `POST /api/plugins/{id}/refresh` | 重拉 MCP 工具清单 |
| `GET /api/plugins/tools` | 已启用 + 已授权 + 凭据齐全的工具 |
| `POST /api/plugins/{id}/tools/{tool}/invoke` | 执行一次,留痕 |
| `GET /api/agent/tools` | 内置工具 + 展开成一等公民的插件工具(`plugin__<插件>__<工具>`) |

智能体、工作流、手动试跑走的是**同一条**执行路径(`invoke_plugin_tool`):权限校验、凭据注入、
调用留痕都在那里,没有谁能绕过它。
