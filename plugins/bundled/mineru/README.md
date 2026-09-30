# MinerU document parsing

Sends PDF, Word, PowerPoint, Excel and image files to [MinerU](https://mineru.net) to be parsed into Markdown: layout
analysis, OCR, and table and formula recognition. For scans, image-only PDFs, multi-column layouts, and documents with
formulas and complex tables, it does far better than Mosael's built-in local parsing.

## How to use it

1. Create an API token under API management on mineru.net.
2. On Mosael's Plugins page, enable MinerU and enter the token. You can choose the model (VLM recommended), the document
   language, and whether to force OCR.
3. Ways to use it:
   - **For one document**: open the asset details and choose "Parse again" → "Parse with MinerU";
   - **As the default from now on**: pick MinerU under "Settings → Capability providers → Document parsing", and
     "Parse again" uses it by default;
   - **For the agent and workflows**: the "Parse a document with MinerU" tool on the Plugins page is enabled by default,
     so the agent can call it directly and workflows have a node of the same name; give it a document and the result is
     saved as a parse of that document.

When a document is imported, Mosael always parses it locally first (nothing leaves your machine and it costs nothing);
sending it to MinerU only happens when you ask for it explicitly, because the document is uploaded to MinerU.

## Network (read this if you're abroad or running a global proxy)

MinerU only serves the mainland China region. On the Plugins page this connection has a "Network" setting (Mosael gives
every plugin connection one):

- **Follow Mosael** (default): the same as Mosael's own outbound traffic: it uses the outbound proxy if one is set in
  Settings, otherwise the system proxy;
- **Direct (no proxy)**: choose this when you're in mainland China but Mosael or the system has a proxy on that sends
  traffic abroad;
- **Use a proxy**: choose this when you're abroad, and enter an HTTP proxy into mainland China, e.g.
  `http://127.0.0.1:7890` (this plugin does not support SOCKS).

When an upload or call is refused (403) or can't connect, the error message points to this setting.

## What it produces

- Markdown marked page by page: headings, paragraphs, lists, formulas (LaTeX), tables (converted to Markdown tables) and
  figures;
- The page image for each page is rendered by Mosael itself from the original (always for PDF; Word / PowerPoint need
  LibreOffice installed on this machine).

When the agent reads the document, it reads this MinerU parse (when a document has several parses, the latest
successful one is used).

## Limits

- Up to 200 MB and 200 pages per file; the free tier has a daily page quota (see mineru.net for the current numbers).
- It currently uses MinerU's cloud API. A self-hosted MinerU service (`mineru-kit api-server`) isn't supported yet.
