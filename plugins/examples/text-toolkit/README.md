# Text Toolkit

Small text utilities that run entirely on this computer. Word and character counts, subtitle line
breaking, shortening to a length, copy cleanup, Markdown-to-plain-text, and extraction of hashtags,
links, @mentions and email addresses.

## Install

This example ships with the repository. In **Plugins → Install from folder**, choose
`plugins/examples/text-toolkit`; the manifest is `mosael.plugin.json`. It requests **no permissions**
and has no local service or external network access.

## Tools

All tools are read-only and available to the agent, workflows and boards.

| Tool | What it does | Main options |
| --- | --- | --- |
| `word_count` | Characters, words and estimated read-aloud time. Each CJK character counts as one word; about 4.5 Chinese characters or 150 English words per second / minute. | `text` |
| `split_lines` | Breaks a script into subtitle lines. Splits at sentence ends, then at pauses such as commas; never inside an English word. Trailing punctuation is dropped by default. | `text`, `max_chars` (default 16), `keep_punctuation` |
| `truncate` | Shortens text to a character limit at a pause or word boundary where possible. | `text`, `max_chars` (default 20), `ellipsis` (default `…`) |
| `clean_text` | Removes zero-width characters, stray spaces and extra blank lines; converts full-width letters / digits to half-width. Optionally full-width punctuation after Chinese, spaces between Chinese and Latin text, or emoji removal. | `text`, `chinese_punctuation`, `space_between`, `remove_emoji` |
| `strip_markdown` | Turns headings, bold, links, quotes and lists into paste-ready plain text; list items become `• `. Code blocks stay as code. | `text`, `keep_urls` |
| `extract_hashtags` | Pulls `#topic#` and `#hashtag` tags in order; case-insensitive duplicates and all-digit tags such as `#1` are skipped. | `text` |
| `extract_links` | Pulls URLs, @mentions and email addresses in order, without duplicates. | `text` |

Every tool also returns a one-line `summary`; the workflow node outputs are declared in the manifest
so they can be wired without a second definition.

## Workflows and boards

Drag the plugin's node into a workflow, or use it from a board cell. `summary` is exposed to boards by
default; `split_lines.text`, `truncate.text`, `clean_text.text`, `strip_markdown.text`,
`extract_hashtags.hashtags`, `extract_links.urls` and `word_count.summary` are available as node
outputs.

## Notes

- Pure local computation: no model, no API key, no upload.
- Limits and output labels live in `mosael.plugin.json`; the implementation is `tools/main.py`.
