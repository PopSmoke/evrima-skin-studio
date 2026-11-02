"""Opt-in, bounded recovery copies in the ordinary editable-project format."""
import copy
import json
import os
from pathlib import Path
import tempfile
from skin_document import validate

MAX_BYTES = 1024 * 1024


def write_draft(path, document):
    """An unsuccessful write must leave the previous recovery file intact."""
    validate(document)
    text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Recovery copy exceeds 1 MB. Shorten imported notes or save a project manually.')
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                dir=destination.parent, prefix='.'+destination.name+'.', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            file.write(text); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass


class DraftRecovery:
    """Only the latest accepted design is queued. No thread, images or assets."""
    def __init__(self, root, report, delay_ms=1500):
        self.root = root; self.report = report; self.delay_ms = delay_ms
        self.path = None; self.timer = None; self.pending = None; self.last = None

    def cancel_timer(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer); self.timer = None

    def enable(self, path, document):
        # Write the newly selected destination before replacing an active setup.
        write_draft(path, document)
        self.cancel_timer(); self.path = Path(path); self.pending = None
        self.last = copy.deepcopy(document)
        self.report('Recovery saved: ' + str(self.path))

    def queue(self, document):
        if self.path is None: return
        self.cancel_timer()
        if document == self.last:
            self.pending = None
            self.report('Recovery is current: ' + str(self.path)); return
        self.pending = copy.deepcopy(validate(document))
        self.report('Recovery update pending: ' + str(self.path))
        self.timer = self.root.after(self.delay_ms, self.flush)

    def flush(self):
        self.cancel_timer()
        if self.path is None or self.pending is None: return True
        try:
            write_draft(self.path, self.pending)
        except (OSError, ValueError, TypeError) as error:
            self.report('Recovery not saved: ' + str(error) + ' Use Save copy now to retry.')
            return False
        self.last = self.pending; self.pending = None
        self.report('Recovery saved: ' + str(self.path))
        return True

    def stop(self):
        self.cancel_timer(); self.path = None; self.pending = None; self.last = None
        self.report('Recovery is off. Any existing recovery file is retained.')

    def close(self, flush=True):
        if flush and not self.flush(): return False
        self.cancel_timer(); return True
