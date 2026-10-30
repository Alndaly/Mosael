#!/usr/bin/env node
/** 把完整发布目录同步到 R2:latest/ 放当前版本产物,v<tag>/ 放不可变的版本副本。 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, resolve } from "node:path";
import { argv, exit } from "node:process";
import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CreateMultipartUploadCommand,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
  UploadPartCommand,
} from "@aws-sdk/client-s3";
import { renderDownloadPage } from "./r2-download-page.mjs";

const CONTENT_TYPES = new Map([
  [".yml", "text/yaml"],
  [".json", "application/json"],
  [".html", "text/html; charset=utf-8"],
  [".zip", "application/zip"],
  [".dmg", "application/x-apple-diskimage"],
  [".exe", "application/vnd.microsoft.portable-executable"],
]);

function args() {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    if (key === "--dry-run") {
      out.dryRun = true;
      continue;
    }
    out[key.slice(2)] = argv[i + 1];
    i += 1;
  }
  return out;
}

const options = args();
if (!options.dist || !/^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(options.tag || "")) {
  console.error("usage: node scripts/publish-r2.mjs --dist dist/VERSION --tag vVERSION [--dry-run]");
  exit(2);
}
const dist = resolve(options.dist);
const files = existsSync(dist)
  ? readdirSync(dist).filter((name) => name !== "index.html" && statSync(resolve(dist, name)).isFile())
  : [];
if (files.length === 0) {
  console.error(`no release files found: ${dist}`);
  exit(1);
}
const prefix = (process.env.R2_PREFIX || "mosael").replace(/^\/+|\/+$/g, "");
const keyFor = (name, latest) => `${prefix ? `${prefix}/` : ""}${latest ? "latest" : options.tag}/${name}`;
const downloadPage = renderDownloadPage(files, options.tag);
//: Cloudflare 的单次 PutObject 上限是 300 MB;DMG/ZIP 都超过它。超过阈值走 S3 分段上传,
//: 否则大文件会卡在连接上,既不报错也传不完。
const MULTIPART_THRESHOLD = Number(process.env.R2_MULTIPART_THRESHOLD || 250 * 1024 * 1024);
const PART_SIZE = Math.max(5 * 1024 * 1024, Number(process.env.R2_MULTIPART_PART_SIZE || 64 * 1024 * 1024));
const plans = [];
// 不可变目录是发布的第一阶段:其中任何一个对象上传或回读失败,都不会碰到 latest。
for (const latest of [false, true]) {
  for (const name of files) {
    const file = resolve(dist, name);
    plans.push({
      file,
      size: statSync(file).size,
      contentType: CONTENT_TYPES.get(basename(name).slice(name.lastIndexOf("."))) || "application/octet-stream",
      key: keyFor(name, latest),
      cacheControl: latest ? "public,max-age=0,must-revalidate" : "public,max-age=31536000,immutable",
    });
  }
  plans.push({
    body: Buffer.from(downloadPage),
    size: Buffer.byteLength(downloadPage),
    contentType: CONTENT_TYPES.get(".html"),
    key: keyFor("index.html", latest),
    cacheControl: latest ? "public,max-age=0,must-revalidate" : "public,max-age=31536000,immutable",
  });
}

if (options.dryRun) {
  for (const { body: _body, ...plan } of plans) console.log(JSON.stringify(plan));
} else {
  const accountId = process.env.R2_ACCOUNT_ID || "";
  const endpoint = process.env.R2_ENDPOINT || (accountId ? `https://${accountId}.r2.cloudflarestorage.com` : "");
  const bucket = process.env.R2_BUCKET || "";
  const accessKeyId = process.env.R2_ACCESS_KEY_ID || "";
  const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY || "";
  if (!endpoint || !bucket || !accessKeyId || !secretAccessKey) {
    exit(1);
  }
  const client = new S3Client({ region: "auto", endpoint, credentials: { accessKeyId, secretAccessKey } });
  const put = async (plan, body) => {
    if (body.length < MULTIPART_THRESHOLD) {
      await client.send(new PutObjectCommand({
        Bucket: bucket,
        Key: plan.key,
        Body: body,
        ContentLength: body.length,
        ContentType: plan.contentType,
        CacheControl: plan.cacheControl,
      }));
      return;
    }
    const created = await client.send(new CreateMultipartUploadCommand({
      Bucket: bucket,
      Key: plan.key,
      ContentType: plan.contentType,
      CacheControl: plan.cacheControl,
    }));
    if (!created.UploadId) throw new Error(`R2 multipart upload id missing: ${plan.key}`);
    const parts = [];
    try {
      for (let offset = 0, partNumber = 1; offset < body.length; offset += PART_SIZE, partNumber += 1) {
        const part = body.subarray(offset, Math.min(offset + PART_SIZE, body.length));
        const uploaded = await client.send(new UploadPartCommand({
          Bucket: bucket,
          Key: plan.key,
          UploadId: created.UploadId,
          PartNumber: partNumber,
          Body: part,
          ContentLength: part.length,
        }));
        if (!uploaded.ETag) throw new Error(`R2 multipart part ETag missing: ${plan.key}#${partNumber}`);
        parts.push({ ETag: uploaded.ETag, PartNumber: partNumber });
      }
      await client.send(new CompleteMultipartUploadCommand({
        Bucket: bucket,
        Key: plan.key,
        UploadId: created.UploadId,
        MultipartUpload: { Parts: parts },
      }));
    } catch (error) {
      await client.send(new AbortMultipartUploadCommand({
        Bucket: bucket,
        Key: plan.key,
        UploadId: created.UploadId,
      })).catch(() => undefined);
      throw error;
    }
  };
  for (const plan of plans) {
    const body = plan.body ?? readFileSync(plan.file);
    const localSha = createHash("sha256").update(body).digest("hex");
    await put(plan, body);
    const head = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: plan.key }));
    if (Number(head.ContentLength) !== body.length) throw new Error(`R2 size mismatch: ${plan.key}`);
    const remote = await client.send(new GetObjectCommand({ Bucket: bucket, Key: plan.key }));
    const hash = createHash("sha256");
    for await (const chunk of remote.Body) hash.update(chunk);
    if (hash.digest("hex") !== localSha) throw new Error(`R2 sha256 mismatch: ${plan.key}`);
    console.log(`verified r2://${bucket}/${plan.key} (${body.length} bytes)`);
  }
}
