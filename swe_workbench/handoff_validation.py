"""Small strict shape checks shared by handoff boundaries; no normalization."""
import re
from .errors import WorkbenchError
from .intake import MAX_RECORDS


def check(condition, path, expected):
    if not condition:
        raise WorkbenchError('handoff-field', f'{path}: {expected}')


def obj(value, path, required=(), optional=()):
    check(isinstance(value, dict), path, 'expected an object')
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    check(not missing, path, 'missing fields: ' + ', '.join(sorted(missing)))
    check(not extra, path, 'unsupported fields: ' + ', '.join(sorted(extra)))
    return value


def text(value, path, *, empty=False, nullable=False):
    if nullable and value is None:
        return
    check(isinstance(value, str), path, 'expected text')
    check(empty or bool(value.strip()), path, 'expected nonempty text')
    check(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), path, 'expected valid Unicode text')


def array(value, path):
    check(isinstance(value, list) and len(value) <= MAX_RECORDS, path, f'expected an array of at most {MAX_RECORDS} entries')


def integer(value, path):
    check(type(value) is int and value >= 0, path, 'expected a nonnegative integer')


def sha(value, path, *, git=False):
    check(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}' if not git else '(?:[0-9a-f]{40}|[0-9a-f]{64})', value), path, 'expected a full hexadecimal digest')


def selector(value, path):
    check(isinstance(value, dict), path, 'expected an object selector')
    if value == {'source': 'candidate'}:
        return
    obj(value, path, ('attachment', 'field_path'))
    text(value['attachment'], path + '.attachment')
    keys(value['field_path'], path + '.field_path')


def keys(value, path):
    array(value, path)
    for i, key in enumerate(value):
        text(key, f'{path}[{i}]', empty=True)


def observation_requests(value, version):
    array(value, 'observations')
    for i, item in enumerate(value):
        path = f'observations[{i}]'
        obj(item, path, ('label', 'attachment', 'field_path', 'required', 'scope'), ('context_path', 'subject') if version.endswith('/v2') else ('context_path',))
        for k in ('label', 'attachment', 'scope'):
            text(item[k], path + '.' + k)
        check(type(item['required']) is bool, path + '.required', 'expected a boolean')
        keys(item['field_path'], path + '.field_path')
        if 'context_path' in item:
            keys(item['context_path'], path + '.context_path')
        if 'subject' in item:
            text(item['subject'], path + '.subject')


def state(value, path='state'):
    obj(value, path, ('schema', 'change_id', 'revision', 'material_digest', 'decision', 'reason', 'findings', 'next_action', 'reviewer_mode', 'actor'), ('responsible_party',))
    for k in ('schema', 'change_id', 'decision', 'next_action'):
        text(value[k], path + '.' + k)
    text(value['reason'], path + '.reason', empty=True)
    for k in ('reviewer_mode', 'actor', 'responsible_party'):
        if k in value:
            text(value[k], path + '.' + k, nullable=True)
    integer(value['revision'], path + '.revision')
    sha(value['material_digest'], path + '.material_digest')
    array(value['findings'], path + '.findings')
    for i, finding in enumerate(value['findings']):
        text(finding, f'{path}.findings[{i}]')


def material(value):
    common = {'schema', 'title', 'goal', 'repository', 'base_revision', 'candidate_revision', 'files', 'patch', 'patch_sha256', 'attachments', 'observation_requests', 'observations', 'assurance'}
    obj(value, 'material', common, ('profile', 'subject_requests', 'relationship_requests', 'subjects', 'relationships'))
    if value['schema']=='swe-workbench-handoff/v2':
        check({'profile','subjects','subject_requests','relationships','relationship_requests'} <= value.keys(),'material','v2 role/profile fields are missing')
    for k in ('schema', 'title', 'goal', 'repository', 'assurance', 'patch'):
        text(value[k], 'material.' + k, empty=k == 'patch')
    for k in ('base_revision', 'candidate_revision'):
        sha(value[k], 'material.' + k, git=True)
    sha(value['patch_sha256'], 'material.patch_sha256')
    observation_requests(value['observation_requests'], value['schema'])
    for k in ('files', 'attachments', 'observations'):
        array(value[k], 'material.' + k)
    for i, f in enumerate(value['files']):
        path = f'material.files[{i}]'
        obj(f, path, ('path', 'before', 'after'))
        text(f['path'], path + '.path')
        for phase in ('before', 'after'):
            blob = f[phase]
            if blob is not None:
                obj(blob, path + '.' + phase, ('text', 'git_blob', 'sha256'))
                text(blob['text'], path + '.' + phase + '.text', empty=True)
                sha(blob['git_blob'], path + '.' + phase + '.git_blob', git=True)
                sha(blob['sha256'], path + '.' + phase + '.sha256')
    for i, a in enumerate(value['attachments']):
        path = f'material.attachments[{i}]'
        obj(a, path, ('name', 'text', 'sha256'))
        text(a['name'], path + '.name')
        text(a['text'], path + '.text', empty=True)
        sha(a['sha256'], path + '.sha256')
    for k in ('subjects', 'relationships', 'subject_requests', 'relationship_requests'):
        if k in value:
            array(value[k], 'material.' + k)
    if value.get('profile') is not None:
        obj(value['profile'], 'material.profile', ('sha256', 'definition'))
        sha(value['profile']['sha256'], 'material.profile.sha256')


def manifest(value, files):
    obj(value, 'manifest', ('schema', 'change_id', 'revision', 'files'))
    text(value['schema'], 'manifest.schema')
    text(value['change_id'], 'manifest.change_id')
    integer(value['revision'], 'manifest.revision')
    obj(value['files'], 'manifest.files', set(files) - {'manifest.json'})
    for name, entry in value['files'].items():
        obj(entry, 'manifest.files.' + name, ('bytes', 'sha256'))
        integer(entry['bytes'], 'manifest.files.' + name + '.bytes')
        sha(entry['sha256'], 'manifest.files.' + name + '.sha256')
