export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

export function safeHttpUrl(value, fallback = "") {
  try {
    const url = new URL(String(value), window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : fallback;
  } catch {
    return fallback;
  }
}
