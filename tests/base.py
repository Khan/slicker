from __future__ import absolute_import

import os
import shutil
import tempfile
import unittest

from slicker import khodemod


class TestBase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmpdir = os.path.realpath(
            tempfile.mkdtemp(prefix=(self.__class__.__name__ + '.')))
        self.error_output = []
        # Poor-man's mock.
        _old_emit = khodemod.emit

        def restore_emit():
            khodemod.emit = _old_emit
        self.addCleanup(restore_emit)
        khodemod.emit = lambda txt: self.error_output.append(txt)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def join(self, *args):
        return os.path.join(self.tmpdir, *args)

    def copy_file(self, filename):
        """Copy a file from testdata to tmpdir."""
        shutil.copyfile(os.path.join('testdata', filename),
                        os.path.join(self.tmpdir, filename))

    def write_file(self, filename, contents):
        if not os.path.exists(self.join(os.path.dirname(filename))):
            os.makedirs(os.path.dirname(self.join(filename)))
        with open(self.join(filename), 'w') as f:
            f.write(contents)
        # We may have a cached path-resolution; if we made a new file, it's now
        # wrong.  (We could instead call khodemod.write_file which does this
        # more precisely, but this is more convenient.)
        khodemod._RESOLVE_PATHS_CACHE.clear()

    def assertFileIs(self, filename, expected):
        with open(self.join(filename)) as f:
            actual = f.read()
        self.assertMultiLineEqual(expected, actual)

    def assertFileIsNot(self, filename):
        self.assertFalse(os.path.exists(self.join(filename)))
