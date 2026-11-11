"""Prepare an operator-admitted task from committed blobs, without execution."""
from __future__ import annotations

import ctypes
import errno
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile

from .core import CRITERIA
from .errors import WorkbenchError
from .intake import MAX_FILE_BYTES, read_jsonl, reject_constant
from .store import canonical, digest


def _fail(code, message):
    raise WorkbenchError(code, message)


def _read(path):
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise WorkbenchError('bundle-input', 'A selected input file cannot be read.') from exc
    if len(data) > MAX_FILE_BYTES:
        _fail('bundle-size', f'Selected inputs must each fit the existing {MAX_FILE_BYTES}-byte intake limit.')
    return data


def _text(data, label):
    try:
        value = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise WorkbenchError('bundle-encoding', f'{label} must contain UTF-8 text.') from exc
    if any(ord(char) < 32 and char not in '\r\n\t' for char in value):
        _fail('bundle-binary', f'{label} contains unsupported binary/control bytes.')
    return value


def _json(path):
    try:
        value = json.loads(_text(_read(path), 'JSON input'), parse_constant=reject_constant)
        canonical(value)
        return value
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise WorkbenchError('bundle-json', 'Selected JSON input is invalid.') from exc


def _metadata(value, label, *, repository=False):
    keys = ('origin', 'license', 'repository') if repository else ('origin', 'license')
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip() for k in keys):
        _fail('bundle-provenance', f'{label} requires nonempty ' + ', '.join(keys) + ' fields.')
    return value


def _source_path(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        _fail('bundle-path', 'Selected repository paths must be nonempty relative text paths.')
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(p in ('.', '..', '.git') for p in path.parts):
        _fail('bundle-path', 'Selected repository paths must be canonical relative paths without .git or traversal.')
    return value


def _git(repo, *args, missing_ok=False):
    env = {'PATH': os.defpath, 'LC_ALL': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_NO_REPLACE_OBJECTS': '1',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_LAZY_FETCH': '1'}
    try:
        process = subprocess.run(['git', '--no-pager', '--literal-pathspecs', '-C', str(repo),
                                  *args], env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise WorkbenchError('bundle-git', 'Local Git plumbing is unavailable.') from exc
    if process.returncode and not (missing_ok and process.returncode == 1):
        _fail('bundle-git', 'Git could not read the selected repository, commit or tracked object.')
    return process.stdout


def _checks(value):
    if not isinstance(value, list) or not value:
        _fail('bundle-checks', 'Checks JSON must be a nonempty list of name/argv/timeout objects.')
    names = set()
    for check in value:
        if (not isinstance(check, dict) or set(check) != {'name', 'argv', 'timeout'}
                or not isinstance(check['name'], str) or not check['name'].strip() or check['name'] in names
                or not isinstance(check['argv'], list) or not check['argv']
                or any(not isinstance(arg, str) or '\x00' in arg for arg in check['argv']) or not check['argv'][0]
                or type(check['timeout']) not in (int, float) or not math.isfinite(check['timeout']) or check['timeout'] <= 0):
            _fail('bundle-checks', 'Every check needs a unique name, nonempty argv command and positive finite timeout.')
        names.add(check['name'])
    return value


def _verifiers(value):
    if not isinstance(value, dict) or not value:
        _fail('bundle-verifier', 'Verifier files must be a nonempty mapping of relative paths to UTF-8 text.')
    for relative, text in value.items():
        _source_path(relative)
        if not isinstance(text, str):
            _fail('bundle-verifier', 'Verifier file contents must be text.')
        _text(text.encode('utf-8'), 'Protected verifier')
        if any(parent.as_posix() in value for parent in PurePosixPath(relative).parents if parent.as_posix() != '.'):
            _fail('bundle-verifier', 'Verifier file paths cannot overlap as files and directories.')
    return value


def _evaluation(value, check_names, patch_digests):
    if not isinstance(value, dict):
        _fail('bundle-evaluation', 'Evaluation metadata must be an object.')
    if (not isinstance(value.get('family'), str) or not value['family'].strip()
            or type(value.get('version')) not in (str, int) or not value['version']
            or value.get('kind') not in ('audit_challenge', 'clean')):
        _fail('bundle-evaluation', 'Evaluation family, version and audit_challenge/clean kind are required.')
    requirements, rubric = value.get('requirements'), value.get('rubric')
    if not isinstance(requirements, list) or not requirements or not isinstance(rubric, list) or not rubric:
        _fail('bundle-evaluation', 'Evaluation requires nonempty requirements and rubric lists.')
    ids = set()
    for requirement in requirements:
        if (not isinstance(requirement, dict) or not isinstance(requirement.get('id'), str)
                or not requirement['id'].strip() or requirement['id'] in ids
                or not isinstance(requirement.get('text'), str) or not requirement['text'].strip()):
            _fail('bundle-evaluation', 'Requirements need unique IDs and nonempty text.')
        ids.add(requirement['id'])
    ids = set()
    for criterion in rubric:
        if (not isinstance(criterion, dict) or not isinstance(criterion.get('id'), str)
                or not criterion['id'].strip() or criterion['id'] in ids
                or type(criterion.get('points')) is not int or criterion['points'] < 0
                or type(criterion.get('critical')) is not bool
                or not isinstance(criterion.get('checks'), list) or not criterion['checks']
                or any(not isinstance(name, str) or name not in check_names for name in criterion['checks'])):
            _fail('bundle-evaluation', 'Rubric criteria need unique IDs, nonnegative points, known checks and boolean critical.')
        ids.add(criterion['id'])
    for name in ('reference_patch_digest', 'alternate_patch_digest'):
        key = value.get(name)
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key) or key not in patch_digests:
            _fail('bundle-evaluation', 'Reference and alternate roles must name exact admitted patch digests.')
    return value


def _publish(temporary, output):
    """Linux atomic directory publication that cannot replace an existing path."""
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, 'renameat2', None)
    if rename is None:
        _fail('bundle-publication', 'Atomic no-replace directory publication is unavailable on this platform.')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(temporary), -100, os.fsencode(output), 1):
        number = ctypes.get_errno()
        if number in (errno.EEXIST, errno.ENOTEMPTY):
            _fail('bundle-output', 'The output path already exists; select a fresh directory.')
        raise OSError(number, 'Atomic bundle publication failed')


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_bundle(*, repo, commit, task_id, task_text, sources, checks, candidates,
                   provenance, notices, output, predictions=None, input_format='native', name=None, title=None,
                   verifier_files=None, evaluation=None):
    """Select committed text and explicitly admitted patches into a fresh bundle.

    Config JSON and exact patch/prediction bytes are read locally. The selected
    check argv is recorded; no task/check/patch is executed or applied here.
    """
    repo = Path(repo).resolve()
    requested_output = Path(output)
    if requested_output.exists() or requested_output.is_symlink():
        _fail('bundle-output', 'The output path already exists; select a fresh directory.')
    output = requested_output.resolve()
    if not isinstance(commit, str) or not commit or commit.startswith('-') or '\x00' in commit:
        _fail('bundle-commit', 'An explicit local commit or revision is required.')
    if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
        _fail('bundle-task', 'Task ID must contain 1 to 200 characters.')
    if input_format not in ('native', 'swebench') or (predictions is None and input_format != 'native'):
        _fail('bundle-format', 'Select native or swebench for supplied predictions; generated predictions use native.')
    if not sources or not notices:
        _fail('bundle-selection', 'Select source files and applicable tracked notices explicitly.')
    if output.exists() or output.is_symlink():
        _fail('bundle-output', 'The output path already exists; select a fresh directory.')
    if not output.parent.is_dir():
        _fail('bundle-output', 'The output parent directory must already exist.')
    input_paths = [Path(value).resolve() for value in (task_text, checks, candidates, provenance)]
    if predictions is not None:
        input_paths.append(Path(predictions).resolve())
    input_paths.extend(Path(value).resolve() for value in (verifier_files, evaluation) if value is not None)
    # Refuse partial clones before object access: missing objects must never
    # trigger implicit network fetching during a read-only preparation.
    partial = _git(repo, 'config', '--local', '--get-regexp', r'^(extensions\.partialclone|remote\..*\.promisor)$', missing_ok=True)
    if partial.strip():
        _fail('bundle-repository', 'Partial/promisor repositories are unsupported; supply all selected objects locally.')
    bare = _git(repo, 'rev-parse', '--is-bare-repository').strip() == b'true'
    repo_root = repo if bare else Path(os.fsdecode(_git(repo, 'rev-parse', '--show-toplevel').strip())).resolve()
    git_dir = Path(os.fsdecode(_git(repo, 'rev-parse', '--absolute-git-dir').strip())).resolve()
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in (repo_root, git_dir, *input_paths)):
        _fail('bundle-overlap', 'Output must be separate from the source repository and selected inputs.')
    exact_commit = _git(repo, 'rev-parse', '--verify', '--end-of-options', commit + '^{commit}').decode('ascii').strip()
    selected = list(dict.fromkeys(_source_path(p) for p in [*sources, *notices]))
    source_files, source_summary = {}, []
    source_bytes = 0
    for relative in sorted(selected):
        entry = _git(repo, 'ls-tree', '-z', '--full-tree', exact_commit, '--', relative).split(b'\0')
        if len(entry) != 2 or not entry[0]:
            _fail('bundle-source', 'Selected path must identify exactly one tracked regular blob: ' + relative)
        header, actual_path = entry[0].split(b'\t', 1)
        mode, kind, object_id = header.decode('ascii').split()
        if actual_path != relative.encode('utf-8') or mode != '100644' or kind != 'blob':
            _fail('bundle-source', 'Only non-executable UTF-8 regular blobs are supported: ' + relative)
        size = int(_git(repo, 'cat-file', '-s', object_id))
        source_bytes += size
        if source_bytes > MAX_FILE_BYTES:
            _fail('bundle-size', f'Selected source bytes exceed the existing {MAX_FILE_BYTES}-byte input profile.')
        raw = _git(repo, 'cat-file', 'blob', object_id)
        source_files[relative] = _text(raw, 'Selected source ' + relative)
        source_summary.append({'path': relative, 'git_blob': object_id, 'mode': mode, 'sha256': digest(raw), 'bytes': len(raw)})
    text = _text(_read(task_text), 'Task text')
    if not text.strip():
        _fail('bundle-task', 'Task text must not be empty.')
    check_list = _checks(_json(checks))
    protected_files = _verifiers(_json(verifier_files)) if verifier_files is not None else None
    source_provenance = dict(_metadata(_json(provenance), 'Source provenance', repository=True))
    if source_provenance.get('base_commit', exact_commit) != exact_commit:
        _fail('bundle-provenance', 'Source provenance base_commit must match the resolved selected commit.')
    source_provenance['base_commit'] = exact_commit
    source_provenance['notice_files'] = ['notices/' + p for p in notices]
    selections = _json(candidates)
    if not isinstance(selections, list) or not selections:
        _fail('bundle-candidates', 'Candidates JSON must be a nonempty list of explicitly selected patches.')
    patch_data, patch_provenance, candidate_summary, generated = {}, {}, [], []
    for candidate in selections:
        if (not isinstance(candidate, dict) or set(candidate) != {'patch_file', 'model_name_or_path', 'provenance'}
                or not isinstance(candidate['patch_file'], str) or not candidate['patch_file']
                or not isinstance(candidate['model_name_or_path'], str) or not candidate['model_name_or_path'].strip()):
            _fail('bundle-candidates', 'Each candidate requires patch_file, model_name_or_path and provenance.')
        patch_path = Path(candidate['patch_file'])
        if not patch_path.is_absolute():
            patch_path = Path(candidates).resolve().parent / patch_path
        patch_path = patch_path.resolve()
        input_paths.append(patch_path)
        if output.is_relative_to(patch_path) or patch_path.is_relative_to(output):
            _fail('bundle-overlap', 'Output overlaps a selected candidate input.')
        raw = _read(patch_path)
        patch_text = _text(raw, 'Candidate patch')
        if not patch_text:
            _fail('bundle-candidates', 'Selected candidate patches must not be empty.')
        patch_digest = digest(raw)
        metadata = _metadata(candidate['provenance'], 'Candidate provenance')
        if patch_digest in patch_provenance and patch_provenance[patch_digest] != metadata:
            _fail('bundle-provenance', 'One exact patch cannot have conflicting admitted provenance.')
        patch_data[patch_digest] = raw
        patch_provenance[patch_digest] = metadata
        candidate_summary.append({'patch_digest': patch_digest, 'bytes': len(raw),
                                  'model_name_or_path': candidate['model_name_or_path'], 'provenance': metadata})
        generated.append({'schema_version': 1, 'task_id': task_id, 'patch': patch_text,
                          'model_name_or_path': candidate['model_name_or_path'], 'origin': metadata['origin'],
                          'source': metadata.get('source_url', source_provenance['repository'])})
    rubric = {'version': 1, 'criteria': list(CRITERIA)}
    task = {'title': title or task_id, 'task_text': text, 'source_files': source_files, 'checks': check_list,
            'patches': [raw.decode('utf-8') for raw in patch_data.values()], 'patch_provenance': patch_provenance,
            'origin': source_provenance['origin'], 'provenance': source_provenance}
    if protected_files is not None:
        task['verifier_files'] = protected_files
    if evaluation is not None:
        task['evaluation'] = _evaluation(_json(evaluation), {check['name'] for check in check_list}, set(patch_data))
    catalog = {'version': 1, 'name': name or task_id, 'title': title or task_id,
               'origin': source_provenance['origin'], 'prediction_file': 'predictions.jsonl',
               'prediction_format': input_format, 'provenance': source_provenance,
               'rubric': rubric, 'tasks': {task_id: task}}
    prediction_bytes = _read(predictions) if predictions is not None else b''.join(canonical(row) + b'\n' for row in generated)
    if len(prediction_bytes) > MAX_FILE_BYTES:
        _fail('bundle-size', 'Generated predictions exceed the existing intake file limit.')
    summary = {'schema': 'swe-workbench-bundle-preparation-v1', 'base_commit': exact_commit, 'task_id': task_id,
               'source_files': source_summary, 'source_digest': digest(canonical(source_files)),
               'check_digest': digest(canonical({'checks': check_list, 'verifier_files': protected_files}
                                                if protected_files is not None else check_list)), 'rubric_digest': digest(canonical(rubric)),
               'catalog_digest': digest(canonical(catalog)), 'checks': check_list, 'candidates': candidate_summary,
               'notices': source_provenance['notice_files'], 'prediction_format': input_format,
               'prediction_digest': digest(prediction_bytes), 'checks_executed': False,
               'execution_trust': 'The operator admits these exact patch/check tuples for trusted execution; preparation reads inputs only.'}
    if protected_files is not None:
        summary['verifier_digest'] = digest(canonical(protected_files))
    if evaluation is not None:
        summary['evaluation'] = task['evaluation']
    temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '-pending-', dir=output.parent))
    try:
        files = {'catalog.json': canonical(catalog) + b'\n', 'predictions.jsonl': prediction_bytes}
        files.update({'patches/' + key + '.patch': raw for key, raw in patch_data.items()})
        files.update({'notices/' + p: source_files[p].encode('utf-8') for p in notices})
        for relative, raw in files.items():
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        _, rows = read_jsonl(temporary / 'predictions.jsonl', input_format)
        if any(row['error'] for row in rows):
            _fail('bundle-predictions', 'Prediction input has invalid records: ' + ', '.join(sorted({r['error'] for r in rows if r['error']})))
        summary['prediction_records'] = len(rows)
        summary['unapproved_prediction_records'] = sum(row['record']['task_id'] != task_id or row['record'].get('patch') not in task['patches'] for row in rows)
        with (temporary / 'preparation.json').open('xb') as stream:
            stream.write(canonical(summary) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        for directory, _, _ in os.walk(temporary, topdown=False):
            _fsync_directory(directory)
        _publish(temporary, output)
        _fsync_directory(output.parent)
    except OSError as exc:
        raise WorkbenchError('bundle-publication', 'Bundle publication failed; inspect the selected output before retrying.') from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary
