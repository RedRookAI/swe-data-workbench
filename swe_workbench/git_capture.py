"""Bounded exact output for local read-only Git plumbing."""
import os
import selectors
import subprocess
from .errors import WorkbenchError
from .intake import MAX_FILE_BYTES

READ_BYTES = 16384
DIAGNOSTIC_BYTES = 65536


def capture(argv, env, *, stdout_limit=MAX_FILE_BYTES, metrics=None):
    limits = {'stdout': stdout_limit, 'stderr': DIAGNOSTIC_BYTES}
    buffers = {name: bytearray() for name in limits}
    try:
        process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise WorkbenchError('bundle-git', 'Local Git plumbing is unavailable.') from exc
    try:
        with selectors.DefaultSelector() as selector:
            for name in limits:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                for key, _ in selector.select():
                    name = key.data
                    chunk = os.read(key.fd, min(READ_BYTES, limits[name] - len(buffers[name]) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if metrics is not None:
                        metrics['max_read'] = max(metrics.get('max_read', 0), len(chunk))
                    if len(buffers[name]) + len(chunk) > limits[name]:
                        raise WorkbenchError('bundle-git-size', f'Git {name} exceeds its {limits[name]}-byte capture limit; exact input refused.')
                    buffers[name].extend(chunk)
                    if metrics is not None:
                        metrics[name] = max(metrics.get(name, 0), len(buffers[name]))
            code = process.wait()
        return code, bytes(buffers['stdout']), bytes(buffers['stderr'])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()
