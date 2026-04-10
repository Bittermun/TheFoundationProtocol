const TFP_NODE_BASE = "http://127.0.0.1:8000";

function targetForTfpUrl(rawUrl) {
  try {
    const withoutScheme = rawUrl.replace(/^tfp:\/\//, "");
    const [pathPart] = withoutScheme.split("?");
    if (pathPart.startsWith("tag/")) {
      const parts = pathPart.split("/");
      const tag = parts[1] || "";
      return `${TFP_NODE_BASE}/api/content?tag=${encodeURIComponent(tag)}`;
    }
    const rootHash = pathPart;
    return `${TFP_NODE_BASE}/api/get/${encodeURIComponent(rootHash)}?device_id=browser-extension`;
  } catch (err) {
    return null;
  }
}

chrome.webNavigation.onBeforeNavigate.addListener(async (details) => {
  if (!details.url.startsWith("tfp://")) return;
  const target = targetForTfpUrl(details.url);
  if (!target) return;
  await chrome.tabs.update(details.tabId, { url: target });
});
