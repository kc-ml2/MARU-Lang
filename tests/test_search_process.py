import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from maru_lang.services.search_process import OutputLimitReached, records


class SearchProcessTests(unittest.TestCase):
    def stream(self, script, **kwargs):
        return records(sys.executable, Path.cwd(), ['-c', script], separator=b'\n',
                       timeout=kwargs.get('timeout', 2),
                       max_output_bytes=kwargs.get('budget', 100000))

    def test_early_close_reaps_process(self):
        real_popen = subprocess.Popen
        children = []

        def start(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with patch('maru_lang.services.search_process.subprocess.Popen', side_effect=start):
            with closing(self.stream("import time; print('ready', flush=True); time.sleep(30)")) as output:
                self.assertEqual(next(output), b'ready')
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(children[0].stdout.closed)

    def test_timeout_with_no_output(self):
        with self.assertRaises(TimeoutError):
            list(self.stream('import time; time.sleep(30)', timeout=0.1))

    def test_stderr_is_drained_and_bounded(self):
        with self.assertRaises(OutputLimitReached):
            list(self.stream("import sys; sys.stderr.write('x' * 1000000)", budget=1024))

    def test_failed_process_reports_error(self):
        with self.assertRaisesRegex(ValueError, 'bad regex'):
            list(self.stream("import sys; sys.stderr.write('bad regex'); sys.exit(2)"))
