/* Content consistency relative to selected manifest; no publisher authentication. */
const LIMIT = 8 * 1024 * 1024;
const decoder = new TextDecoder('utf-8', {fatal: true});
function insist(ok, message) { if (!ok) throw new Error(message); }
export function strictJSON(text) {
  let at = 0;
  const whitespace = () => { while (/[\x20\x09\x0a\x0d]/.test(text[at] || '\0')) at++; };
  function string() {
    const start = at++; let escaped = false;
    while (at < text.length) {
      const c = text[at++];
      if (c === '"' && !escaped) return JSON.parse(text.slice(start, at));
      if (c === '\\' && !escaped) escaped = true; else escaped = false;
    }
    throw new Error('Unterminated JSON string.');
  }
  function value(depth = 0) {
    insist(depth < 256, 'JSON nesting is unsupported.'); whitespace();
    if (text[at] === '"') return string();
    if (text[at] === '{' || text[at] === '[') {
      const object = text[at++] === '{'; const result = object ? Object.create(null) : []; const seen = new Set(); whitespace();
      const end = object ? '}' : ']'; if (text[at] === end) { at++; return result; }
      while (at < text.length) {
        if (object) {
          insist(text[at] === '"', 'Expected a JSON key.'); const key = string(); whitespace();
          insist(!seen.has(key), 'Duplicate JSON key: ' + key); seen.add(key);
          insist(text[at++] === ':', 'Expected a JSON colon.'); result[key] = value(depth + 1);
        } else result.push(value(depth + 1));
        whitespace(); if (text[at] === end) { at++; return result; }
        insist(text[at++] === ',', 'Expected a JSON separator.'); whitespace();
      }
      throw new Error('Incomplete JSON container.');
    }
    for (const [token, result] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(token, at)) { at += token.length; return result; }
    }
    const token = text.slice(at).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    insist(token, 'Invalid JSON value.'); at += token[0].length;
    const number = Number(token[0]);
    insist(Number.isSafeInteger(number) && String(number) === token[0], 'Numeric representation unsupported by browser verification; use the CLI verifier.');
    return number;
  }
  const result = value(); whitespace(); insist(at === text.length, 'Trailing JSON content.'); return result;
}
export async function sha256(raw) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(v => v.toString(16).padStart(2, '0')).join('');
}
async function read(name, optional = false) {
  const response = await fetch('./handoff/' + name, {credentials: 'omit', cache: 'no-store'});
  if (optional && response.status === 404) return null;
  insist(response.ok, 'Handoff file unavailable: ' + name);
  const reader = response.body.getReader(); const chunks = []; let bytes = 0;
  try {
    while (true) {
      const {done, value} = await reader.read(); if (done) break; bytes += value.length;
      insist(bytes <= LIMIT, 'Handoff file exceeds the supported byte limit: ' + name); chunks.push(value);
    }
  } finally { await reader.cancel(); reader.releaseLock(); }
  const raw = new Uint8Array(bytes); let offset = 0;
  for (const chunk of chunks) { raw.set(chunk, offset); offset += chunk.length; }
  return raw;
}
function equal(a, b) {
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return a === b;
  const keys = Object.keys(a); return Array.isArray(a) === Array.isArray(b) && keys.length === Object.keys(b).length && keys.every(k => Object.hasOwn(b, k) && equal(a[k], b[k]));
}
export async function loadVerifiedHandoff() {
  const raw = await read('handoff.json', true); if (raw === null) return null;
  const manifestRaw = await read('manifest.json'); const manifest = strictJSON(decoder.decode(manifestRaw));
  const artifactsRaw = await read('artifacts.json');
  insist(manifest && Object.keys(manifest.files || {}).sort().join(',') === 'artifacts.json,handoff.json', 'Invalid handoff manifest file set.');
  for (const [name, content] of [['handoff.json', raw], ['artifacts.json', artifactsRaw]]) {
    const expected = manifest.files[name];
    insist(expected && expected.bytes === content.length && expected.sha256 === await sha256(content), 'Handoff manifest content mismatch: ' + name);
  }
  const record = strictJSON(decoder.decode(raw)); const encoded = strictJSON(decoder.decode(artifactsRaw));
  insist(['swe-workbench-handoff/v1', 'swe-workbench-handoff/v2'].includes(record.schema) && manifest.schema === record.schema, 'Unsupported handoff schema.');
  insist(record.state && record.material && Array.isArray(record.events) && record.events.length > 0, 'Incomplete handoff state/history.');
  insist(manifest.change_id === record.state.change_id && manifest.revision === record.state.revision, 'Manifest state mismatch.');
  insist(record.workbench_executions === 0 && record.keep_mutations === 0, 'Unsupported execution claim.');
  const decoded = new Map();
  for (const [key, value] of Object.entries(encoded)) {
    insist(/^[a-f0-9]{64}$/.test(key) && typeof value === 'string', 'Invalid artifact reference.');
    const bytes = Uint8Array.from(atob(value), c => c.charCodeAt(0));
    insist(await sha256(bytes) === key, 'Historical artifact identity mismatch.');
    decoded.set(key, strictJSON(decoder.decode(bytes)));
  }
  const references = new Set();
  for (const [i, event] of record.events.entries()) {
    const p = event.payload; insist(p && p.revision === i && p.change_id === record.state.change_id, 'Handoff event association mismatch.');
    for (const k of ['state_digest', 'material_digest']) { insist(decoded.has(p[k]), 'Missing referenced artifact.'); references.add(p[k]); }
    const state = decoded.get(p.state_digest);
    insist(state.material_digest === p.material_digest && state.revision === p.revision && state.change_id === p.change_id, 'Historical state association mismatch.');
  }
  insist(references.size === decoded.size, 'Unreferenced handoff artifacts.');
  const last = record.events.at(-1).payload;
  insist(equal(record.state, decoded.get(last.state_digest)) && equal(record.material, decoded.get(last.material_digest)), 'Current handoff differs from retained artifacts.');
  Object.defineProperty(record, '_verifiedArtifacts', {value: encoded}); return record;
}
