export const community = {
  // ---- i18n 分区 F4(社区,ADR 0026):这一批新加的 key 放在这行下面 ----
  // Community share "Open in Mosael": preview, then import (deep link mosael://import?share=…).
  shareImportTitle: "Import a community share",
  shareImportLoading: "Reading the share…",
  shareImportAuthor: "By",
  shareImportKind: "Type",
  shareImportSize: "Size",
  shareImportKindWorkflow: "Workflow",
  shareImportKindBoard: "Board",
  shareImportDownloads: "Downloaded {n} times",
  shareImportConfirm: "Import into workspace",
  shareImportImporting: "Importing…",
  shareImportFailed: "Couldn't read the share",
  shareImportNotFound: "This share doesn't exist or has been removed.",
  shareImportNotFoundFix: "Check that the link is complete, or find the share again in the community.",
  shareImportOffline: "Can't reach MosaelCloud.",
  shareImportOfflineFix: "Check your network or proxy, then try again.",
  shareImportInvalid: "This content isn't a usable workflow share.",
  shareImportInvalidFix: "Make sure the link is for a workflow share. Board shares can't be imported automatically yet — download the file from the website instead.",
  shareImportOtherFix: "Try again later; if it keeps failing, download the file from the website and import it from the workflows page.",
  shareImportBoardUnsupported: "Board shares can't be imported automatically yet. Download the file from the website, then import it on the boards page.",
  shareImportDone: "Imported “{name}”.",
} as const;
