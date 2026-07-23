---
title: Plugins
description: Pure-function tools in a local trusted sandbox, exposed to the agent and workflows.
sidebar:
  order: 6
---

Plugins are **pure-function tools** running in the same local trusted sandbox as the code node, automatically exposed to the agent and workflows.

## Install & toggle

- On the **Plugins** page, click **Scan** to discover local plugins; each can be enabled / disabled.
- A plugin's `manifest` declares its tools and required **permissions**; permissions are granted one by one, and ungranted tools stay unavailable.

## Tools & call log

- **Tools**: the panel lists each tool; fill in parameters and try it in place.
- **Call log**: recent calls are recorded (success / failure + input & output), expandable per entry; delete one or clear all.

## In workflows

The workflow **plugin tool** node picks a tool from an enabled plugin and feeds upstream variables in as arguments.
