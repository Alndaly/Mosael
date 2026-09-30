# TikHub

Read **public** data from Douyin / TikTok / Xiaohongshu / Bilibili / Kuaishou and other platforms: post details, creator profiles and their post lists,
keyword search, trending charts. For topic research, studying comparable accounts, and finding footage ideas.

**This plugin contains not a single line of code.** TikHub publishes its own MCP service; declaring the connection to it is all it takes.

## Configuration

Plugins page → New connection:

| Where | Key | Notes |
| --- | --- | --- |
| Configuration | `TIKHUB_PLATFORM` | Which platform's endpoint this connection uses (pick from the dropdown); see the list below |
| Credentials | `TIKHUB_API_KEY` | Generate it at <https://user.tikhub.io>; it is injected into this connection only |

The connection name follows the platform ("TikHub · Bilibili"). Once the credential is filled in, the tool list is fetched once automatically; after changing the platform, click "Refresh tools" on the plugin page.

Platform values: `douyin` `tiktok` `xiaohongshu` `bilibili` `kuaishou` `weibo` `zhihu` `instagram`
`youtube` `twitter` `threads` `linkedin` `reddit` `wechat` `others` `tikhub`.

**To use two platforms at once**: create another connection, choose the other platform, and enter the same (or another) key. One connection maps to one MCP endpoint
(`https://mcp.tikhub.io/{platform}/mcp`) — that is the shape of TikHub's MCP; a single plugin can have as many connections as you like,
and workflow nodes and agents tell them apart by connection.

## Why we switched from "our own script" to "connecting to MCP"

The previous version was a Python script exposing only one generic `tikhub_fetch(path, params)`: the caller had to find the path
in the docs itself. That was the approach when there was no alternative — TikHub spans a dozen-plus platforms and hundreds of endpoints, and a copy
of that list inside the plugin would inevitably rot, so we didn't copy it at all.

But TikHub already has an MCP service (`https://mcp.tikhub.io/{platform}/mcp`, Bearer auth). Once connected to it:

- The tool list is **fetched live from the service**, and each tool carries its own name, description and input schema — the model no longer has to guess paths.
- When the service adds new endpoints, one click on "Refresh tools" brings them in, with no plugin change and no release.
- There is not a single line of code in the plugin directory, so there is no code to rot.

Writing another script layer that translates JSON from stdin into an HTTP call and the result back to stdout would be reimplementing
something that already exists.

## What if there are too many tools

One platform may have dozens of endpoints. Putting them all into the agent's tool table would crowd out the built-in capabilities, and every conversation turn would pay tokens
for those dozens of descriptions. So `tools.expose` is `"selected"`: tools are off by default; tick, one by one on the plugin page, the few you want the agent to use.
Names are whatever the plugin page lists after "Refresh tools"; to rename a tool or mark it read-only, write it in `tools.overrides`:

```jsonc
"tools": {
  "expose": "selected",
  "default_effects": "paid",
  "overrides": {
    "fetch_one_video": { "read_only": true }
  }
}
```

`default_effects: "paid"`: every TikHub endpoint deducts credits per call, so the agent shows an approval card before calling (see the
approval section, `effects`, in `docs/PLUGIN_MANIFEST.md`; under the auto-approve rules it is allowed according to the paid-call rule). Tools marked `read_only` don't ask anyone,
and sub-agents can use them too — none are marked by default: the plugin runs someone else's service, so we would rather give sub-agents one tool fewer.

Sources: [TikHub MCP](https://tikhub.io/mcp) · [TikHub API docs](https://docs.tikhub.io/)
