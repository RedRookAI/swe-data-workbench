/* Content consistency relative to selected manifest; no publisher authentication. */
const LIMIT = 8 * 1024 * 1024;
const decoder = new TextDecoder('utf-8', {fatal: true});
function insist(ok, message) { if (!ok) throw new Error(message); }
export class ExactJSONNumber {
  constructor(token) { this.token=token;Object.freeze(this); }
  toString() { return this.token; }
}
function numericKey(token) {
  const kind=/[.eE]/.test(token)?'decimal':'integer';
  const m=token.match(/^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/);
  let digits=(m[2]+(m[3]||'')).replace(/^0+/,'');
  let exponent=BigInt(m[4]||'0')-BigInt((m[3]||'').length);
  while(digits.endsWith('0') && digits.length){digits=digits.slice(0,-1);exponent++;}
  if(!digits)return kind+':'+(kind==='decimal'?m[1]:'')+'0';
  return kind+':'+m[1]+digits+'e'+exponent;
}
export function displayJSON(value, depth=0) {
  if(value instanceof ExactJSONNumber)return value.token;
  if(value===null || typeof value!=='object')return JSON.stringify(value);
  const pad='  '.repeat(depth),next=pad+'  ';
  if(Array.isArray(value))return value.length?'[\n'+value.map(v=>next+displayJSON(v,depth+1)).join(',\n')+'\n'+pad+']':'[]';
  const entries=Object.entries(value);return entries.length?'{\n'+entries.map(([k,v])=>next+JSON.stringify(k)+': '+displayJSON(v,depth+1)).join(',\n')+'\n'+pad+'}':'{}';
}
export function exactEqual(a,b) {
  if(a instanceof ExactJSONNumber || b instanceof ExactJSONNumber){
    if(!(a instanceof ExactJSONNumber) || !(b instanceof ExactJSONNumber))return false;
    return numericKey(a.token)===numericKey(b.token);
  }
  if(a===null || b===null || typeof a!=='object' || typeof b!=='object')return a===b;
  const keys=Object.keys(a);return Array.isArray(a)===Array.isArray(b) && keys.length===Object.keys(b).length && keys.every(k=>Object.hasOwn(b,k)&&exactEqual(a[k],b[k]));
}
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
    const number=Number(token[0]);
    insist(Number.isFinite(number), 'Nonfinite numeric interpretation is unsupported.');
    return Number.isSafeInteger(number) && String(number)===token[0] ? number : new ExactJSONNumber(token[0]);
  }
  const result = value(); whitespace(); insist(at === text.length, 'Trailing JSON content.'); return result;
}
export async function sha256(raw) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(v => v.toString(16).padStart(2, '0')).join('');
}
async function read(name, optional = false, base='./handoff/') {
  const response = await fetch(base+name, {credentials:'omit',cache:'no-store',redirect:'error'});
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
export async function loadVerifiedHandoff(base='./handoff/') {
  insist(base==='./handoff/' || /^\.\/change-[a-f0-9]{20}\/handoff\/$/.test(base),'Unsupported selected package path.');
  const raw = await read('handoff.json',true,base); if (raw === null) return null;
  const manifestRaw = await read('manifest.json',false,base); const manifest = strictJSON(decoder.decode(manifestRaw));
  const artifactsRaw = await read('artifacts.json',false,base);
  insist(manifest && Object.keys(manifest.files || {}).sort().join(',') === 'artifacts.json,handoff.json', 'Invalid handoff manifest file set.');
  for (const [name, content] of [['handoff.json', raw], ['artifacts.json', artifactsRaw]]) {
    const expected = manifest.files[name];
    insist(expected && expected.bytes === content.length && expected.sha256 === await sha256(content), 'Handoff manifest content mismatch: ' + name);
  }
  const record = strictJSON(decoder.decode(raw)); const encoded = strictJSON(decoder.decode(artifactsRaw));
  insist(['swe-workbench-handoff/v1', 'swe-workbench-handoff/v2','swe-workbench-handoff/v3','swe-workbench-handoff/v4'].includes(record.schema) && manifest.schema === record.schema, 'Unsupported handoff schema.');
  insist(record.state && record.material && Array.isArray(record.events) && record.events.length > 0, 'Incomplete handoff state/history.');
  insist(manifest.change_id === record.state.change_id && manifest.revision === record.state.revision, 'Manifest state mismatch.');
  insist(record.workbench_executions === 0 && record.keep_mutations === 0, 'Unsupported execution claim.');
  const decoded = new Map();const rawArtifacts=new Map();const sourceContents=new Map();
  for (const [key, value] of Object.entries(encoded)) {
    insist(/^[a-f0-9]{64}$/.test(key) && typeof value === 'string', 'Invalid artifact reference.');
    const bytes = Uint8Array.from(atob(value), c => c.charCodeAt(0));
    insist(await sha256(bytes) === key, 'Historical artifact identity mismatch.');
    rawArtifacts.set(key,bytes);
  }
  const references = new Set();
  for (const [i, event] of record.events.entries()) {
    const p = event.payload; insist(p && p.revision === i && p.change_id === record.state.change_id, 'Handoff event association mismatch.');
    for (const k of ['state_digest', 'material_digest']) { insist(rawArtifacts.has(p[k]), 'Missing referenced artifact.');references.add(p[k]);if(!decoded.has(p[k]))decoded.set(p[k],strictJSON(decoder.decode(rawArtifacts.get(p[k])))); }
    const material=decoded.get(p.material_digest);
    if(['swe-workbench-handoff/v3','swe-workbench-handoff/v4'].includes(material.schema)){
      for(const file of material.files){for(const phase of [file.before,file.after]){
        if(phase?.coverage==='text'){
          insist(rawArtifacts.has(phase.content_digest),'Missing source artifact.');const raw=rawArtifacts.get(phase.content_digest);
          insist(raw.length===phase.bytes,'Source artifact byte count mismatch.');references.add(phase.content_digest);sourceContents.set(phase.content_digest,decoder.decode(raw));
        }
      }}
    }
    const state = decoded.get(p.state_digest);
    insist(state.material_digest === p.material_digest && state.revision === p.revision && state.change_id === p.change_id, 'Historical state association mismatch.');
  }
  insist(references.size === rawArtifacts.size, 'Unreferenced handoff artifacts.');
  if(record.material.schema==='swe-workbench-handoff/v4')for(const observation of record.material.observations){insist(observation.value_format==='swe-workbench-exact-json/v1','Missing exact observation contract.');displayExact(observation.value);}
  const last = record.events.at(-1).payload;
  insist(exactEqual(record.state, decoded.get(last.state_digest)) && exactEqual(record.material, decoded.get(last.material_digest)), 'Current handoff differs from retained artifacts.');
  Object.defineProperty(record, '_verifiedArtifacts', {value: encoded});Object.defineProperty(record,'_sourceContents',{value:sourceContents}); return record;
}

export function displayExact(value) {
  if(value===null)return 'Unavailable';
  if(value.type==='null')return 'null';
  if(value.type==='number') {insist(typeof value.token==='string' && value.token.length<=4300 && /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(value.token),'Invalid exact number token.');return value.token;}
  if(value.type==='boolean'){insist(typeof value.value==='boolean','Invalid exact boolean.');return String(value.value);}
  if(value.type==='string'){insist(typeof value.value==='string','Invalid exact string.');return JSON.stringify(value.value);}
  if(value.type==='array')return '['+value.items.map(displayExact).join(', ')+']';
  if(value.type==='object')return '{'+Object.entries(value.members).map(([k,v])=>JSON.stringify(k)+': '+displayExact(v)).join(', ')+'}';
  throw new Error('Unsupported exact observation.');
}

export function attentionFromRecord(record) {
  const s=record.state,m=record.material,reports=m.reported_checks||[];
  const current=reports.filter(r=>r.binding!=='declared-base-source');
  const bad=current.some(r=>r.status!=='reported'||r.binding!=='declared-same-source'||r.warnings?.length||!['passed','failed','error'].some(k=>r.counts?.[k]>0)||['failed','error','unavailable'].some(k=>r.counts?.[k]>0))||(reports.length>0&&current.length===0);
  const unknowns=m.observations.filter(o=>o.required&&(o.value===null||(o.candidate_applicability??(o.binding==='declared-same-source'?'declared':'unknown'))!=='declared')).map(o=>o.label+': missing or unbound candidate evidence');
  for(const r of reports) {
    let original;try{original=strictJSON(m.attachments.find(a=>a.name===r.attachment)?.text||'null');}catch{}
    if(r.status==='reported'&&original?.schema==='swe-workbench-junit-report/v1'&&r.definition_sha256===null)unknowns.push(r.attachment+': check definition was not supplied');
  }
  return {change_id:s.change_id,title:m.title,goal:m.goal,revision:s.revision,material_digest:s.material_digest,decision:s.decision,needs_attention:s.decision!=='handoff-ready'||s.findings.length>0||bad||unknowns.length>0,responsible_party:s.responsible_party??null,next_action:s.next_action,findings:s.findings,reports,unknowns,candidate_revision:m.candidate_revision,source_scope:{files:m.files.length,text:m.coverage?.text_paths.length??m.files.length,metadata_only:m.coverage?.metadata_only_paths.length??0}};
}
