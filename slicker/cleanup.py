"""Suggestors relating to cleaning up after the contentful changes we've made.

This file contains the suggestors (see khodemod.py) which pertain to cleaning
up any non-contentful problems potentially introduced by the changes we've made
-- things like fixing whitespace and sorting imports.  These are used by
slicker.slicker.make_fixes after it does all its other work.
"""
from __future__ import absolute_import

import ast
import difflib
import os
import sys

from fix_includes import fix_python_imports

from . import util
from . import khodemod


def remove_empty_files_suggestor(filename, body):
    """Suggestor to remove any empty files we leave behind.

    We also remove the file if it has only __future__ imports.  If all that's
    left is docstrings, comments, and non-__future__ imports, we warn but don't
    remove it.  (We ignore __init__.py files since those are often
    intentionally empty or kept only for some imports.)
    """
    if os.path.basename(filename) == '__init__.py':
        # Ignore __init__.py files.
        return

    file_info = util.File(filename, body)

    has_docstrings_comments_or_imports = '#' in body
    for stmt in file_info.tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Str):
            # A docstring.
            has_docstrings_comments_or_imports = True
        elif isinstance(stmt, ast.ImportFrom) and stmt.module == '__future__':
            # A __future__ import, which won't force us to keep the file.
            pass
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            # A non-__future__ import.
            has_docstrings_comments_or_imports = True
        else:
            # Some real code; we don't want to do anything.
            return

    # If we've gotten here, there's no "real code".
    if has_docstrings_comments_or_imports:
        yield khodemod.WarningInfo(
            filename, 0, "This file looks mostly empty; consider removing it.")
    else:
        # It's actually empty, so we can just go ahead and remove.
        yield khodemod.Patch(filename, body, None, 0, len(body))


def remove_leading_whitespace_suggestor(filename, body):
    """Suggestor to remove any leading whitespace we leave behind."""
    lstripped_body = body.lstrip()
    if lstripped_body != body:
        whitespace_len = len(body) - len(lstripped_body)
        yield khodemod.Patch(filename, body[:whitespace_len], '',
                             0, whitespace_len)


class _FakeOptions(object):
    """A fake `options` object to pass in to fix_python_imports."""
    def __init__(self, project_root):
        self.safe_headers = True
        self.root = project_root


def import_sort_suggestor(project_root):
    """Suggestor to fix up imports in a file."""
    fix_imports_flags = _FakeOptions(project_root)

    def suggestor(filename, body):
        """`filename` relative to project_root."""
        # TODO(benkraft): merge this with the import-adding, so we just show
        # one diff to add in the right place, unless there is additional
        # sorting to do.
        # Now call out to fix_python_imports to do the import-sorting
        change_record = fix_python_imports.ChangeRecord('fake_file.py')

        # A modified version of fix_python_imports.GetFixedFile
        # NOTE: fix_python_imports needs the rootdir to be on the
        # path so it can figure out third-party deps correctly.
        # (That's in addition to having it be in FakeOptions, sigh.)
        try:
            sys.path.insert(0, os.path.abspath(project_root))
            file_line_infos = fix_python_imports.ParseOneFile(
                body, change_record)
            fixed_lines = fix_python_imports.FixFileLines(
                change_record, file_line_infos, fix_imports_flags)
        finally:
            del sys.path[0]

        if fixed_lines is None:
            return
        fixed_body = ''.join(['%s\n' % line for line in fixed_lines
                              if line is not None])
        if fixed_body == body:
            return

        diffs = difflib.SequenceMatcher(None, body, fixed_body).get_opcodes()
        for op, i1, i2, j1, j2 in diffs:
            if op != 'equal':
                yield khodemod.Patch(filename,
                                     body[i1:i2], fixed_body[j1:j2], i1, i2)

    return suggestor
