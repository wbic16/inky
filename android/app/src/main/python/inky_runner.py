"""Thin Android runner for inky.

Drives the *unmodified* inky engine through its own CLI surface:
inky.main(argv) with a real input file, --dict / --protect pointing at the
bundled data files, --report pointing at a report file, and stdout
redirected to an in-memory buffer (inky writes corrected text to
sys.stdout.buffer and the analysis report to the --report file).
No engine logic lives here.
"""
import io
import os
import sys


class _StdoutCapture:
    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("latin-1", "replace")
        self.buffer.write(data)
        return len(data)

    def flush(self):
        pass


def run(text, workdir, datadir):
    import inky  # the bundled, unmodified engine (inky.py)

    os.makedirs(workdir, exist_ok=True)
    input_path = os.path.join(workdir, "inky_input.txt")
    report_path = os.path.join(workdir, "inky_report.txt")
    with open(input_path, "wb") as f:
        f.write(text.encode("latin-1", "replace"))

    argv = [input_path, "--report", report_path]
    dict_path = os.path.join(datadir, "words-en.txt")
    if os.path.isfile(dict_path):
        argv += ["--dict", dict_path]
    protect_path = os.path.join(datadir, "protect.txt")
    if os.path.isfile(protect_path):
        argv += ["--protect", protect_path]

    capture = _StdoutCapture()
    old_stdout = sys.stdout
    sys.stdout = capture
    try:
        inky.main(argv)
    finally:
        sys.stdout = old_stdout

    corrected = capture.buffer.getvalue().decode("latin-1")
    report = ""
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8", errors="replace") as f:
            report = f.read()
    if not report.strip():
        report = "(no findings - inky is happy with this text)"
    return corrected + "\n<<<INKY_REPORT>>>\n" + report
