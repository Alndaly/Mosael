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
