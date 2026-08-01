---
title: AI Studio
description: A conversational agent that operates your project, plus text-to-image / text-to-video generation.
sidebar:
  order: 3
---

**AI Studio** has two modes, toggled at the bottom-left of the composer: **Chat** and **Generate**.

## Chat: the agent operates your project

The agent uses Open Studio's MCP tools to **see your project and propose changes**: searching media, arranging the timeline, kicking off generation, even publishing.

![AI Studio chat mode: agent environment panel on the right (context / session / capabilities)](../../../../assets/screens/ai-chat.png)

- **Confirmation cards**: any action that would mutate project / external state pops a confirmation card and only lands after you approve.
- **Skills**: preset skills (opencode-style) are available at the bottom-left of the composer.
- **Attachments**: upload images / videos for the agent to analyze (multimodal).
- The left column lists **conversations**; each is independent and can be renamed / deleted.

Under the hood it hosts an external coding-agent CLI (opencode-style), not a home-grown chat loop. Requires [model providers](/en/guides/providers/) to be configured.

### The composer keeps only what you look at every turn

The composer row carries just the things you touch on every message: the **Chat / Generate** toggle,
attachments, the **model**, and send. Everything else lives behind the slider icon in **session
settings** — the set-once-and-forget things:

- **Thinking**: off / low / medium / high. When on, the model's reasoning streams into a collapsible
  block you can expand, and it auto-collapses when done. "Off" only means we don't *ask* for it:
  models that reason regardless (k3, DeepSeek reasoner) still have their thinking shown.
- **Video analysis mode**: whole clip vs sampled frames.
- **Context**: a meter with "N% left", plus **Compact context now**.

### What happens when the context fills up

Once a conversation runs long, the app has the model **summarize the earlier turns** and keeps the
recent ones, freeing room to continue. This is never silent — a record stays in the conversation
saying how many messages moved out and roughly how many tokens were freed; expand it to read the
summary itself.

- It triggers at **80%** of the selected model's context window. Windows differ per model and are
  editable in [model settings](/en/guides/providers/).
- You can compact on demand instead of waiting — it costs one model call, so it's an explicit button
  rather than something that fires on its own.
- The meter is anchored on **real usage reported by the vendor** (the last call's input + output);
  only messages newer than that are estimated.

## Generate: text-to-image / text-to-video

In **Generate** mode the left column is the **generation model** catalog, the middle is the results feed, and the composer takes your prompt:

![AI Studio generate mode: results feed and engine parameters on the right](../../../../assets/screens/ai-generate.png)

**Switch between chat and generate in one click** — describe the shot in the bottom input, tune engine parameters on the right; results can be sent straight to the media library:

![Demo: switch to generate mode and type a prompt](../../../../assets/gifs/ai-studio.gif)

- Pick a model → write a prompt → send; the job queues and finished results land in the media library.
- Whether a model can run depends on **its vendor's key** being configured; with no usable model, a banner at the top links to settings.

## Feishu (Lark) binding

Settings → Feishu bot connects the agent to Feishu so you can chat from there.

**Changes that need confirmation arrive as a card in that same Feishu chat — approve or reject
without leaving Feishu.**

Who may approve follows the account binding: whoever taps the button must already have their
Feishu account bound to an Open Studio account, and must still be a member of the workspace.
Everyone in a group chat can see the card; seeing it is not permission to approve it.

Two developer-console settings are required for this (neither is settable via API, so one-click
bot creation cannot do it for you): subscribe to `card.action.trigger` under Event Subscriptions,
enable **Interactive Card** under App Features → Bot, then republish the app. Until then the bot
falls back to a plain-text notice telling you which switches to flip.
