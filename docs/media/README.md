# Current interface captures

The website and both READMEs use the **1.0.0** interface captured from the running app, not reconstructed UI or generated mockups. The canonical files live in [`website/public/media`](../../website/public/media). Historical design-review attachments elsewhere in `docs` are not current product documentation.

## Source and credit

Sample footage and extracted frames: **Big Buck Bunny**, © 2008 Blender Foundation / www.bigbuckbunny.org, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). [Film and license](https://peach.blender.org/about/); [source trailer](https://media.w3.org/2010/05/bunny/trailer.mp4). Excerpts are trimmed, resized and rearranged in the demo timeline. Narration was synthesized with the macOS Samantha voice; subtitle cues are manually prepared editing exercises.

The demo backend is isolated from personal projects and credentials. Empty AI and publishing pages show the actual unconfigured state. No AI responses, tool successes, login successes or platform posts are fabricated. The Chinese and English interface recordings use the same bilingual sample project.

## Inventory

- `screens/`: full-resolution native screenshots (2880 × 1800).
- `gifs/`: actual browser recordings converted to looping 960 × 600 GIFs.
- `videos/`: the same interactions as user-controlled 1280 × 800 MP4 recordings.
- Chinese light files are at each directory root; `dark/` contains Chinese dark; `en/` and `en/dark/` contain English light and dark.
- `capture-manifest.json` records source commit, capture time, scene, locale, theme, byte count and SHA-256 for every capture.
- `mosael-promo.mp4` is a concatenation of the current Home, media preview, timeline, board and workflow screen recordings, with no simulated product output.

Scenes: Home and project navigation; import and media previews; timeline selection/playback; subtitle dubbing and Transcript; AI Chat/Trace/Generate; workflow node catalog and parameters; board forms and `@` media picker; plugin connections; publishing form and browser accounts; scheduled tasks; provider/ASR settings; interface fonts; sign-in.

The previous handcrafted promo, obsolete GIF aliases and unused website hero images were retired rather than left beside current captures.

## Re-record

Run the current frontend on `http://127.0.0.1:5173` and an **isolated demo backend** on a loopback port. Import appropriately licensed sample media, prepare a project with video/audio/subtitle tracks, a board, the official speech-cleanup workflow, a scheduled task and sample plugin connections. Do not use a personal backend for public recordings.

Prepare a private JSON-string token file and a fixture JSON containing `project`, `sequence`, `board`, `workflow` IDs and an `assets` map with `forest`, `narration` and `forest-frame` IDs. The recording script names its expected demo cards explicitly; keep those titles aligned when updating the fixture. Never commit either authentication tokens or the demo database.

```bash
backend/.venv/bin/python scripts/record-doc-media.py \
  --api http://127.0.0.1:8812 \
  --token-file /tmp/demo-token.json \
  --fixture /tmp/demo-capture.json
```

Requires Playwright Chromium and ffmpeg. Use `--locale zh|en`, `--theme light|dark`, or `--only scene,scene` to retry a scene. A failed selector stops capture instead of substituting an old image. The script performs real clicks and records real browser video; it does not replace UI text or DOM content.

After recording, review screenshots and moving frames, update the related bilingual guide and its version, run `pnpm --dir website test` and `pnpm --dir website build`, and check both themes on desktop and narrow screens. The media tests reject stale/untracked public captures, incorrect-language references and missing light/dark pairs.

## README showcase

`readme-showcase.png` is an AI-assisted decorative composition of the three unaltered application captures preserved in `readme-shots/`. The layers show dark Space Grotesk editing, light Caveat handwriting, and dark Newsreader media browsing. The composite is promotional artwork; use the original captures and canonical website images to inspect interface details. These additional screenshots share the sample-footage credit above.

The canonical capture manifest retains the original capture version (`1.0.0-beta5`) and records `documentedVersion: 1.0.0`. The stable release uses the same interface code; only release metadata changed after capture.
