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
