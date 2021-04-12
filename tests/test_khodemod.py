from __future__ import absolute_import

from slicker import khodemod

import base


class PathFilterTest(base.TestBase):
    def test_resolve_paths(self):
        self.write_file('foo.py', '')
        self.write_file('bar/baz.py', '')
        self.write_file('.dotfile.py', '')
        self.write_file('.dotdir/something.py', '')
        self.write_file('foo_extensionless_py', '')
        self.write_file('foo.js', '')
        self.write_file('foo.css', '')
        self.write_file('genfiles/qux.py', '')
        self.write_file('build/qux.py', '')

        self.assertItemsEqual(
            khodemod.resolve_paths(
                khodemod.default_path_filter(self.tmpdir),
                root=self.tmpdir),
            ['foo.py', 'bar/baz.py', 'build/qux.py'])

        self.assertItemsEqual(
            khodemod.resolve_paths(
                khodemod.default_path_filter(
                    self.tmpdir,
                    exclude_paths=('genfiles', 'build')),
                root=self.tmpdir),
            ['foo.py', 'bar/baz.py'])

        self.assertItemsEqual(
            khodemod.resolve_paths(
                khodemod.default_path_filter(
                    self.tmpdir,
                    extensions=('js', 'css'), include_extensionless=True),
                root=self.tmpdir),
            ['foo_extensionless_py', 'foo.js', 'foo.css'])
