# Object Storage

Uploads files from the asset library to **your own bucket** and hands back a public direct link; it can also list the
objects in a bucket, sign direct links for existing objects, and pull objects back into the asset library.
**Built into the app**: once Mosael is installed it is already on the Plugins page.

One connection is one bucket, and the provider is a setting of the connection:

| Provider | When the endpoint is empty | Signature | Longest presign |
| --- | --- | --- | --- |
| Alibaba Cloud OSS | `oss-<region>.aliyuncs.com` | Native V4 (`OSS4-HMAC-SHA256`) | 7 days |
| Tencent Cloud COS | `cos.<region>.myqcloud.com` | Native `q-sign-algorithm=sha1` | Unlimited |
| Volcengine TOS | `tos-<region>.volces.com` | `TOS4-HMAC-SHA256` | 7 days |
| Amazon S3 | `s3.<region>.amazonaws.com` | SigV4 | 7 days |
| S3-compatible service | Required (e.g. `http://localhost:9000`) | SigV4, path-style addressing | 7 days |

For Tencent Cloud, enter the **full bucket name with the APPID**, e.g. `examplebucket-1250000000`. S3-compatible
services (MinIO, Cloudflare R2…) use path-style addressing (`<endpoint>/<bucket>/<object>`), since self-hosted services
usually don't have a wildcard domain set up for each bucket; the endpoint may use `http://`.
For Cloudflare R2, set the region to `auto`.

## The specific problem it solves

Mosael is **local-first**: the files in your asset library live on your own disk and have no public address. Some
providers, however, only accept links; the reference video for Volcengine Ark's Seedance is one example. Its official
documentation is explicit (translated):

> Make sure the URL is a publicly accessible link (we recommend storing it in the TOS object storage service and
> configuring it as public-read)

And it **explicitly does not accept Base64**: a reference **image** can be sent as a data URL, a reference **video**
cannot.

`storage_upload` is the bridge: it uploads the asset and hands back a **time-limited direct link**. The signature is in
the query string, so **the bucket doesn't need to be public-read**: anyone who has the link can download it, but it
stops working once it expires. It declares `public_url` in its manifest, so when a generation has a slot that only
accepts links and you gave it a local asset, the host calls it **automatically** (if you have several buckets, choose
the default one under "Settings → Capability providers → Asset links"), and reuses the link for the same asset until it
expires instead of uploading it again.

## Four tools

| Tool | Name | What it does |
| --- | --- | --- |
| `storage_upload` | Upload to object storage | Uploads an asset and returns a time-limited direct link plus the public-read address. **Streaming**: large files are uploaded in parts with progress reported along the way; cancelling stops between parts and cleans up the parts already uploaded |
| `storage_presign` | Sign a direct link | Signs a time-limited direct link for an object already in the bucket |
| `storage_fetch` | Fetch from object storage | Pulls an object from the bucket back into the asset library (**it hands over an address and the host moves the bytes**, so progress, cancelling and retries are all the host's job). The object key is declared as `format: "external_id"`: fetching by an address in the bucket is an import, not a content transformation, so it is used in workflows and chat and not on boards |
| `storage_list` | List bucket objects | Lists the objects under a prefix, up to 1000 per page, and returns `next_cursor` when there is another page |

The default object key is `mosael/<content hash>/<original file name>`: two assets both named `image.png` don't
overwrite each other, and re-uploading the same content lands on the same key.

Uploads larger than 64 MB go in parts (Initiate → UploadPart × N → Complete, the same flow for all four providers), and
each part is retried on its own (rate limiting, temporary server errors, dropped connections); on failure or cancel the
upload is aborted, because parts left in the bucket are billed for storage and are invisible in the console.

Failures are explained by cause in plain words: when the bucket is in another region it names the region to enter, and
it also recognises a wrong key, missing permission, clock skew, a bucket that doesn't exist and so on, always with the
original error code.

## Why not the official SDKs

A plugin process is a short-lived script speaking the stdio protocol. Installing a whole SDK just to sign a few kinds of
requests costs install size, version conflicts, and a supply chain we don't control. The signing itself is a one-page
algorithm, pure `hmac` + `hashlib`:

- `tools/sigv4.py`: the three SigV4-family providers (S3 / TOS / OSS) are **the same algorithm with different words**:
  the algorithm name, the date header, the end of the scope, the first step of the key derivation chain and the presign
  parameter names all differ; Alibaba Cloud V4 is also structured differently (it signs only the default kinds of
  headers, has the `AdditionalHeaders` line, and writes query parameters without a value as just their name).
- `tools/qsign.py`: Tencent Cloud COS's native signature, which is not part of the SigV4 family.

Every kind of signature (including the four requests of a multipart upload) is checked against vectors computed by the
official SDKs from the same inputs (`backend/tests/test_*_signature_matches_the_sdk.py`,
`test_object_storage_multipart_matches_the_sdk.py`).

## One plugin, not five

This used to be four plugin packages (Alibaba Cloud OSS / Tencent Cloud COS / Volcengine TOS / Amazon S3), with the
main body (uploading, listing and so on) copied byte for byte between the packages and a test pinning them so they
didn't drift apart. Yet the only differences between them fit in one table in `tools/providers.py`: signature dialect,
default endpoint, presign limit and addressing style. Now the main body (`tools/storage.py`) doesn't know a single
thing about "Alibaba Cloud", and adding a provider means adding a row to the table.

On upgrade, the old four plugins are merged in place by the `merge-object-storage-plugins` migration: connection ids
stay the same, and the config, keys (not decrypted, only renamed), grants, tool switches, the "Asset links" default,
the direct link cache, and nodes in workflows and on boards all move over; the old packages' folders are deleted.

## Permissions and keys

Create a sub-user / RAM user that **can only read and write this one bucket**; don't use the root account's keys. The
only things the plugin can read are this connection's config and that pair of keys: it has no database, no API token
and no media directory (that is part of the isolation boundary).
