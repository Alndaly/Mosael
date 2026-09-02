import { fetchPlatformResource } from "./platform-resource";
import type { PlatformResourceRequest } from "./shared/protocol";

void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

chrome.runtime.onInstalled.addListener(() => {
  void chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  void chrome.runtime.sendMessage({ type: "ACTIVE_TAB_CHANGED", tabId }).catch(() => undefined);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url || changeInfo.status === "complete") {
    void chrome.runtime.sendMessage({ type: "ACTIVE_TAB_CHANGED", tabId }).catch(() => undefined);
  }
});

chrome.runtime.onMessage.addListener((message: PlatformResourceRequest, _sender, sendResponse) => {
  if (message?.type !== "FETCH_PLATFORM_RESOURCE") return false;
  void fetchPlatformResource(message.url).then(sendResponse);
  return true;
});
