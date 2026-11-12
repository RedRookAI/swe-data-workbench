"""Resolve an explicitly selected data-only profile into the normal capture input."""
from .handoff_context import PROFILE, V2
from .store import canonical, digest
from .handoff import require
from . import handoff_validation as shape


def expand(profile, *, change_id, title, goal):
    required = {'schema', 'id', 'version', 'repository', 'observations'}
    shape.obj(profile,'profile',required,('subjects','relationships','attachments'))
    for k in ('schema','id','version','repository'):shape.text(profile[k],'profile.'+k)
    shape.observation_requests(profile['observations'],V2)
    require(isinstance(profile, dict) and required <= set(profile) <= required | {'subjects', 'relationships', 'attachments'}, 'Profile has missing or unsupported fields.')
    require(profile['schema'] == PROFILE, 'Unsupported project profile version.')
    require(all(isinstance(profile[k], str) and profile[k].strip() for k in ('id', 'version', 'repository')), 'Profile identity/version/repository are required.')
    require(not profile['repository'].startswith(('/', '~')) and '@' not in profile['repository'], 'Use a project label or credential-free repository URL, not a host path or credential.')
    require(all(isinstance(v, str) and v.strip() for v in (change_id, title, goal)), 'Supply this change ID, title and requested goal explicitly.')
    require(isinstance(profile['observations'], list), 'Profile observations must be a list.')
    attachments = profile.get('attachments', [])
    require(isinstance(attachments, list) and all(isinstance(v, str) and v and v not in ('.','..') and '/' not in v and '\\' not in v for v in attachments) and len(set(attachments))==len(attachments), 'Profile attachments are unique names, never filesystem paths.')
    return {'schema': V2, 'change_id': change_id, 'title': title, 'goal': goal, 'repository': profile['repository'],
            'observations': profile['observations'], 'subjects': profile.get('subjects', [{'id': 'product', 'role': 'product_source', 'selector': {'source': 'candidate'}}]),
            'relationships': profile.get('relationships', []), 'profile': {'sha256': digest(canonical(profile)), 'definition': profile}}


def bind_directory(profile, directory, explicit):
    from pathlib import Path
    root = Path(directory).resolve()
    require(root.is_dir(), 'Select an existing evidence directory.')
    result = dict(explicit)
    for name in profile.get('attachments', []):
        require(name not in result, 'Choose directory binding or an explicit file for each evidence slot, not both.')
        source = root / name
        require(not source.is_symlink() and source.is_file(), 'A declared evidence slot is missing or a symlink: ' + name)
        result[name] = source
    return result
