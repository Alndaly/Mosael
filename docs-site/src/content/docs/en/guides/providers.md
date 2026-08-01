---
title: Configure model providers
description: Add AI providers per capability, set default models, cost rules.
sidebar:
  order: 1
---

Open Studio's AI features (agent chat, text-to-image / video, voiceover, transcription) are bring-your-own-key: most vendors take an **API key**, subscription plans use **authorized sign-in** (below). Credentials never leave this machine; the settings API returns a masked hint or just "linked / not linked", never the plaintext.

## Configured per capability

Settings groups AI providers into four **capability sections**, each configured independently:

| Section | Used by |
| --- | --- |
| **AI Chat** | the agent and workflow LLM nodes |
| **AI Image** | text-to-image generation |
| **AI Video** | text-to-video generation |
| **AI Audio** | TTS voiceover / podcast synthesis |

At the top of each section is the **default model**: the default provider and model for that capability, overridable in place wherever it's used. The dropdown lists **models** (e.g. "DeepSeek · deepseek-v4-pro"), not providers — several models under one provider each appear on their own.

![Settings → AI Image: default model + configured provider list](../../../../assets/screens/settings-models.png)

**Configure providers per capability** — Chat / Image / Video / Audio each have their own section; after "Add provider" the UI renders exactly the fields that provider declares, and keys are stored locally:

![Demo: provider configuration entries for AI Chat and AI Image](../../../../assets/gifs/providers.gif)

## A provider is one endpoint plus one credential

A provider is **not** a model. It records where to connect and which credential to use, and it can
hold **any number of models**. Click the chevron on a provider row to see its model list.

## Add a provider

Click **Add provider** in the relevant section:

1. Pick a **vendor** (built-ins include Alibaba DashScope, Volcengine ARK (video / Seedream image), Kimi, MiniMax, OpenAI, Google, Kuaishou Kling, OpenAI-compatible endpoints; the catalog grows over time).
2. Give it a **name** (e.g. "My Kimi").
3. Paste the **API key** (subscription plans have no key field — you authorize after saving instead). A "Get API key ↗" link jumps straight to that vendor's key console.
4. **Base URL**: leave empty for the vendor default (the placeholder shows it); OpenAI-compatible endpoints need it filled in.
5. **Model** is optional; if filled it becomes this provider's first model. You can add more at any time.

Providers can be **enabled / disabled** at any time without deleting.

## Managing its models

Expand a provider row:

- **Add a model**: the "Add model…" field at the bottom is a **searchable** input listing catalog models you haven't configured yet. Catalogs run to hundreds of entries (DashScope has 233), so it searches rather than scrolls. Models absent from the catalog — private deployments, aliases — can simply be **typed in**; they work exactly like catalog ones and are only badged "not in catalog".
- **Enable / disable** a single model with the switch. Disabled models disappear from the default-model dropdown and every model picker.
- **Model settings** (gear icon):
  - **Capabilities**: which sections this model serves (chat / image / video / tts / podcast). Empty means "follow the vendor preset". This is how one endpoint expresses "a chat model *and* an image model".
  - **Context window**: decides how long a conversation can run before compaction kicks in. Defaults to the vendor catalog; when the catalog doesn't know the model, a conservative 32000 is used and you can override it. The line underneath says whether the current value is **yours, the catalog's, or the fallback**.
  - **Advanced** (collapsed): four compatibility switches — reasoning model, vision, reasoning effort, developer role. You only come here when an endpoint rejects a request; normally none of them need touching.
- **Delete** with the trash icon.

> The context window and the compatibility switches only show for **chat** models — asking an image model whether it supports the developer role is noise.

## Subscription plans: authorize instead of pasting a key

Claude Pro/Max, Kimi Code, ChatGPT Plus/Pro, GitHub Copilot, xAI and OpenRouter are **subscriptions** with no key to paste. Pick the matching entry when adding a provider under AI Chat, save, then click **Authorize** on that row:

1. Some vendors first ask for a **sign-in method** (Codex offers browser authorization or a device code).
2. The dialog shows an **authorization link** or a **device code**; complete it in your browser. Vendors that need a pasted code get an input field right there.
3. Once authorized, the models that account can actually use are pulled in automatically (Copilot's vary by plan tier; OpenRouter has hundreds).

**Tokens refresh themselves.** Expiry is simply how subscription tokens work — the app refreshes them when they're used and whenever you open Settings. Only a *failed* refresh (signed out elsewhere, authorization revoked) surfaces, in warning colour, as "re-authorization needed"; click **Re-authorize** then. **Revoke** disconnects the account.

### Checking your quota

Subscription rows carry an extra **gauge icon** showing the current plan, each quota, and when it resets.

It is **fetched on click**. None of these quota endpoints is a documented public API (they're what each vendor's own CLI uses internally), so polling them on a timer would both trip rate limits and quietly rot into a permanently failing background task the day a vendor changes something. When a fetch fails, the message distinguishes "this vendor isn't supported" from "this attempt didn't succeed".

## Outbound proxy

When a vendor blocks your region (authorization or calls rejected, "region not supported"), set a proxy under Settings → **Local backend → Outbound proxy**. Both provider calls and authorization sign-in go through it.

- Loopback traffic **never** goes through the proxy (otherwise every agent tool call would break) — nothing to configure.
- The embedded browser is **unaffected**: publish-account logins carry their own per-account proxy.

## Retries on a flaky network

Settings → **AI runtime** sets the retry count. It applies to **every** AI call — chat, image, video, audio, embedding — because rate limits and 502s don't discriminate. On 429 / 5xx / connection failure the request retries with exponential backoff, with nothing required from you.

## Cost rules

Under Settings → **Cost rules** you can price models (per token / per image / per second); Home and the task center accumulate AI spend accordingly. Unpriced usage is labeled "unpriced".

When a vendor's catalog carries public pricing (OpenRouter, for one), **Prefill from catalog** generates rules in bulk — it only fills what's **missing** and never touches what you've already entered (your prices may include a discount or an enterprise agreement). Catalog entries priced at 0 produce no rule: that means "unpriced / included in the subscription", not "free".

## Bindings: missing config surfaces where it's needed

Models are **bound** to the places that use them. When something isn't configured, that place tells you and links to the fix:

- Workflow **LLM / AI-generate nodes**: with no usable provider (or a deleted one referenced), the inspector shows an amber / red banner with a "Configure" shortcut.
- **AI Studio** generation: with no usable generation model, the list shows the same prompt.

> The generation model catalog always has built-in entries; whether they actually run depends on **the corresponding vendor key being configured**.
