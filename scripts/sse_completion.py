"""Incremental SSE completion framing; no JSON substring matching or EOF guessing."""
class SSECompletion:
    def __init__(self):
        self.pending = b''
        self.skip_lf = False
        self.data = []
        self.saw_sse = False
        self.done = False
        self.consumed = 0
        self.done_offset = None

    def feed(self, chunk):
        if self.done:
            return
        if self.skip_lf and chunk:
            self.skip_lf = False
            if chunk.startswith(b"\n"):
                chunk = chunk[1:]
                self.consumed += 1
        self.pending += chunk
        offset = 0
        while offset < len(self.pending):
            lf = self.pending.find(b'\n', offset)
            cr = self.pending.find(b'\r', offset)
            positions = [x for x in (lf, cr) if x >= 0]
            if not positions:
                break
            end = min(positions)
            if self.pending[end:end+1] == b'\r' and end + 1 == len(self.pending):
                self.skip_lf = True
            width = 2 if self.pending[end:end+2] == b'\r\n' else 1
            line = self.pending[offset:end]
            offset = end + width
            if not line:
                if b'\n'.join(self.data) == b'[DONE]':
                    self.done = True
                    self.done_offset = self.consumed + offset
                    break
                self.data.clear()
            elif line.startswith(b':'):
                self.saw_sse = True
            else:
                field, separator, value = line.partition(b':')
                if field in (b'data', b'event', b'id', b'retry'):
                    self.saw_sse = True
                if field == b'data':
                    self.data.append(value[1:] if value.startswith(b' ') else value)
        self.consumed += offset
        self.pending = self.pending[offset:]
