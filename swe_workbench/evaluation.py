"""Version-bound task quality and computed task-specific integer credit.

Task state is an immutable artifact referenced by existing meta/audit rows.
Submission acceptance remains a separate authority in core.py.
"""
from __future__ import annotations
from collections import Counter
import json
import re
from .core import REVIEWER_MODES
from .errors import WorkbenchError
from .store import canonical, digest

VERSION = 'task-quality-v1'
STATE_EVENTS = {'task-context-created', 'task-quality-reviewed', 'task-calibration-recorded'}
HEX = re.compile(r'[0-9a-f]{64}\Z')


def require(condition, message, code='invalid-evaluation', status=400):
    if not condition:
        raise WorkbenchError(code, message, status)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _material(w, task_id):
    task = w.catalog['tasks'].get(task_id)
    require(task is not None, 'Task does not exist.', 'task-not-found', 404)
    evaluation = task.get('evaluation')
    require(isinstance(evaluation, dict), 'Task has no evaluation definition.', 'evaluation-unavailable', 422)
    require(evaluation.get('kind') in ('clean', 'audit_challenge') and _nonempty(evaluation.get('family'))
            and type(evaluation.get('version')) in (str, int), 'Evaluation kind, family and version are required.')
    requirements, rubric = evaluation.get('requirements'), evaluation.get('rubric')
    require(isinstance(requirements, list) and bool(requirements), 'Requirements must be a nonempty list.')
    ids = []
    for item in requirements:
        require(isinstance(item, dict) and _nonempty(item.get('id')) and _nonempty(item.get('text')), 'Each requirement needs an ID and text.')
        ids.append(item['id'])
    require(len(ids) == len(set(ids)), 'Requirement IDs must be unique.')
    names = [c['name'] for c in task['checks']]
    require(len(names) == len(set(names)), 'Check names must be unique.')
    require(isinstance(rubric, list) and bool(rubric), 'Rubric must be a nonempty list.')
    ids, used = [], []
    for criterion in rubric:
        require(isinstance(criterion, dict) and _nonempty(criterion.get('id'))
                and type(criterion.get('points')) is int and criterion['points'] >= 0
                and type(criterion.get('critical')) is bool and isinstance(criterion.get('checks'), list)
                and bool(criterion['checks']) and all(isinstance(c, str) and c in names for c in criterion['checks']),
                'Criteria need unique IDs, nonnegative integer points, known checks and an explicit critical flag.')
        ids.append(criterion['id']); used.extend(criterion['checks'])
    require(len(ids) == len(set(ids)) and len(used) == len(set(used)), 'Criteria/checks cannot be duplicated for credit.')
    selected = {digest(p.encode('utf-8')) for p in task['patches']}
    roles = [evaluation.get('reference_patch_digest'), evaluation.get('alternate_patch_digest')]
    require(all(isinstance(role, str) and HEX.fullmatch(role) and role in selected for role in roles)
            and roles[0] != roles[1], 'Reference and alternate must identify distinct exact admitted patches.')
    # Material includes the full visible/protected roles and attribution, never
    # local bundle paths. Machine identities come from the existing core seam.
    binding = w._record({'task_id': task_id, 'patch': task['patches'][0]})
    return {'schema': VERSION, 'task_id': task_id, 'task': task,
            'source_digest': binding['source_digest'], 'check_digest': binding['check_digest'],
            'submission_rubric_digest': binding['rubric_digest']}


def material_id(material):
    return 'task-' + digest(canonical(material))


def _load(w, con, context_id):
    row = con.execute('SELECT value FROM meta WHERE key=?', ('quality-context:' + context_id,)).fetchone()
    if not row:
        raise WorkbenchError('quality-context-not-found', 'Task context is not recorded.', 404)
    state_digest = row['value']
    state = json.loads(w.store.artifact_bytes(state_digest))
    require(state['id'] == context_id and material_id(state['material']) == context_id
            and digest(canonical(state['material'])) == state['material_digest'], 'Task material identity mismatch.', 'quality-integrity', 409)
    require(w.store.artifact_bytes(state['material_digest']) == canonical(state['material']),
            'Original task material artifact differs from current state.', 'quality-integrity', 409)
    events = [e for e in w.store.events(con) if e['kind'] in STATE_EVENTS and e['payload'].get('context_id') == context_id]
    require(bool(events) and events[-1]['payload'].get('state_digest') == state_digest,
            'Task state is not bound to its current audit event.', 'quality-integrity', 409)
    return state | {'state_digest': state_digest}


def _save(w, con, state, kind, actor):
    value = dict(state); value.pop('state_digest', None)
    # Revision tokens are unique across versions of the same task, preventing
    # a stale request for an older draft from matching a new context's draft.
    prior = [e['payload']['revision'] for e in w.store.events(con)
             if e['kind'] in STATE_EVENTS and e['payload'].get('task_id') == state['task_id']]
    value['revision'] = max(prior, default=-1) + 1
    state_digest = w.store.artifact_write(canonical(value))
    con.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                ('quality-context:' + state['id'], state_digest))
    w.store.event(con, kind, {'task_id': state['task_id'], 'context_id': state['id'],
                            'revision': value['revision'], 'material_digest': state['material_digest'],
                            'state_digest': state_digest, 'decision': state['quality']['decision']}, actor=actor)
    return value | {'state_digest': state_digest}


def context(w, task_id):
    w._ready()
    material = _material(w, task_id)
    context_id = material_id(material)
    with w.store.transaction() as con:
        w.store.verify_audit(con)
        if con.execute('SELECT 1 FROM meta WHERE key=?', ('quality-context:' + context_id,)).fetchone():
            return _load(w, con, context_id)
        task = material['task']
        material_digest = w.store.artifact_write(canonical(material))
        state = {'id': context_id, 'task_id': task_id, 'revision': 0, 'material': material, 'material_digest': material_digest,
                 'evaluation': task['evaluation'], 'rubric': task['evaluation']['rubric'],
                 'requirements': task['evaluation']['requirements'],
                 'quality': {'decision': 'draft', 'reason': '', 'actor': None, 'reviewer_mode': None},
                 'findings': [], 'calibration': []}
        return _save(w, con, state, 'task-context-created', 'system')


def _findings(findings):
    require(isinstance(findings, list), 'Findings must be a list.', 'invalid-findings')
    ids = []
    for finding in findings:
        require(isinstance(finding, dict) and all(_nonempty(finding.get(k)) for k in
                ('id', 'kind', 'reason', 'assignee', 'requested_correction'))
                and finding.get('severity') in ('low', 'medium', 'high', 'critical')
                and finding.get('status') in ('open', 'resolved'),
                'Findings require ID, kind, severity, status, reason, assignee and requested correction.', 'invalid-findings')
        if finding['status'] == 'resolved':
            require(_nonempty(finding.get('resolution')), 'Resolved findings require a resolution/revision link.', 'invalid-findings')
        ids.append(finding['id'])
    require(len(ids) == len(set(ids)), 'Finding IDs must be unique.', 'invalid-findings')


def _actor(actor, mode):
    require(_nonempty(actor) and isinstance(mode, str) and mode in REVIEWER_MODES,
            'An actor and supported reviewer mode are required.', 'invalid-reviewer-mode')


def score_item(state, item):
    material, definition = state['material'], state['evaluation']
    result = item.get('result')
    bound = bool(result and item.get('context_current', True) and item.get('execution_status') == 'completed'
                 and result.get('overall') in ('passed', 'failed') and result.get('source_unchanged') is True
                 and item['task_id'] == state['task_id']
                 and item.get('source_digest') == material['source_digest']
                 and item.get('check_digest') == material['check_digest']
                 and item.get('task_text') == material['task']['task_text']
                 and result.get('submission_id') == item['id']
                 and all(result.get(k) == item.get(k) for k in ('source_digest','patch_digest','check_digest','rubric_digest')))
    if material['task'].get('verifier_files') is not None:
        integrity = (result or {}).get('verifier_integrity', {})
        bound = bound and integrity.get('unchanged') is True and integrity.get('verifier_digest') == digest(canonical(material['task']['verifier_files']))
    observations = (result or {}).get('candidate', {}).get('checks', [])
    names = [c.get('name') for c in observations]
    if len(names) != len(set(names)):
        bound = False
    criteria = []
    for criterion in state['rubric']:
        checks = [check for check in observations if check.get('name') in criterion['checks']]
        outcomes = [c.get('outcome') for c in checks]
        known = bound and len(checks) == len(criterion['checks']) and all(o in ('passed','failed') for o in outcomes)
        passed = known and all(o == 'passed' for o in outcomes)
        outcome = ('passed' if passed else 'failed') if known else 'unassessed'
        criteria.append({'id': criterion['id'], 'points': criterion['points'], 'critical': criterion['critical'],
                         'checks': checks, 'outcome': outcome, 'earned': criterion['points'] if passed else (0 if known else None)})
    complete = all(c['earned'] is not None for c in criteria)
    critical = [c for c in criteria if c['critical']]
    critical_passed = (all(c['outcome'] == 'passed' for c in critical) if all(c['earned'] is not None for c in critical) else None)
    patch = item['patch_digest']
    role = 'reference' if patch == definition['reference_patch_digest'] else ('alternate' if patch == definition['alternate_patch_digest'] else 'candidate')
    return {'submission_id': item['id'], 'patch_digest': patch, 'role': role,
            'origin': item.get('origin'), 'provenance': item.get('patch_provenance', {}), 'lineage': item.get('lineage', []),
            'execution_status': item['execution_status'], 'overall': result.get('overall') if result else 'not-run',
            'criteria': criteria, 'score': sum(c['earned'] for c in criteria) if complete else None,
            'max_score': sum(c['points'] for c in criteria), 'complete': complete, 'critical_passed': critical_passed,
            'evidence_digest': result.get('evidence_digest') if result else None,
            'unavailable_reason': None if complete else 'Current complete named measurements are unavailable or execution/context is unresolved.'}


def _qualified(w, con, state):
    qualified = {}
    for row in con.execute('SELECT id,data FROM submissions').fetchall():
        if json.loads(row['data'])['task_id'] != state['task_id']:
            continue
        item = w._item(con, row['id'])
        if item['result']:
            w._verify_result(item['result'])
        score = score_item(state, item)
        if (score['role'] in ('reference','alternate') and score['complete'] and score['score'] == score['max_score']
                and score['critical_passed'] is True and score['overall'] == 'passed'):
            qualified[score['role']] = {'submission_id': item['id'], 'patch_digest': item['patch_digest'],
                                        'evidence_digest': item['result']['evidence_digest']}
    return qualified


def review_task(w, task_id, *, decision, reason, findings, expected_revision, operation_key,
                actor='operator', reviewer_mode='ai_assisted_adjudication'):
    initial = context(w, task_id)
    require(isinstance(decision, str) and decision in ('approved','needs-repair','quarantined') and _nonempty(reason),
            'A task decision and reason are required.', 'invalid-task-review')
    _actor(actor, reviewer_mode); _findings(findings)
    payload = {'context_id': initial['id'], 'decision': decision, 'reason': reason, 'findings': findings,
               'expected_revision': expected_revision, 'actor': actor, 'reviewer_mode': reviewer_mode}
    with w.store.transaction() as con:
        prior = w.store.operation(con, 'task-review', operation_key, payload)
        if prior is not None:
            return prior
        state = _load(w, con, initial['id'])
        require(type(expected_revision) is int and expected_revision == state['revision'],
                'Task revision changed; reload current quality context.', 'stale-task-review', 409)
        require({f['id'] for f in state['findings']}.issubset({f['id'] for f in findings}),
                'Retain previous findings and resolve them explicitly.', 'invalid-findings')
        qualification = {}
        if decision == 'approved':
            require(state['evaluation']['kind'] == 'clean', 'Audit challenges cannot enter the clean task set.', 'task-ineligible', 422)
            require(not any(f['status'] == 'open' and f['severity'] in ('high','critical') for f in findings),
                    'Resolve open high/critical findings before approval.', 'task-ineligible', 422)
            qualification = _qualified(w, con, state)
            require(set(qualification) == {'reference','alternate'},
                    'Approval requires current passing reference and alternate evidence.', 'task-ineligible', 422)
        quality = {'decision': decision, 'reason': reason, 'actor': actor, 'reviewer_mode': reviewer_mode,
                   'previous_revision': state['revision'], 'qualification': qualification}
        state = state | {'revision': state['revision'] + 1, 'quality': quality, 'findings': findings}
        response = _save(w, con, state, 'task-quality-reviewed', actor)
        w.store.remember(con, 'task-review', operation_key, payload, response)
        return response


def record_calibration(w, task_id, *, reviews, reason, author_feedback, guideline_update, operation_key, actor='operator'):
    initial = context(w, task_id)
    require(_nonempty(reason) and _nonempty(author_feedback) and _nonempty(guideline_update),
            'Calibration needs reason, author feedback and guideline update.', 'invalid-calibration')
    require(isinstance(reviews, list) and len(reviews) >= 2, 'Calibration requires at least two separately recorded reviews.', 'invalid-calibration')
    ids = []
    for review in reviews:
        require(isinstance(review, dict) and all(_nonempty(review.get(k)) for k in ('review_id','actor','decision','reason'))
                and review.get('reviewer_mode') == 'ai_assisted_adjudication'
                and review.get('decision') in ('approved','needs-repair','quarantined')
                and all(isinstance(review.get(k), str) and HEX.fullmatch(review[k]) for k in ('input_digest','output_digest')),
                'Reviews need unique IDs, actual AI-assisted attribution, judgments and input/output SHA-256 digests.', 'invalid-calibration')
        ids.append(review['review_id'])
    require(len(ids) == len(set(ids)) and _nonempty(actor), 'Review IDs must be distinct and an actor is required.', 'invalid-calibration')
    decisions = [r['decision'] for r in reviews]
    pairs = len(reviews) * (len(reviews)-1) // 2
    matches = sum(left == right for i,left in enumerate(decisions) for right in decisions[i+1:])
    record = {'reviews': reviews, 'reason': reason, 'author_feedback': author_feedback, 'guideline_update': guideline_update,
              'actor': actor, 'agreement': {'matching_pairs': matches, 'pairs': pairs, 'value': matches / pairs,
              'origin': 'separately_recorded_ai_assisted_reviews', 'interpretation': 'Declared judgments; agreement is not correctness or independent human evidence.'}}
    payload = {'context_id': initial['id'], **record}
    with w.store.transaction() as con:
        prior = w.store.operation(con, 'task-calibration', operation_key, payload)
        if prior is not None:
            return prior
        state = _load(w, con, initial['id'])
        response = _save(w, con, state | {'revision': state['revision'] + 1, 'calibration': [*state['calibration'], record]},
                         'task-calibration-recorded', actor)
        w.store.remember(con, 'task-calibration', operation_key, payload, response)
        return response


def score_snapshot(state, snapshot):
    require(all(item['task_id'] == state['task_id'] for item in snapshot['items']),
            'This evaluation slice supports one exact task per batch.', 'evaluation-task-mismatch', 422)
    items = [score_item(state, item) for item in snapshot['items']]
    scores = [item['score'] for item in items if item['complete']]
    findings = state['findings']
    events = [e for e in snapshot['audit'] if e['payload'].get('context_id') == state['id']]
    summary = {'task_count': 1, 'unique_submissions': len(items), 'complete_scores': len(scores),
               'unassessed_scores': len(items)-len(scores), 'quality': state['quality']['decision'],
               'role_counts': dict(sorted(Counter(i['role'] for i in items).items())),
               'finding_categories': dict(sorted(Counter(f['kind'] for f in findings).items())),
               'open_findings': sum(f['status'] == 'open' for f in findings),
               'task_reviews': sum(e['kind'] == 'task-quality-reviewed' for e in events),
               'repair_requests': sum(e['kind'] == 'task-quality-reviewed' and e['payload'].get('decision') == 'needs-repair' for e in events),
               'score_spread': {'count': len(scores), 'min': min(scores) if scores else None, 'max': max(scores) if scores else None},
               'review_duration': None}
    return {'context': state, 'items': items, 'summary': summary, 'batch_id': snapshot['batch']['id'], 'cut': snapshot['cut']}


def score_batch(w, batch_id):
    w._ready()
    batch_items = w.submissions(batch_id)
    task_ids = {i['task_id'] for i in batch_items}
    require(len(task_ids) == 1, 'Evaluation batches must contain one task.', 'evaluation-task-mismatch', 422)
    initial = context(w, next(iter(task_ids)))
    with w.store.transaction(write=False) as con:
        state = _load(w, con, initial['id'])
        snapshot = w._snapshot(con, batch_id)
        return score_snapshot(state, snapshot)
