# Baidu Netdisk

Moves files between Baidu Netdisk and the asset library: pull footage in from the netdisk, and save finished videos back
to it.

## What it can do

| Tool | Name | What it does |
| --- | --- | --- |
| `pan_list` | List a Netdisk folder | Lists the files and sub-directories in a directory with their `fs_id`; returns `has_more` and `next_start` when the listing isn't finished |
| `pan_search` | Search Baidu Netdisk | Searches by file name (recursively), for when you don't know the exact path; `has_more` is true when there are more hits than `limit` |
| `pan_import` | Import from Baidu Netdisk | Pulls a file into the asset library by `fs_id` and returns an `asset_id`. `fs_id` is declared as `format: "external_id"` (an id inside the netdisk): used in workflows and chat, not on boards |
| `pan_upload` | Upload to Baidu Netdisk | Uploads one file from the asset library to the netdisk and returns its `fs_id`; reports progress as it goes, can be cancelled, runs up to 30 minutes |

Once you have an `asset_id`, it is an ordinary asset: put it on the timeline, use it as the first frame of a generation,
publish it; it all works the same.
`pan_import` and `pan_upload` are also workflow nodes ("Import from Baidu Netdisk" / "Upload to Baidu Netdisk").

## How uploading works

Baidu's upload protocol itself has three steps; this is not a detour on our side:

1. **precreate**: report the file size and the md5 of every part, and get an uploadid.
   **Instant upload happens at this step**: if Baidu recognises those md5s it returns the result directly and not a
   single byte has to be sent.
2. **superfile2**: upload part by part. Parts are fixed at 4 MB (Baidu's rule, not a tunable parameter; with any other
   size the md5 list reported in precreate won't match).
3. **create**: report the uploadid and the part list; only then does the file actually exist.

No step can be skipped: if you upload without create, the file simply doesn't exist on the netdisk, even though every
superfile2 call returned success.

**It doesn't overwrite by default**: when a file with the same name exists, it saves a copy. Wiping out something on
someone's netdisk with one wrong upload costs far more than an extra copy. To overwrite, pass `overwrite: true`
explicitly.

The md5 is computed as a stream, without loading the whole file into memory, since uploads are often finished videos of
several GB.

Uploading is a **streaming tool**: it reports progress after every part (the workflow node shows something like
"Uploaded 12.0 / 96.0 MB"), and cancelling stops between parts; the manifest gives it a 30-minute budget
(`timeout_seconds`), since the default 60 seconds isn't enough for a finished video of several hundred MB.
A netdisk path without the leading `/` is accepted too.

## How the plugin gets the file

`asset_id` in `pan_upload` is marked `"format": "asset"` in the manifest, so **what the host hands over is already a
local path** (see "Receiving a file" in [PLUGIN_MANIFEST.md](../../../docs/PLUGIN_MANIFEST.md)).
The plugin side doesn't know the asset library exists, and doesn't need to.

It gets a copy, not the original, and the copy is deleted when the call ends.

## Setup

1. Register an app on the [Baidu Netdisk Open Platform](https://pan.baidu.com/union) to get an AppKey / SecretKey
2. Add this package on Mosael's Plugins page and fill in the AppKey and SecretKey
3. Click **Authorize** to the right of "Authorization" on the first row of the connection: log in and agree on the Baidu
   page that opens, then paste the authorization code it shows back in

The `refresh_token` (valid for 10 years) and `access_token` you get back are stored in this connection automatically,
and the "Authorization" row changes to **Authorized**. These two fields aren't shown next to the AppKey; if you already
have a refresh_token, click "Enter tokens manually" on the "Authorization" row to expand them and fill it in yourself,
and **just leave** the Access Token field **empty**: the plugin exchanges the refresh_token for one on its own.

When Baidu stops accepting the stored tokens (the refresh_token was revoked, or it still says expired after one
renewal), the plugin includes `reauthorize: true` in the failure response and the connection is marked **Needs
re-authorization**; click "Re-authorize" and go through it once more.


### Tokens renew themselves

Baidu's `access_token` expires after thirty days. When the plugin hits the "expired" errno, it gets a new one, retries
once unchanged, and hands the new token back to the host to remember (through the
[`state` channel](../../../docs/PLUGIN_MANIFEST.md)). Fill in the refresh_token once and you never have to think about
it again.

**Both access_token and refresh_token are remembered**: Baidu rotates the refresh_token along with it when it issues a
new token, so if only the former were stored, thirty days later you'd be exchanging one that has already been revoked
and get a failure with no visible cause.

If it is still expired after one renewal, the problem isn't the expiry (wrong AppKey, app suspended), and only then is
it reported in the interface, **retrying only once**: trying again would just hammer the API with the same error.

**Every endpoint goes through the same renewal path**, including precreate / create during uploads; a second renewal
within the same call uses the refresh_token that was just rotated. If the call **fails** after renewing (for example the
file doesn't exist), the new tokens are still handed back to be remembered, because Baidu has already revoked the old
ones.

## Why it doesn't download files itself

`pan_import` only gets as far as a dlink and hands that to the host (see the artifact section of
[PLUGIN_MANIFEST.md](../../../docs/PLUGIN_MANIFEST.md)). The reason isn't convenience:

- The plugin side only gets **one short-lived stdio call**; downloading a 2 GB file itself would certainly time out
- Even if it didn't time out, the user would see no progress, and pressing cancel wouldn't stop it
- Progress, retries, size limits and failure isolation are all already in the host's job system

A dlink happens to be the kind of address that **can only be downloaded with credentials**: without
`User-Agent: pan.baidu.com` it returns 403 outright, and the `access_token` has to be appended to the url too. So
what's handed over is not just the url but also that set of request headers, which is exactly why the artifact channel
supports `headers`.

## Status

The API shapes follow the Open Platform documentation, and the offline parts (building parameters, pagination, errno
translation, the artifact hand-off) are covered by tests. **It has not yet been run against a real account**: the
first time it is connected to a real one, please check the fields returned by `pan_list` / `filemetas`.
