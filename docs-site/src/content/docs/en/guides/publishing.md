---
title: Publishing & account matrix
description: One-click distribution to Douyin / RedNote / WeChat Channels / Bilibili, with persistent multi-account logins and proxies.
sidebar:
  order: 7
---

The **Publish** page has two tabs (it remembers which one you were on): **Publish records** and **Account matrix**.

## The page at a glance

![Publish page: publish records and account matrix tabs](../../../../assets/screens/publish.png)

**Add accounts in the matrix and create a publish task** — pick a platform and a rendered video, fill in title / description / tags (per-platform title limits are validated up front), and "AI copy" can draft platform-fitting text for you:

![Demo: add-account dialog in the account matrix and the new-publish dialog](../../../../assets/gifs/publishing.gif)

## Account matrix

The account matrix manages accounts across platforms; login state is persisted by the desktop shell and survives restarts:

- **Add account**: pick a platform (Douyin / RedNote / WeChat Channels / Bilibili, …), sign in once and it stays.
- **Re-check / sign in / switch**: re-verify login state anytime; sign in again if it expires.
- **Per-account proxy**: assign a proxy to a single account (right-click → Proxy).
- **DevTools / inspect**: open devtools for one account when troubleshooting.

Logins run in an embedded browser view with an address bar / back / forward / reload and a "Back to Open Studio" button.

## New publish

Pick a finished cut, set title, description and tags, choose targets:

- A signed-in **social account** (Douyin / RedNote / WeChat Channels / Bilibili). The desktop app's embedded browser does the upload using your session, so **publishing is unavailable in the browser build**.
- Copy can be **AI-written**.
- The workflow **publish** node automates the same thing.

## Publish records

Every publish job is tracked under **Publish records** — view details, open the resulting page, delete. Status changes flow into the notification / task centers and click through to the record.
