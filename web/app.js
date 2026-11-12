/* Static is the default. Live mode is an explicit owner action on the private API.
   Imported strings enter the DOM only through textContent, never HTML or URLs. */
const $ = (id) => document.getElementById(id);
const live = new URLSearchParams(location.search).get('mode') === 'live';
const criteria = ['task_clarity', 'evidence_adequacy', 'requested_behavior', 'preserved_behavior', 'unsupported_claims'];
const labels = {task_clarity: 'Task clarity', evidence_adequacy: 'Evidence adequacy', requested_behavior: 'Requested behavior', preserved_behavior: 'Preserved behavior', unsupported_claims: 'Unsupported claims'};
const state = {token: '', batch: null, items: [], selected: null, audit: [], snapshot: null, bundle: null, busy: false, evaluation: null, qualityDemo: null};
const retries = new Map();
const reviewerModes = {developer_adjudication: 'Developer adjudication', ai_assisted_adjudication: 'AI-assisted adjudication', owner_adjudication: 'Owner adjudication', scripted_adjudication: 'Scripted adjudication'};
function reviewLabel(mode) { return reviewerModes[mode] || 'Unspecified adjudication'; }
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
function approvedInput() { return Boolean(state.bundle?.prediction_format && state.bundle.name !== 'synthetic-fixtures'); }
function current() { return state.items.find((item) => item.id === state.selected); }
async function request(path, body) {
  if (!live || !state.token) throw new Error('Connect to the private owner instance first.');
  const headers = {Authorization: 'Bearer ' + state.token};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'omit', redirect: 'error'});
  const data = await response.json();
  if (!response.ok) { const error = new Error((data.error?.code || response.status) + ': ' + (data.error?.message || 'Request failed.')); error.code = data.error?.code; error.status = response.status; throw error; }
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
  for (const button of document.querySelectorAll('#quality-content button[type=submit], #evaluation-export')) button.disabled = state.busy || !state.token;
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
  if (!id) { state.batch = null; state.items = []; state.audit = []; state.evaluation = null; showBatchOptions([]); render(); return; }
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
  state.evaluation = null;
  try {
    const evaluation = await request('/api/batches/' + encoded + '/evaluation');
    if (evaluation.context && Array.isArray(evaluation.items)) state.evaluation = evaluation;
  } catch (error) {
    if (!['evaluation-unavailable', 'evaluation-task-mismatch', 'task-not-found'].includes(error.code)) throw error;
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
  const facts = [['Input lines', batch?.raw_lines, 'Raw records received'], ['Unique submissions', batch?.unique_items, (batch?.duplicate_lines ?? '—') + ' duplicate · ' + (batch?.invalid_lines ?? '—') + ' invalid'], ['Completed checks', counts.completed, 'Execution status'], ['Accepted', batch ? (counts.accepted ?? state.items.filter((x) => x.disposition === 'accepted').length) : undefined, 'Recorded adjudication']];
  $('metrics').replaceChildren(...facts.map(([label, value, note]) => { const block = node('div', null, 'metric'); block.append(node('span', label, 'small muted'), node('strong', value ?? '—'), node('span', note, 'small muted')); return block; }));
  $('batch-meta').textContent = batch ? 'Recorded source: ' + (batch.created_at || 'time unavailable') + ' · ' + short(batch.id) : live ? (approvedInput() ? 'Import the approved task to begin.' : 'Import the trusted sample to begin.') : 'No recorded snapshot available.';
}
function renderCase() {
  const publicCase = state.bundle?.origin === 'public_upstream' || state.items.some((item) => item.origin === 'public_upstream');
  const synthetic = !publicCase && (state.bundle?.origin === 'synthetic_fixture' || state.items.some((item) => item.origin === 'synthetic_fixture'));
  $('case-kind').textContent = publicCase ? 'PUBLIC UPSTREAM CASE' : synthetic ? 'SYNTHETIC FIXTURE CASE' : 'CONFIGURED CASE';
  $('case-title').textContent = state.bundle?.title || (publicCase ? 'Public upstream code with recorded check evidence' : synthetic ? 'Original synthetic workflow demonstration' : 'Evidence and attribution');
  const description = publicCase ? 'Pinned upstream code and candidate provenance appear with each submission. Synthetic controls are labeled separately. Check output reflects the configured local recipe.' : synthetic ? 'Authored synthetic tasks and controls illustrate the workflow. Their executable checks and recorded decisions remain inspectable.' : 'Inspect each submitted patch, its occurrence-level source claims, approved provenance and actual check evidence.';
  $('case-description').textContent = description;
  $('case-sidebar').textContent = publicCase ? 'Public upstream case. Labeled synthetic controls. Real check observations.' : synthetic ? 'Synthetic coding fixtures. Real executable checks. Version-bound adjudication.' : 'Recorded coding submissions. Real executable checks. Version-bound adjudication.';
  $('synthetic-link').hidden = live || !publicCase;
  $('first-upstream-link').hidden = live || !publicCase || state.snapshot?.runtime?.bundle?.name !== 'escape-goat';
  $('import').textContent = approvedInput() ? 'Import approved task' : 'Import trusted sample';
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
  statuses.append(badge(item.origin || 'origin unavailable'));
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
  appendField(provenance, 'Approved source and patch provenance', {origin: item.origin, trusted_tuple: item.trusted_tuple, provenance: item.provenance, patch_provenance: item.patch_provenance});
  provenance.append(node('p', 'Source and model names below are claims from individual input occurrences. Approval of an exact execution tuple is recorded separately.', 'small muted'));
  const occurrences = item.lineage || item.occurrences || state.batch?.occurrences?.filter((occurrence) => occurrence.submission_id === item.id);
  appendField(provenance, 'Input occurrences and declared source/model claims', occurrences?.length ? occurrences.map(({raw_record_base64, ...claim}) => claim) : {availability: 'Occurrence-level claims are not present in this recorded view.', declared_origin: item.declared_origin});
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
  if (review) { panel.append(node('h3', (item.context_current === false ? 'Historical ' : 'Current ') + reviewLabel(review.reviewer_mode || review.origin).toLowerCase()), badge(review.decision), node('p', review.reason || 'No reason recorded.')); appendField(panel, 'Criterion judgments and attribution', {criteria: review.criteria, actor: review.actor, origin: review.origin, reviewer_mode: review.reviewer_mode || review.origin}); }
  else panel.append(node('p', 'No adjudication recorded.', 'muted'));
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
  const reviewerLabel = node('label', 'Reviewer mode'); reviewerLabel.htmlFor = 'reviewer-mode';
  const reviewerMode = node('select'); reviewerMode.id = 'reviewer-mode'; reviewerMode.name = 'reviewer_mode';
  for (const [value, title] of Object.entries(reviewerModes)) { const option = node('option', title); option.value = value; reviewerMode.append(option); }
  form.append(reviewerLabel, reviewerMode, node('p', 'Record who directed this decision and the assistance used. Independent authorship requires separate evidence.', 'small muted'));
  const decisionLabel = node('label', 'Disposition'); decisionLabel.htmlFor = 'decision'; const decision = node('select'); decision.id = 'decision'; decision.required = true; const choose = node('option', 'Choose a disposition'); choose.value = ''; choose.disabled = true; choose.selected = true; decision.append(choose);
  for (const [value, title] of [['needs-work', 'Send back · needs work'], ['rejected', 'Reject'], ['accepted', 'Accept']]) { const option = node('option', title); option.value = value; if (value === 'accepted') option.disabled = item.result.overall !== 'passed' || item.execution_status !== 'completed'; decision.append(option); }
  const reasonLabel = node('label', 'Reason and evidence'); reasonLabel.htmlFor = 'reason'; const reason = node('textarea'); reason.id = 'reason'; reason.rows = 4; reason.maxLength = 8000; reason.required = true; reason.placeholder = 'Explain the requested behavior, observed evidence and any remaining defect.';
  const submit = node('button', 'Save exact-version adjudication', 'primary'); submit.type = 'submit'; submit.id = 'submit-review';
  form.append(decisionLabel, decision, reasonLabel, reason, node('p', 'Bound to revision ' + item.revision + ' · evidence ' + short(item.result.evidence_digest) + ' · rubric ' + short(item.rubric_digest), 'small digest'), submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const judgments = Object.fromEntries(criteria.map((name) => [name, $('criterion-' + name).value]));
    if (decision.value === 'accepted' && Object.values(judgments).some((value) => value !== 'pass')) { notify('Assess every criterion as pass before accepting.', true); return; }
    await mutation('/api/submissions/' + encodeURIComponent(item.id) + '/review', {expected_revision: item.revision, evidence_digest: item.result.evidence_digest, rubric_digest: item.rubric_digest, decision: decision.value, reason: reason.value, criteria: judgments, reviewer_mode: reviewerMode.value}, 'review:' + item.id, async () => { await loadLive(); notify(reviewLabel(reviewerMode.value) + ' saved against the exact evidence revision.'); });
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
function criticalLabel(value) { return value === true ? 'passed' : value === false ? 'failed' : 'unassessed'; }
function scoreText(score, max) { return score === null || score === undefined ? 'Unassessed' : score + ' / ' + (max ?? '—'); }
function qualityTable(parent, scores) {
  const wrapper = node('div', null, 'table-scroll');
  const table = node('table'); const caption = node('caption', 'Criterion scores for every submission'); table.append(caption);
  const head = node('thead'); const header = node('tr');
  const rubric = scores.context.rubric || [];
  for (const label of ['Submission / role', ...rubric.map((criterion) => criterion.id + (criterion.critical ? ' · critical' : '')), 'Total credit', 'Critical gate']) { const cell = node('th', label); cell.scope = 'col'; header.append(cell); }
  head.append(header); table.append(head); const body = node('tbody');
  for (const item of scores.items) {
    const row = node('tr', null, item.critical_passed === false ? 'critical-failure' : '');
    const identity = node('th'); identity.scope = 'row'; identity.append(node('span', short(item.patch_digest), 'digest'), node('span', item.role || 'candidate'), node('span', item.origin || 'origin unavailable', 'small muted'));
    row.append(identity);
    for (const criterion of rubric) {
      const observation = item.criteria?.find((value) => value.id === criterion.id);
      const cell = node('td'); cell.append(node('strong', scoreText(observation?.earned, observation?.points ?? criterion.points)), badge(observation?.outcome || 'unassessed')); row.append(cell);
    }
    row.append(node('td', scoreText(item.score, item.max_score)));
    const gate = node('td'); gate.append(badge(criticalLabel(item.critical_passed))); row.append(gate); body.append(row);
  }
  table.append(body); wrapper.append(table); parent.append(wrapper);
  const details = node('details'); details.append(node('summary', 'Named check observations and candidate attribution'));
  for (const item of scores.items) appendField(details, short(item.patch_digest) + ' · ' + (item.role || 'candidate'), item);
  parent.append(details);
}
function renderFindings(parent, findings) {
  parent.append(node('h4', 'Task findings'));
  if (!findings?.length) { parent.append(node('p', 'No task findings recorded.', 'muted')); return; }
  for (const finding of findings) {
    const block = node('article', null, 'quality-finding');
    block.append(node('h4', finding.id + ' · ' + finding.kind), badge(finding.severity), badge(finding.status), node('p', finding.reason), node('p', 'Assigned to: ' + finding.assignee, 'small'), node('p', 'Requested correction: ' + finding.requested_correction, 'small'));
    if (finding.resolution) block.append(node('p', 'Resolution: ' + finding.resolution, 'small'));
    parent.append(block);
  }
}
function renderCalibration(parent, records) {
  parent.append(node('h4', 'Review calibration and author feedback'));
  if (!records?.length) { parent.append(node('p', 'No calibration recorded.', 'muted')); return; }
  for (const record of records) {
    const details = node('details'); details.open = true;
    details.append(node('summary', 'Recorded calibration · ' + (record.actor || 'actor unavailable')), node('p', record.reason), node('h4', 'Author feedback'), node('p', record.author_feedback), node('h4', 'Guideline update'), node('p', record.guideline_update));
    for (const review of record.reviews || []) appendField(details, (review.actor || 'Reviewer') + ' · ' + reviewLabel(review.reviewer_mode), review);
    if (record.agreement) appendField(details, 'Declared paired judgments', record.agreement);
    parent.append(details);
  }
}
function renderScoreVersion(parent, scores, title) {
  const context = scores.context;
  const section = node('section', null, 'quality-version');
  section.append(node('h3', title), badge(context.evaluation?.kind || 'kind unavailable'), badge(context.quality?.decision || 'draft'), node('p', 'Task ' + context.task_id + ' · checker version ' + display(context.evaluation?.version) + ' · task revision ' + context.revision, 'small muted'), node('p', context.quality?.reason || 'No task-quality decision reason recorded.'));
  section.append(node('p', reviewLabel(context.quality?.reviewer_mode) + ' · ' + (context.quality?.actor || 'no reviewer recorded'), 'small muted'));
  const requirements = node('details'); requirements.append(node('summary', 'Requirements and exact task identity'));
  const list = node('ul');
  for (const requirement of context.requirements || []) list.append(node('li', requirement.id + ': ' + requirement.text));
  requirements.append(list, node('p', 'Context: ' + context.id, 'digest'), node('p', 'Material: ' + (context.material_digest || 'unavailable'), 'digest')); section.append(requirements);
  qualityTable(section, scores); renderFindings(section, context.findings); renderCalibration(section, context.calibration);
  const summary = node('details'); summary.append(node('summary', 'Task and submission denominators'), node('pre', display(scores.summary))); section.append(summary);
  parent.append(section);
}
function formField(form, id, label, multiline = true) {
  const text = node('label', label); text.htmlFor = id;
  const field = node(multiline ? 'textarea' : 'input'); field.id = id; field.required = true;
  if (multiline) { field.rows = 3; field.maxLength = 8000; }
  form.append(text, field); return field;
}
function jsonArray(field, label) {
  let value;
  try { value = JSON.parse(field.value); } catch { throw new Error(label + ' must be valid JSON.'); }
  if (!Array.isArray(value)) throw new Error(label + ' must be a JSON array.');
  return value;
}
function renderQualityForms(parent, scores) {
  const context = scores.context;
  const taskPath = '/api/tasks/' + encodeURIComponent(context.task_id);
  const details = node('details'); details.append(node('summary', 'Review task quality'));
  const form = node('form'); form.id = 'task-quality-form';
  const decisionLabel = node('label', 'Task quality decision'); decisionLabel.htmlFor = 'task-quality-decision';
  const decision = node('select'); decision.id = 'task-quality-decision'; decision.required = true;
  for (const [value, title] of [['', 'Choose a task decision'], ['needs-repair', 'Needs repair'], ['quarantined', 'Quarantine audit version'], ['approved', 'Approve clean task']]) { const option = node('option', title); option.value = value; decision.append(option); }
  form.append(decisionLabel, decision);
  const reason = formField(form, 'task-quality-reason', 'Task quality reason');
  const modeLabel = node('label', 'Task reviewer mode'); modeLabel.htmlFor = 'task-reviewer-mode'; const mode = node('select'); mode.id = 'task-reviewer-mode';
  for (const [value, title] of Object.entries(reviewerModes)) { const option = node('option', title); option.value = value; mode.append(option); } mode.value = 'ai_assisted_adjudication'; form.append(modeLabel, mode);
  const findings = formField(form, 'task-findings', 'Findings (JSON array)'); findings.maxLength = 56000; findings.rows = 9; findings.spellcheck = false; findings.value = JSON.stringify(context.findings || [], null, 2);
  form.append(node('p', 'Each finding needs id, kind, severity (low/medium/high/critical), status (open/resolved), reason, assignee and requested_correction. Resolved findings also need resolution. Keep earlier findings and record their resolution.', 'small muted'), node('p', 'Bound to task revision ' + context.revision + ' · ' + context.id, 'small digest'));
  const submit = node('button', 'Save task quality', 'primary'); submit.type = 'submit'; form.append(submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    let records; try { records = jsonArray(findings, 'Findings'); } catch (error) { notify(error.message, true); return; }
    await mutation(taskPath + '/quality', {decision: decision.value, reason: reason.value, findings: records, expected_revision: context.revision, reviewer_mode: mode.value}, 'task-quality:' + context.id, async () => { await loadLive(); notify('Task quality saved against the current task revision.'); });
  });
  details.append(form); parent.append(details);
  const calibrationDetails = node('details'); calibrationDetails.append(node('summary', 'Record calibration and author feedback'));
  const calibration = node('form'); calibration.id = 'task-calibration-form';
  const reviews = formField(calibration, 'calibration-reviews', 'Recorded AI-assisted reviews (JSON array)'); reviews.rows = 8; reviews.maxLength = 56000; reviews.spellcheck = false;
  calibration.append(node('p', 'Supply at least two actual separately recorded reviews with review_id, actor, decision, reason, reviewer_mode=ai_assisted_adjudication, input_digest and output_digest. Digests identify the recorded input and output.', 'small muted'));
  const calibrationReason = formField(calibration, 'calibration-reason', 'Calibration reason');
  const feedback = formField(calibration, 'calibration-feedback', 'Author feedback');
  const guideline = formField(calibration, 'calibration-guideline', 'Guideline update');
  const save = node('button', 'Save calibration', 'primary'); save.type = 'submit'; calibration.append(save);
  calibration.addEventListener('submit', async (event) => {
    event.preventDefault();
    let records; try { records = jsonArray(reviews, 'Recorded reviews'); } catch (error) { notify(error.message, true); return; }
    await mutation(taskPath + '/calibration', {reviews: records, reason: calibrationReason.value, author_feedback: feedback.value, guideline_update: guideline.value}, 'calibration:' + context.id, async () => { await loadLive(); notify('Calibration, author feedback and guideline update recorded.'); });
  });
  calibrationDetails.append(calibration); parent.append(calibrationDetails);
  const exportButton = node('button', 'Freeze evaluation dataset', 'primary'); exportButton.id = 'evaluation-export'; exportButton.type = 'button';
  const receipt = node('pre'); receipt.id = 'evaluation-export-receipt'; receipt.hidden = true;
  exportButton.addEventListener('click', () => mutation('/api/batches/' + encodeURIComponent(state.batch.id) + '/evaluation-export', {}, 'evaluation-export:' + context.id, async (result) => { receipt.textContent = JSON.stringify(result, null, 2); receipt.hidden = false; notify('Evaluation dataset frozen with every candidate outcome.'); }));
  parent.append(exportButton, receipt);
}
function renderQuality() {
  const versions = live ? (state.evaluation ? [state.evaluation] : []) : (state.qualityDemo?.versions || []);
  const root = $('quality-content'); root.replaceChildren(); $('quality-section').hidden = !versions.length;
  if (!versions.length) return;
  $('quality-heading').textContent = 'Evaluation quality';
  $('quality-intro').textContent = 'Task approval and candidate credit use separate evidence. Inspect each criterion and the critical behavior gate alongside the total.';
  if (!live && Array.isArray(state.qualityDemo.comparison)) {
    const comparison = node('section'); comparison.append(node('h3', 'Same patches, two checker versions'));
    const wrapper = node('div', null, 'table-scroll'); const table = node('table'); const head = node('tr');
    for (const title of ['Patch / attribution', 'Before credit', 'After credit', 'Before critical gate', 'After critical gate', 'Audit observation']) head.append(node('th', title));
    const thead = node('thead'); thead.append(head); table.append(thead); const body = node('tbody');
    for (const item of state.qualityDemo.comparison) {
      const row = node('tr', null, item.false_pass === true ? 'false-pass' : '');
      const label = node('th'); label.scope = 'row'; label.append(node('strong', item.label || short(item.patch_digest)), node('span', item.origin || 'origin unavailable', 'small muted'), node('span', short(item.patch_digest), 'digest')); row.append(label);
      row.append(node('td', item.before_score ?? 'Unassessed'), node('td', item.after_score ?? 'Unassessed'), node('td', criticalLabel(item.before_critical)), node('td', criticalLabel(item.after_critical)), node('td', item.false_pass === true ? 'False pass exposed' : 'See criterion evidence'));
      body.append(row);
    }
    table.append(body); wrapper.append(table); comparison.append(wrapper); root.append(comparison);
  }
  for (const [index, scores] of versions.entries()) renderScoreVersion(root, scores, live ? 'Current task context' : index === 0 ? 'Before · original checker' : 'After · revised checker');
  if (live) renderQualityForms(root, state.evaluation);
  else {
    if (state.qualityDemo.author_feedback) appendField(root, 'Recorded author feedback', state.qualityDemo.author_feedback);
    if (state.qualityDemo.guideline_update) appendField(root, 'Recorded guideline update', state.qualityDemo.guideline_update);
    const exports = node('nav', null, 'actions'); exports.setAttribute('aria-label', 'Evaluation evidence downloads');
    for (const [version, label] of [['before', 'Before repair'], ['after', 'After repair']]) {
      for (const [file, kind] of [['evaluation.json', 'all outcomes'], ['evidence.json', 'bound evidence'], ['manifest.json', 'manifest']]) {
        const link = node('a', label + ' · ' + kind, 'button'); link.href = './evaluation/' + version + '/' + file; link.download = ''; exports.append(link);
      }
    }
    root.append(exports);
    // Only show root-provided earlier views from the main published page.
    if (location.pathname === '/') {
      const nav = node('nav', null, 'actions'); nav.setAttribute('aria-label', 'Earlier demonstrations');
      for (const [path, label] of [['./prepared/', 'Prepared bundle example'], ['./unicode-hyphen/', 'Unicode hyphen example'], ['./synthetic/', 'Original synthetic example']]) { const link = node('a', label, 'button'); link.href = path; nav.append(link); }
      root.append(nav);
    }
  }
}
async function loadRecordedQuality() {
  try {
    const response = await fetch('./quality.json', {credentials: 'omit', cache: 'no-store'});
    if (response.status === 404) return;
    if (!response.ok) throw new Error('The optional evaluation-quality record is unavailable.');
    const data = await response.json();
    if (data.schema !== 'swe-workbench-quality-demo/v1' || !Array.isArray(data.versions) || !data.versions.every((version) => version.context && Array.isArray(version.items))) throw new Error('The evaluation-quality record does not match its schema.');
    state.qualityDemo = data; renderQuality();
  } catch (error) { notify(error.message, true); }
}

function render() { renderCase(); renderQuality(); renderMetrics(); renderIntake(); renderQueue(); renderInspector(); renderAudit(); syncActions(); }
$('filter').addEventListener('change', renderQueue);
$('batch-select').addEventListener('change', () => { loadLive($('batch-select').value).catch((e) => notify(e.message, true)); });
$('connect-form').addEventListener('submit', async (event) => { event.preventDefault(); state.token = $('token').value; $('token').value = ''; try { state.bundle = await request('/api/bundle'); await loadLive(); $('owner-actions').hidden = false; $('export').hidden = false; notify('Connected to the private owner API.'); } catch (e) { state.token = ''; notify(e.message, true); } syncActions(); });
$('disconnect').addEventListener('click', () => { state.token = ''; state.batch = null; state.items = []; state.audit = []; state.selected = null; state.bundle = null; state.evaluation = null; retries.clear(); $('owner-actions').hidden = true; $('export').hidden = true; $('export-receipt').hidden = true; showBatchOptions([]); render(); notify('Disconnected. Owner token cleared from page memory.'); });
$('import').addEventListener('click', () => mutation(approvedInput() ? '/api/import-approved' : '/api/import-sample', {}, 'import', async (batch) => { await loadLive(batch.id); notify('Configured input imported with duplicate accounting and occurrence-level source claims.'); }));
$('process').addEventListener('click', () => { if (state.batch) mutation('/api/batches/' + encodeURIComponent(state.batch.id) + '/process', {workers: 1}, null, async () => { await loadLive(); notify('Processing returned. Inspect each submission for its measured outcome.'); }); });
$('refresh').addEventListener('click', () => loadLive().then(() => notify('Current evidence and revisions loaded.')).catch((e) => notify(e.message, true)));
$('export').addEventListener('click', () => { if (state.batch) mutation('/api/batches/' + encodeURIComponent(state.batch.id) + '/export', {}, 'export:' + state.batch.id, async (receipt) => { $('export-receipt').textContent = JSON.stringify(receipt, null, 2); $('export-receipt').hidden = false; if (receipt.metrics) renderExportMetrics(receipt.metrics); await loadLive(); notify('Export frozen. The receipt identifies its exact manifest and metrics.'); }); });
async function loadHandoff() {
  const response = await fetch('./handoff/handoff.json', {credentials: 'omit', cache: 'no-store'});
  if (response.status === 404) return;
  if (!response.ok) throw new Error('The change handoff is unavailable.');
  const record = await response.json();
  if (record.schema !== 'swe-workbench-handoff/v1' || !record.state || !Array.isArray(record.material?.observations)) throw new Error('Unsupported change handoff.');
  const {state: review, material} = record; const root = $('handoff-content'); root.replaceChildren();
  root.append(node('h3', material.title), node('p', material.goal), badge(review.decision),
    node('p', 'Handoff readiness records a review package. Code acceptance and delivery remain with the source project.', 'small muted'),
    node('p', 'External check reports · ' + record.workbench_executions + ' checks executed by this handoff · ' + record.keep_mutations + ' source-project mutations', 'notice'));
  const identity = node('dl', null, 'handoff-identity');
  for (const [label, value] of [['Base', material.base_revision], ['Candidate', material.candidate_revision], ['Patch SHA-256', material.patch_sha256], ['Review revision', review.revision]]) {
    identity.append(node('dt', label), node('dd', value, 'digest'));
  }
  root.append(identity);
  const wrapper = node('div', null, 'table-scroll'); const table = node('table'); const header = node('tr');
  for (const text of ['Observation', 'Reported result', 'Source binding', 'Scope and origin']) header.append(node('th', text));
  const head = node('thead'); head.append(header); table.append(head); const body = node('tbody');
  for (const observation of material.observations) {
    const value = observation.value;
    const result = value && typeof value === 'object' && Number.isInteger(value.passed) && Number.isInteger(value.tests) ? value.passed + ' / ' + value.tests + ' passed · ' + (value.profile || 'profile unspecified') : display(value);
    const row = node('tr'); row.append(node('th', observation.label), node('td', result), node('td', observation.binding), node('td', observation.scope + ' · externally reported'));
    body.append(row);
  }
  table.append(body); wrapper.append(table); root.append(wrapper);
  appendField(root, 'Recorded review', review.reason);
  const findings = node('ul'); for (const finding of review.findings) findings.append(node('li', finding));
  root.append(node('h3', 'What remains unresolved'), findings); appendField(root, 'Next action', review.next_action);
  const details = node('details'); details.append(node('summary', 'Exact diff and reported evidence'));
  appendField(details, 'Patch', material.patch);
  for (const observation of material.observations) appendField(details, observation.label, observation.value);
  details.append(node('p', material.assurance, 'small muted')); root.append(details);
  const history = node('details'); history.append(node('summary', 'Version-bound review history'));
  for (const event of record.events) history.append(node('p', event.kind + ' · revision ' + event.payload.revision + ' · ' + event.created_at));
  root.append(history); const downloads = node('nav', null, 'actions'); downloads.setAttribute('aria-label', 'Change handoff downloads');
  for (const [file, label] of [['handoff.json', 'Change and review'], ['artifacts.json', 'Retained evidence'], ['manifest.json', 'Manifest']]) {
    const link = node('a', label, 'button'); link.href = './handoff/' + file; link.download = ''; downloads.append(link);
  }
  root.append(downloads, node('p', 'Reported checks remain unsigned external evidence. Content hashes establish consistency. This view performs no source-project action.', 'small muted'));
  $('handoff-section').hidden = false;
  $('recording-section').querySelector('h2').textContent = 'Earlier task-quality walkthrough · 0.1.0a4';
}
async function start() {
  if (live) { $('mode').textContent = 'Live · owner access'; $('connection').hidden = false; $('batch-meta').textContent = 'Connect to load private evidence.'; render(); return; }
  try {
    const response = await fetch('./data/evidence.json', {cache: 'no-store', credentials: 'omit'});
    if (!response.ok) throw new Error('The recorded evidence snapshot is unavailable.');
    const snapshot = await response.json();
    if (!snapshot.batch || !Array.isArray(snapshot.items) || !Array.isArray(snapshot.audit)) throw new Error('The recorded snapshot does not match the evidence schema.');
    state.snapshot = snapshot; state.bundle = snapshot.runtime?.bundle || null; state.batch = snapshot.batch; state.items = snapshot.items; state.audit = snapshot.audit; state.selected = snapshot.items[0]?.id;
    showBatchOptions([snapshot.batch]); $('downloads').hidden = false; render();
    const manifestResponse = await fetch('./data/manifest.json', {credentials: 'omit'});
    if (manifestResponse.ok) { const manifest = await manifestResponse.json(); renderExportMetrics(manifest.metrics || {}); }
    await loadRecordedQuality();
    await loadHandoff();
    // Only this fixed local recording path is eligible; imported URLs are inert.
    const recording = await fetch('./recording.webm', {method: 'HEAD', credentials: 'omit'});
    if (recording.ok && (recording.headers.get('content-type') || '').startsWith('video/')) {
      const video = $('walkthrough'); video.muted = true; video.volume = 0.1; video.autoplay = false; video.src = './recording.webm';
      const track = node('track'); track.kind = 'captions'; track.label = 'Walkthrough captions'; track.srclang = 'en'; track.src = './captions.vtt'; track.default = true; video.append(track);
      try { const volume = Number(sessionStorage.getItem('workbench-preview-volume')); if (sessionStorage.getItem('workbench-preview-volume') !== null && Number.isFinite(volume) && volume >= 0 && volume <= 1) video.volume = volume; } catch {}
      video.addEventListener('volumechange', () => { try { sessionStorage.setItem('workbench-preview-volume', String(video.volume)); } catch {} });
      $('recording-section').hidden = false;
    }
  } catch (e) { render(); notify(e.message, true); }
}
start();
