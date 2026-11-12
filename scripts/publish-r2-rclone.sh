#!/usr/bin/env bash
# Publish one release directory to R2 with rclone's multipart uploader.
#
# Usage: scripts/publish-r2-rclone.sh 2.4.2
# Requires rclone and the key=value file at MOSAEL_R2_ENV (default
# ~/.mosael-release-r2.env) containing R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY and R2_BUCKET.
set -euo pipefail

VERSION="${1:?usage: scripts/publish-r2-rclone.sh VERSION}"
TAG="v${VERSION}"
DIST="dist/${VERSION}"
ENV_FILE="${MOSAEL_R2_ENV:-$HOME/.mosael-release-r2.env}"
PUBLIC_BASE="${R2_PUBLIC_BASE:-https://dl.mosael.com}"

[[ -d "$DIST" ]] || { echo "missing $DIST" >&2; exit 1; }
[[ -f "$DIST/SHA256SUMS" ]] || { echo "missing $DIST/SHA256SUMS" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "missing R2 env file $ENV_FILE" >&2; exit 1; }
command -v rclone >/dev/null || { echo "rclone is required" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
PREFIX="${R2_PREFIX:-mosael}"
BUCKET="${R2_BUCKET:?missing R2_BUCKET}"
: "${R2_ACCOUNT_ID:?missing R2_ACCOUNT_ID}"
: "${R2_ACCESS_KEY_ID:?missing R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?missing R2_SECRET_ACCESS_KEY}"

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"
export RCLONE_CONFIG_R2_REGION=auto
export NODE_OPTIONS="${NODE_OPTIONS:---dns-result-order=ipv4first}"

# R2 has no directory index. Generate the same page the release script would.
VERSION="$VERSION" DIST="$DIST" node --input-type=module <<'JS'
import fs from "node:fs";
import { renderDownloadPage } from "./scripts/r2-download-page.mjs";
const files = fs.readdirSync(process.env.DIST).filter((name) => fs.statSync(`${process.env.DIST}/${name}`).isFile());
fs.writeFileSync(`${process.env.DIST}/index.html`, renderDownloadPage(files, `v${process.env.VERSION}`));
JS

REMOTE="r2:${BUCKET}/${PREFIX}"
IMMUTABLE="${REMOTE}/${TAG}"
LATEST="${REMOTE}/latest"

# Immutable copy first. Large objects go through multipart upload, never a
# single PutObject (Cloudflare caps that at 300 MB).
rclone copy "$DIST" "$IMMUTABLE" \
  --transfers 4 --s3-upload-concurrency 4 \
  --s3-upload-cutoff 16M --s3-chunk-size 16M \
  --stats-one-line --stats 30s
rclone check "$DIST" "$IMMUTABLE" --checksum --one-way

# Then server-side copy to latest. --ignore-times is required: metadata files
# change without changing size, and size-only would silently keep the old release.
rclone copy "$IMMUTABLE" "$LATEST" \
  --ignore-times --checksum --server-side-across-configs
rclone check "$IMMUTABLE" "$LATEST" --checksum --one-way

curl -fsSL "${PUBLIC_BASE}/${PREFIX}/latest/latest-mac.yml" | grep -qx "version: ${VERSION}"
curl -fsSL "${PUBLIC_BASE}/${PREFIX}/latest/latest.yml" | grep -qx "version: ${VERSION}"
curl -fsSL "${PUBLIC_BASE}/${PREFIX}/latest/index.html" | grep -q "Mosael ${VERSION}"
curl -fsI "${PUBLIC_BASE}/${PREFIX}/${TAG}/SHA256SUMS" | head -1 | grep -q '200'

echo "R2 published: ${IMMUTABLE} + ${LATEST}"
