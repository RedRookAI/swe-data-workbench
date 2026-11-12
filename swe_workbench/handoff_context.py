"""Small typed provenance and deterministic review comparisons, without execution."""
from .store import canonical, digest
from .errors import WorkbenchError
from . import handoff_validation as shape

V2 = 'swe-workbench-handoff/v2'
PROFILE = 'swe-workbench-handoff-profile/v1'
ROLES = {'product_source', 'qualification_workflow', 'consumer_fixture', 'released_artifact'}
RELATIONS = {'checks_source': 'qualification_workflow', 'fixture_for': 'consumer_fixture', 'built_from': 'released_artifact'}


def require(condition, message):
    if not condition:
        raise WorkbenchError('handoff-context', message)


def select(material, selector):
    from .handoff import field, parse
    require(isinstance(selector, dict), 'A subject needs an explicit data selector.')
    if selector == {'source': 'candidate'}:
        return material['candidate_revision'], 'captured-git-source'
    require(set(selector) == {'attachment', 'field_path'}, 'Unsupported subject selector; executable templates are not supported.')
    attachment = next((a for a in material['attachments'] if a['name'] == selector['attachment']), None)
    require(attachment is not None, 'Subject evidence attachment is missing.')
    value = field(parse(attachment['text']), selector['field_path'])
    require(value is None or isinstance(value, str), 'Subject identity must be a string or unknown.')
    return value, 'externally-reported'


def subjects(material):
    requests = material.get('subject_requests', [{'id': 'product', 'role': 'product_source', 'selector': {'source': 'candidate'}}])
    require(isinstance(requests, list) and requests, 'At least the product-source subject is required.')
    result = []
    for i, request in enumerate(requests):
        shape.selector(request.get("selector") if isinstance(request,dict) else None, f"subjects[{i}].selector")
        require(isinstance(request, dict) and set(request) == {'id', 'role', 'selector'}, 'Subject needs id, role and selector.')
        require(isinstance(request['id'], str) and request['id'].strip() and isinstance(request['role'], str) and request['role'] in ROLES, 'Unsupported subject ID or role.')
        if request['role'] == 'product_source':
            require(request['selector'] == {'source': 'candidate'}, 'A report or fixture cannot replace the captured product-source identity.')
        else:
            require('attachment' in request['selector'], 'Non-product identities require explicit evidence, not a guessed source role.')
        value, origin = select(material, request['selector'])
        result.append({**request, 'value': value, 'origin': origin, 'status': 'known' if value is not None else 'unknown'})
    require(len({s['id'] for s in result}) == len(result), 'Subject IDs must be unique.')
    require(sum(s['role'] == 'product_source' for s in result) == 1, 'Exactly one captured product-source subject is required.')
    return result


def relationships(material):
    from .handoff import field, parse
    lookup = {s['id']: s for s in material['subjects']}
    attachments = {a['name']: a for a in material['attachments']}
    requests = material.get('relationship_requests', [])
    require(isinstance(requests, list), 'Relationships must be a list.')
    result = []
    for request in requests:
        require(isinstance(request, dict) and set(request) == {'id', 'kind', 'from', 'to', 'reason', 'evidence'}, 'Relationship needs id, kind, from, to, reason and evidence.')
        require(all(isinstance(request[k], str) and request[k].strip() for k in ('id', 'reason')), 'Relationship ID and reason are required.')
        require(all(isinstance(request[k], str) for k in ('kind', 'from', 'to')) and request['kind'] in RELATIONS and request['from'] in lookup and request['to'] in lookup, 'Unknown relationship or subject.')
        source, target = lookup[request['from']], lookup[request['to']]
        require(source['role'] == RELATIONS[request['kind']] and target['role'] == 'product_source', 'Relationship roles do not match the stated subjects.')
        require(isinstance(request['evidence'], list), 'Relationship support must be explicit evidence references.')
        support = []
        for ref in request['evidence']:
            require(isinstance(ref, dict) and set(ref) in ({'attachment', 'field_path'}, {'attachment', 'field_path', 'matches_subject'}, {'attachment', 'quote'}), 'Unsupported relationship evidence reference.')
            shape.text(ref['attachment'], 'relationship.evidence.attachment')
            if 'matches_subject' in ref:shape.text(ref['matches_subject'],'relationship.evidence.matches_subject')
            require(ref['attachment'] in attachments, 'Relationship evidence attachment is missing.')
            attachment = attachments[ref['attachment']]
            if 'quote' in ref:
                require(isinstance(ref['quote'], str) and ref['quote'].strip(), 'A support quote must be nonempty.')
                value = ref['quote'] if ref['quote'] in attachment['text'] else None
            else:
                value = field(parse(attachment['text']), ref['field_path'])
            matched = None
            if 'matches_subject' in ref:
                require(ref['matches_subject'] in lookup, 'Unknown subject in relationship support.')
                expected = lookup[ref['matches_subject']]['value']
                matched = expected is not None and value == expected
            support.append({**ref, 'value': value, 'matches': matched, 'attachment_sha256': attachment['sha256']})
        matched_ids = {s.get('matches_subject') for s in support if s['matches'] is True}
        known = source['value'] is not None and target['value'] is not None and all(s['value'] is not None for s in support) and {request['from'], request['to']} <= matched_ids
        result.append({**request, 'support': support, 'status': 'declared-supported' if known else 'unknown',
                       'assurance': 'Evidence-referenced operator declaration; not authenticated execution or custody.'})
    require(len({r['id'] for r in result}) == len(result), 'Relationship IDs must be unique.')
    return result


def observation_binding(material, request, revision):
    lookup = {s['id']: s for s in material['subjects']}
    subject_id = request.get('subject', next(s['id'] for s in material['subjects'] if s['role'] == 'product_source'))
    shape.text(subject_id,'observation.subject')
    require(subject_id in lookup, 'Observation refers to an unknown subject.')
    subject = lookup[subject_id]
    if revision is None or subject['value'] is None:
        binding = 'unbound'
    elif revision != subject['value']:
        binding = 'declared-other-subject'
    else:
        binding = 'declared-same-source' if subject['role'] == 'product_source' else 'declared-same-subject'
    linked = any(r['from'] == subject_id and r['status'] == 'declared-supported' for r in material['relationships'])
    applies = binding == 'declared-same-source' or (binding == 'declared-same-subject' and linked)
    return {'subject': subject_id, 'subject_role': subject['role'], 'binding': binding, 'candidate_applicability': 'declared' if applies else 'unknown'}


def eligible(material):
    for observation in material['observations']:
        if not observation['required']:
            continue
        known = observation['value'] is not None
        bound = observation.get('candidate_applicability') == 'declared' if material['schema'] == V2 else observation['binding'] == 'declared-same-source'
        if not known or not bound:
            return False
    return True


def _changes(before, after, key):
    require(len({v[key] for v in before})==len(before) and len({v[key] for v in after})==len(after), 'Comparison keys are ambiguous; preserve the legacy input and clarify its labels in a new material version.')
    left, right = {v[key]: v for v in before}, {v[key]: v for v in after}
    return {'added': sorted(right.keys() - left.keys()), 'removed': sorted(left.keys() - right.keys()),
            'changed': sorted(k for k in left.keys() & right.keys() if canonical(left[k]) != canonical(right[k]))}


def compare(state, material, events, artifacts, baseline_revision=None):
    from .handoff import parse
    candidates = [e for e in events if e['kind'] == 'handoff-reviewed' and e['payload']['revision'] < state['revision']]
    if baseline_revision is not None:
        require(type(baseline_revision) is int, 'Comparison revision must be an integer.')
        candidates = [e for e in candidates if e['payload']['revision'] == baseline_revision]
        require(bool(candidates), 'Select an earlier reviewed revision of this same change.')
    if not candidates:
        return {'baseline_revision': None, 'current_revision': state['revision'], 'status': 'no-prior-reviewed-state'}
    event = candidates[-1]
    old = parse(artifacts[event['payload']['state_digest']])
    previous = parse(artifacts[old['material_digest']])
    require(old['change_id'] == state['change_id'], 'Comparison change identities differ.')
    source_keys = ('base_revision', 'candidate_revision', 'patch_sha256', 'files', 'goal')
    source_same = all(canonical(previous[k]) == canonical(material[k]) for k in source_keys)
    roles_same = all(canonical(previous.get(k, [])) == canonical(material.get(k, [])) for k in ('subjects', 'relationships'))
    prior_obs = {o['label']: o for o in previous['observations']}
    applicability = []
    for observation in material['observations']:
        prior = prior_obs.get(observation['label'])
        bound = observation.get('candidate_applicability') == 'declared' if material['schema'] == V2 else observation['binding'] == 'declared-same-source'
        if not bound:
            status = 'unknown-applicability'
        elif prior is not None and canonical(prior) == canonical(observation) and source_same and roles_same:
            status = 'unchanged-reported-binding'
        else:
            status = 'changed-context-needs-review'
        applicability.append({'label': observation['label'], 'status': status})
    reviews = {k: {'before': old.get(k), 'after': state.get(k)} for k in ('decision', 'reason', 'findings', 'next_action', 'responsible_party', 'actor', 'reviewer_mode') if canonical(old.get(k)) != canonical(state.get(k))}
    request_changes = {k: {'before': previous.get(k), 'after': material.get(k)} for k in ('title', 'goal') if canonical(previous.get(k)) != canonical(material.get(k))}
    if canonical(previous.get('profile')) != canonical(material.get('profile')):
        request_changes['profile'] = {'before': (previous.get('profile') or {}).get('sha256'), 'after': (material.get('profile') or {}).get('sha256')}
    return {'baseline_revision': old['revision'], 'current_revision': state['revision'], 'baseline_material_digest': old['material_digest'],
            'current_material_digest': state['material_digest'], 'status': 'compared', 'source_context_changed': not source_same,
            'request_changes': request_changes,
            'files': _changes(previous['files'], material['files'], 'path'), 'evidence': _changes(previous['attachments'], material['attachments'], 'name'),
            'observations': _changes(previous['observations'], material['observations'], 'label'), 'subjects': _changes(previous.get('subjects', []), material.get('subjects', []), 'id'),
            'relationships': _changes(previous.get('relationships', []), material.get('relationships', []), 'id'), 'review_changes': reviews,
            'applicability': applicability, 'claim': 'A comparison does not execute checks, infer semantic coverage or carry an old approval forward.'}
