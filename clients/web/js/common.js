// Shared helpers for the talk page and the family dashboard.

export async function api(path, options = {}) {
  const res = await fetch(path, options);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const msg = (body && (body.error || body.detail)) || `Request failed (${res.status})`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return body;
}

// Status is always a coloured dot plus a word, never colour alone.
export const STATUS_LABEL = {
  ok: 'Seems OK',
  low: 'Seems low',
  masked: 'Said fine, seemed low',
  urgent: 'Urgent',
  none: 'No conversation',
};

export function status(kind, label) {
  const wrap = el('span', 'status');
  const dot = el('span', `dot ${kind || 'none'}`);
  dot.setAttribute('aria-hidden', 'true');
  wrap.append(dot, document.createTextNode(label || STATUS_LABEL[kind] || STATUS_LABEL.none));
  return wrap;
}

export function signed(v, digits = 2) {
  if (v === null || v === undefined) return '–';
  return (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(digits);
}

export function verbalWord(v) {
  if (v >= 0.1) return 'positive';
  if (v <= -0.2) return 'negative';
  return 'neutral';
}

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function storageGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch { return fallback; }
}
export function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}
