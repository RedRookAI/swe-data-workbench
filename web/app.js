/* Static is the default. Live mode is an explicit owner action on the private API.
   Imported strings enter the DOM only through textContent, never HTML or URLs. */
const $ = (id) => document.getElementById(id);
const live = new URLSearchParams(location.search).get('mode') === 'live';
const criteria = ['task_clarity', 'evidence_adequacy', 'requested_behavior', 'preserved_behavior', 'unsupported_claims'];
const labels = {task_clarity: 'Task clarity', evidence_adequacy: 'Evidence adequacy', requested_behavior: 'Requested behavior', preserved_behavior: 'Preserved behavior', unsupported_claims: 'Unsupported claims'};
const state = {token: '', batch: null, items: [], selected: null, audit: [], snapshot: null, busy: false};
const retries = new Map();
function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined && text !== null) n.textContent = String(text);
  if (cls) n.className = cls;
  return n;
}
function badge(text) { return node('span', text || 'unavailable', 'badge ' + (/^(passed|accepted|completed)$/.test(text) ? 'success' : /^(failed|rejected|error|timeout|execution-error)$/.test(text) ? 'error' : '')); }
function display(value) { return value === undefined || value === null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value); }
function notify(text, failure = false) { $('message').textContent = text; $('message').className = failure ? 'notice error' : 'notice'; $('message').hidden = false; }
function hideMessage() { $('message').hidden = true; }
function appendField(parent, title, value) { const section = node('section'); section.append(node('h3', title), node('pre', display(value))); parent.append(section); }
function short(value) { return value ? String(value).slice(0, 14) + '…' : 'unavailable'; }
function current() { return state.items.find((item) => item.id === state.selected); }
async function request(path, body) {
  if (!live || !state.token) throw new Error('Connect to the private owner instance first.');
  const headers = {Authorization: 'Bearer ' + state.token};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'omit', redirect: 'error'});
  const data = await response.json();
  if (!response.ok) throw new Error((data.error?.code || response.status) + ': ' + (data.error?.message || 'Request failed.'));
  return data;
}
function op(key, payload = {}) {
  const signature = key + ':' + JSON.stringify(payload);
  if (!retries.has(signature)) retries.set(signature, crypto.randomUUID());
  return {signature, body: {...payload, operation_key: retries.get(signature)}};
}
async function mutation(path, payload, key, after) {
  if (state.busy) return;
  hideMessage(); state.busy = true; syncActions();
  const operation = key ? op(key, payload) : {body: payload};
  try {
    const result = await request(path, operation.body);
    if (operation.signature) retries.delete(operation.signature);
    if (after) await after(result);
    return result;
  } catch (e) { notify(e.message + ' Your evidence view remains unchanged; refresh to inspect current state before retrying a conflict.', true); }
  finally { state.busy = false; syncActions(); }
}
function syncActions() {
  for (const id of ['import', 'process', 'export', 'refresh']) $(id).disabled = state.busy || !state.token || (id !== 'import' && !state.batch);
  const submit = $('submit-review');
  if (submit) submit.disabled = state.busy || !state.token;
  $('process').textContent = state.busy ? 'Operation in progress…' : 'Run checks · 1 worker';
}
function showBatchOptions(batches) {
  $('batch-select').replaceChildren();
  for (const batch of batches) { const option = node('option', 'Batch ' + short(batch.id)); option.value = batch.id; $('batch-select').append(option); }
  if (state.batch) $('batch-select').value = state.batch.id;
  $('batch-select').disabled = !live || !batches.length;
}
async function loadLive(batchId) {
  const batches = await request('/api/batches');
  const id = batchId || state.batch?.id || batches[0]?.id;
  if (!id) { state.batch = null; state.items = []; state.audit = []; showBatchOptions([]); render(); return; }
  const encoded = encodeURIComponent(id);
  const [batch, items, audit] = await Promise.all([request('/api/batches/' + encoded), request('/api/batches/' + encoded + '/submissions'), request('/api/batches/' + encoded + '/audit')]);
  state.batch = batch;
  // The interface permits summary rows here, so fetch full detail on selection.
  state.items = items; state.audit = audit;
  state.selected = items.some((x) => x.id === state.selected) ? state.selected : items[0]?.id;
  if (state.selected) {
    const detail = await request('/api/submissions/' + encodeURIComponent(state.selected));
    state.items = items.map((item) => item.id === detail.id ? detail : item);
  }
  showBatchOptions(batches); render();
}
async function selectItem(id) {
  try {
    if (live) {
      const item = await request('/api/submissions/' + encodeURIComponent(id));
      state.items = state.items.map((old) => old.id === id ? item : old);
    }
    state.selected = id; renderQueue(); renderInspector();
  } catch (e) { notify(e.message, true); }
}
function renderMetrics() {
  const batch = state.batch;
  const counts = batch?.counts || {};
  const facts = [['Input lines', batch?.raw_lines, 'Raw records received'], ['Unique submissions', batch?.unique_items, (batch?.duplicate_lines ?? '—') + ' duplicate · ' + (batch?.invalid_lines ?? '—') + ' invalid'], ['Completed checks', counts.completed, 'Execution status'], ['Accepted', batch ? (counts.accepted ?? state.items.filter((x) => x.disposition === 'accepted').length) : undefined, 'Developer adjudication']];
  $('metrics').replaceChildren(...facts.map(([label, value, note]) => { const block = node('div', null, 'metric'); block.append(node('span', label, 'small muted'), node('strong', value ?? '—'), node('span', note, 'small muted')); return block; }));
  $('batch-meta').textContent = batch ? 'Recorded source: ' + (batch.created_at || 'time unavailable') + ' · ' + short(batch.id) : live ? 'Import the trusted sample to begin.' : 'No recorded snapshot available.';
}
function renderIntake() {
  const root = $('intake-records'); root.replaceChildren();
  if (!state.batch) { root.append(node('p', 'No intake evidence available.', 'muted')); return; }
  const batch = state.batch;
  root.append(node('p', batch.raw_lines + ' raw lines = ' + batch.invalid_lines + ' invalid + ' + batch.duplicate_lines + ' duplicate + ' + batch.unique_items + ' unique memberships.'));
  if (batch.invalid_records?.length) appendField(root, 'Quarantined records', batch.invalid_records);
  else root.append(node('p', batch.invalid_lines ? 'Individual validation details are unavailable in this snapshot.' : 'No invalid records in this batch.', 'muted'));
  if (batch.occurrences?.length) appendField(root, 'Input occurrences and duplicate relations', batch.occurrences);
}
function renderExportMetrics(metrics) {
  const root = $('recorded-metrics'); root.replaceChildren();
  const blocks = node('div', null, 'metrics');
  for (const [key, label] of [['accepted_yield', 'Accepted yield'], ['send_back_rate', 'Send-back rate'], ['machine_throughput', 'Machine throughput'], ['review_throughput', 'Review throughput']]) {
    const metric = metrics[key];
    const block = node('div', null, 'metric');
    const value = metric?.value;
    const rate = key.endsWith('yield') || key.endsWith('rate');
    block.append(node('span', label, 'small muted'), node('strong', value === undefined || value === null ? 'Unavailable' : rate ? (value * 100).toFixed(1) + '%' : value.toFixed(2) + '/s'));
    block.append(node('span', value === undefined || value === null ? metric?.unavailable_reason || 'Not recorded in this manifest.' : rate ? metric.numerator + ' / ' + metric.denominator + ' · ' + (metrics.denominators?.[key] || '') : metric.numerator + ' unique measurements / ' + metric.elapsed_seconds.toFixed(3) + ' seconds', 'small muted'));
    blocks.append(block);
  }
  const details = node('details'); details.append(node('summary', 'Complete metrics and denominators'), node('pre', JSON.stringify(metrics, null, 2))); root.append(blocks, details);
}
function renderQueue() {
  const list = $('item-list'); list.replaceChildren();
  const filter = $('filter').value;
  const items = state.items.filter((item) => filter === 'all' || item.disposition === filter);
  $('queue-count').textContent = items.length + ' of ' + state.items.length;
  if (!items.length) list.append(node('p', 'No submissions in this view.', 'empty'));
  for (const item of items) {
    const button = node('button', null, 'submission' + (item.id === state.selected ? ' selected' : ''));
    button.type = 'button'; button.setAttribute('aria-pressed', String(item.id === state.selected));
    button.append(node('span', item.task_id || short(item.id), 'eyebrow'), node('strong', item.title || 'Untitled submission'));
    button.append(node('span', short(item.id), 'small muted'));
    const statuses = node('span', null, 'submission-status'); statuses.append(badge(item.execution_status), badge(item.disposition)); button.append(statuses);
    button.addEventListener('click', () => selectItem(item.id)); list.append(button);
  }
}
function renderInspector() {
  const root = $('inspector'); root.replaceChildren();
  const item = current();
  if (!item) { root.append(node('p', 'Select a submission to inspect its evidence.', 'empty')); return; }
  const head = node('header', null, 'inspector-header');
  head.append(node('p', item.task_id || 'SUBMISSION', 'eyebrow'), node('h2', item.title || 'Untitled submission'));
  const statuses = node('div', null, 'actions'); statuses.append(badge(item.execution_status), badge(item.result?.overall || 'no machine evidence'), badge(item.disposition));
  head.append(statuses, node('p', 'Revision ' + item.revision + ' · ' + (item.origin || 'origin unavailable'), 'small muted')); root.append(head);
  if (item.context_current === false) root.append(node('p', 'Context changed. This earlier evidence and adjudication are historical; import the current context and obtain new evidence before acceptance.', 'notice'));
  const tabs = node('div', null, 'tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Submission details');
  const panels = [];
  for (const [name, title] of [['task', 'Task & patch'], ['evidence', 'Machine evidence'], ['review', 'Adjudication'], ['provenance', 'Provenance']]) {
    const button = node('button', title); button.type = 'button'; button.id = 'tab-' + name; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', 'panel-' + name); button.setAttribute('aria-selected', String(name === 'task')); button.tabIndex = name === 'task' ? 0 : -1;
    const panel = node('div', null, 'tab-panel'); panel.id = 'panel-' + name; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', button.id); panel.tabIndex = 0; panel.hidden = name !== 'task';
    button.addEventListener('click', () => { for (const [b, p] of panels) { const chosen = b === button; b.setAttribute('aria-selected', String(chosen)); b.tabIndex = chosen ? 0 : -1; p.hidden = !chosen; } });
    button.addEventListener('keydown', (event) => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); const index = panels.findIndex(([b]) => b === button); const next = event.key === 'Home' ? 0 : event.key === 'End' ? panels.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + panels.length) % panels.length; panels[next][0].click(); panels[next][0].focus(); });
    panels.push([button, panel]); tabs.append(button);
  }
  root.append(tabs, ...panels.map(([, panel]) => panel));
  const task = panels[0][1];
  task.append(node('h3', 'Requested behavior'), node('pre', item.task_text || 'Task text unavailable.'), node('h3', 'Exact submitted patch'));
  const patch = node('pre', null, 'diff');
  for (const line of (item.patch || 'No patch supplied.').split('\n')) { patch.append(node('span', line, 'diff-line ' + (line.startsWith('+') ? 'add' : line.startsWith('-') ? 'remove' : ''))); }
  task.append(patch);
  renderEvidence(panels[1][1], item);
  renderReview(panels[2][1], item);
  const provenance = panels[3][1];
  appendField(provenance, 'Exact identities', {submission: item.id, revision: item.revision, source_digest: item.source_digest, patch_digest: item.patch_digest, check_digest: item.check_digest, evidence_digest: item.result?.evidence_digest, rubric_digest: item.rubric_digest, origin: item.origin});
  if (item.seeded_reviews?.length) { provenance.append(node('h3', 'Synthetic seeded reviewers'), node('p', 'These authored labels illustrate disagreement. They are separate from developer adjudication.', 'notice')); appendField(provenance, 'Seeded labels', item.seeded_reviews); }
  syncActions();
}
function renderEvidence(panel, item) {
  const result = item.result;
  if (!result) { panel.append(node('p', 'No machine evidence is available. Missing work cannot establish acceptance.', 'notice')); return; }
  panel.append(node('p', 'Actual checks are recorded below. Passing visible checks still requires semantic review against the task.', 'notice'));
  const grid = node('div', null, 'evidence-grid'); appendField(grid, 'Baseline measurement', result.baseline); appendField(grid, 'Candidate measurement', result.candidate); panel.append(grid);
  panel.append(node('p', 'Original source preserved: ' + (result.source_unchanged === true ? 'verified' : result.source_unchanged === false ? 'failed' : 'unavailable'), 'small'));
  if (!result.checks?.length) panel.append(node('p', 'No individual check output is listed.', 'muted'));
  for (const check of result.checks || []) {
    const details = node('details'); details.open = true; const summary = node('summary', check.name || 'Check'); summary.append(badge(check.outcome)); details.append(summary);
    appendField(details, 'Observed output', check); panel.append(details);
  }
}
function renderReview(panel, item) {
  const review = item.review;
  if (review) { panel.append(node('h3', item.context_current === false ? 'Historical developer adjudication' : 'Current developer adjudication'), badge(review.decision), node('p', review.reason || 'No reason recorded.')); appendField(panel, 'Criterion judgments and attribution', {criteria: review.criteria, actor: review.actor, origin: review.origin}); }
  else panel.append(node('p', 'No developer adjudication recorded.', 'muted'));
  if (!live) { panel.append(node('p', 'Recorded read-only evidence. Decisions cannot be changed in this view.', 'notice')); return; }
  if (item.context_current === false) { panel.append(node('p', 'Import the current task context to obtain a new evidence-bound revision. The historical decision is preserved.', 'notice')); return; }
  if (!item.result?.evidence_digest) { panel.append(node('p', 'Run the required checks before binding a review to machine evidence.', 'notice')); return; }
  const form = node('form'); form.id = 'review-form';
  form.append(node('h3', 'Review exact current evidence'), node('p', 'Assess each criterion. Acceptance requires five passes, completed passing machine evidence, and no unresolved execution.', 'small muted'));
  const rubric = node('div', null, 'rubric');
  for (const name of criteria) {
    const row = node('div', null, 'rubric-row'); const label = node('label', labels[name]); label.htmlFor = 'criterion-' + name;
    const select = node('select'); select.id = 'criterion-' + name; select.name = name;
    for (const value of ['not-assessed', 'pass', 'fail', 'uncertain']) { const option = node('option', value); option.value = value; select.append(option); }
    row.append(label, select); rubric.append(row);
  }
  form.append(rubric);
  const decisionLabel = node('label', 'Disposition'); decisionLabel.htmlFor = 'decision'; const decision = node('select'); decision.id = 'decision';
  for (const [value, title] of [['needs-work', 'Send back · needs work'], ['rejected', 'Reject'], ['accepted', 'Accept']]) { const option = node('option', title); option.value = value; if (value === 'accepted') option.disabled = item.result.overall !== 'passed' || item.execution_status !== 'completed'; decision.append(option); }
  const reasonLabel = node('label', 'Reason and evidence'); reasonLabel.htmlFor = 'reason'; const reason = node('textarea'); reason.id = 'reason'; reason.rows = 4; reason.maxLength = 8000; reason.required = true; reason.placeholder = 'Explain the requested behavior, observed evidence and any remaining defect.';
  const submit = node('button', 'Save exact-version adjudication', 'primary'); submit.type = 'submit'; submit.id = 'submit-review';
  form.append(decisionLabel, decision, reasonLabel, reason, node('p', 'Bound to revision ' + item.revision + ' · evidence ' + short(item.result.evidence_digest) + ' · rubric ' + short(item.rubric_digest), 'small digest'), submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const judgments = Object.fromEntries(criteria.map((name) => [name, $('criterion-' + name).value]));
    if (decision.value === 'accepted' && Object.values(judgments).some((value) => value !== 'pass')) { notify('Assess every criterion as pass before accepting.', true); return; }
    await mutation('/api/submissions/' + encodeURIComponent(item.id) + '/review', {expected_revision: item.revision, evidence_digest: item.result.evidence_digest, rubric_digest: item.rubric_digest, decision: decision.value, reason: reason.value, criteria: judgments}, 'review:' + item.id, async () => { await loadLive(); notify('Developer adjudication saved against the exact evidence revision.'); });
  });
  panel.append(form);
}
function renderAudit() {
  $('audit-list').replaceChildren();
  const cut = state.snapshot?.cut;
  $('audit-cut').textContent = cut ? 'Frozen cut #' + cut.seq + ' · ' + short(cut.hash) : live ? 'Current recorded events' : 'Cut unavailable';
  if (!state.audit.length) $('audit-list').append(node('p', 'No audit events available.', 'muted'));
  for (const event of [...state.audit].reverse()) { const details = node('details', null, 'audit-row'); const summary = node('summary', '#' + event.seq + ' · ' + event.kind + ' · ' + event.actor); details.append(summary, node('p', event.created_at || 'Time unavailable', 'small muted'), node('pre', JSON.stringify(event, null, 2))); $('audit-list').append(details); }
}
function render() { renderMetrics(); renderIntake(); renderQueue(); renderInspector(); renderAudit(); syncActions(); }
$('filter').addEventListener('change', renderQueue);
$('batch-select').addEventListener('change', () => { loadLive($('batch-select').value).catch((e) => notify(e.message, true)); });
$('connect-form').addEventListener('submit', async (event) => { event.preventDefault(); state.token = $('token').value; $('token').value = ''; try { await loadLive(); $('owner-actions').hidden = false; $('export').hidden = false; notify('Connected to the private owner API.'); } catch (e) { state.token = ''; notify(e.message, true); } syncActions(); });
$('disconnect').addEventListener('click', () => { state.token = ''; state.batch = null; state.items = []; state.audit = []; state.selected = null; retries.clear(); $('owner-actions').hidden = true; $('export').hidden = true; $('export-receipt').hidden = true; showBatchOptions([]); render(); notify('Disconnected. Owner token cleared from page memory.'); });
$('import').addEventListener('click', () => mutation('/api/import-sample', {}, 'import', async (batch) => { await loadLive(batch.id); notify('Trusted sample imported with explicit duplicate and invalid-line accounting.'); }));
$('process').addEventListener('click', () => { if (state.batch) mutation('/api/batches/' + encodeURIComponent(state.batch.id) + '/process', {workers: 1}, null, async () => { await loadLive(); notify('Processing returned. Inspect each submission for its measured outcome.'); }); });
$('refresh').addEventListener('click', () => loadLive().then(() => notify('Current evidence and revisions loaded.')).catch((e) => notify(e.message, true)));
$('export').addEventListener('click', () => { if (state.batch) mutation('/api/batches/' + encodeURIComponent(state.batch.id) + '/export', {}, 'export:' + state.batch.id, async (receipt) => { $('export-receipt').textContent = JSON.stringify(receipt, null, 2); $('export-receipt').hidden = false; if (receipt.metrics) renderExportMetrics(receipt.metrics); await loadLive(); notify('Export frozen. The receipt identifies its exact manifest and metrics.'); }); });
async function start() {
  if (live) { $('mode').textContent = 'Live · owner access'; $('connection').hidden = false; $('batch-meta').textContent = 'Connect to load private evidence.'; render(); return; }
  try {
    const response = await fetch('./data/evidence.json', {cache: 'no-store', credentials: 'omit'});
    if (!response.ok) throw new Error('The recorded evidence snapshot is unavailable.');
    const snapshot = await response.json();
    if (!snapshot.batch || !Array.isArray(snapshot.items) || !Array.isArray(snapshot.audit)) throw new Error('The recorded snapshot does not match the evidence schema.');
    state.snapshot = snapshot; state.batch = snapshot.batch; state.items = snapshot.items; state.audit = snapshot.audit; state.selected = snapshot.items[0]?.id;
    showBatchOptions([snapshot.batch]); $('downloads').hidden = false; render();
    const manifestResponse = await fetch('./data/manifest.json', {credentials: 'omit'});
    if (manifestResponse.ok) { const manifest = await manifestResponse.json(); renderExportMetrics(manifest.metrics || {}); }
    // Only this fixed local recording path is eligible; imported URLs are inert.
    const recording = await fetch('./recording.webm', {method: 'HEAD', credentials: 'omit'});
    if (recording.ok && (recording.headers.get('content-type') || '').startsWith('video/')) {
      const video = $('walkthrough'); video.muted = true; video.volume = 0.1; video.autoplay = false; video.src = './recording.webm';
      const track = node('track'); track.kind = 'captions'; track.label = 'Walkthrough captions'; track.srclang = 'en'; track.src = './recording.vtt'; track.default = true; video.append(track);
      try { const volume = Number(sessionStorage.getItem('workbench-preview-volume')); if (volume > 0 && volume <= 1) video.volume = volume; } catch {}
      video.addEventListener('volumechange', () => { try { sessionStorage.setItem('workbench-preview-volume', String(video.volume)); } catch {} });
      $('recording-section').hidden = false;
    }
  } catch (e) { render(); notify(e.message, true); }
}
start();
