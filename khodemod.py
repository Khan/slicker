"""Utility for modifying code.

Heavily inspired by https://github.com/facebook/codemod and with a similar API,
although it's written from scratch.  The user-facing functionality will
eventually be pretty similar, but khodemod is designed for use as a library --
so each component is pluggable -- as well as for Khan Academy's use cases.

TERMS:
"suggestor": These are how one implements code-changes to be applied using
    khodemod.  They're just functions (often curried -- that is, the actual
    suggestor is the function returned by calling some_suggestor(...))
    accepting a filename (string) and body (string, the text of that file) and
    yielding a series of khodemod.Patch objects, representing the changes to be
    made.  They may also yield khodemod.WarningInfo objects, which will be
    displayed to the user as warnings, or raise khodemod.FatalError exceptions,
    to refuse to process the given file.  Note that these changes will not be
    applied until the suggestor completes operation.  For an example, see
    regex_suggestor() below, which implements a simple find-and-replace.
"frontend": These are responsible for applying the changes given by a
    suggestor, perhaps displaying output to the user (or even prompting for
    input) as they go.  Currently, only one is implemented,
    khodemod.AcceptingFrontend, which simply applies the changes, perhaps
    displaying a progress bar.
    TODO(benkraft): Implement other frontends.
"root": The directory in which we should operate, often the current working
    directory.
"path_filter": These are how one decides what code to operate on: one passes a
    path filter, which is just a function which takes a filename relative to
    "root" and returns True if we should operate on it.  These are useful for
    ignoring generated files and the like.

TODO(benkraft): Implement a commandline interface for the regex suggestors.
"""
from __future__ import absolute_import

import collections
import os

import tqdm


DEFAULT_EXCLUDE_PATHS = ('genfiles', 'third_party')
DEFAULT_EXTENSIONS = ('py',)


def regex_suggestor(regex, replacement):
    """Replaces regex (object) with replacement.

    Replacment may use backreferences and such.
    TODO(benkraft): Support passing a function as a replacement.
    TODO(benkraft): This won't necessarily work right for overlapping matches;
    the patches may fail to apply.
    """
    def suggestor(filename, body):
        for match in regex.finditer(body):
            yield Patch(filename, match.group(0), match.expand(replacement),
                        match.start(), match.end())
    return suggestor


# old/new are strings; start/end are character offsets for the old text.
# TODO(benkraft): Include context for patching?
_Patch = collections.namedtuple('Patch',
                                ['filename', 'old', 'new', 'start', 'end'])
# pos is a character offset for the warning.
WarningInfo = collections.namedtuple('WarningInfo',
                                     ['filename', 'pos', 'message'])


class Patch(_Patch):
    def apply_to(self, body):
        if body[self.start:self.end] != (self.old or ''):
            raise FatalError(self.filename, self.start,
                             "patch didn't apply: %s" % (self,))
        if self.new is None:    # means we want to delete the new file
            assert self.start == 0 and self.end == len(body), self
            return None
        else:
            return body[:self.start] + self.new + body[self.end:]


class FatalError(RuntimeError):
    """Something went horribly wrong; we should give up patching this file."""
    def __init__(self, filename, pos, message):
        self.filename = filename
        self.pos = pos
        self.message = message

    def __repr__(self):
        return "FatalError(%r, %r, %r)" % (self.filename, self.pos,
                                           self.message)

    def __unicode__(self):
        return "Fatal Error:%s:%s:%s" % (self.filename, self.pos, self.message)

    def __eq__(self, other):
        return (isinstance(other, FatalError) and
                self.filename == other.filename and self.pos == other.pos and
                self.message == other.message)


def emit(txt):
    """This is a function so tests can override it."""
    print txt


def extensions_path_filter(extensions, include_extensionless=False):
    if extensions == '*':
        return lambda path: True

    def filter_path(path):
        _, ext = os.path.splitext(path)
        if not ext and include_extensionless:
            return True
        if ext and ext.lstrip(os.path.extsep) in extensions:
            return True
        return False

    return filter_path


def dotfiles_path_filter():
    return lambda path: not any(len(part) > 1 and path.startswith('.')
                                for part in os.path.split(path))


def exclude_paths_filter(exclude_paths):
    return lambda path: not any(part in exclude_paths
                                for part in path.split(os.path.sep))


def and_filters(filters):
    return lambda item: all(f(item) for f in filters)


def default_path_filter(extensions=DEFAULT_EXTENSIONS,
                        include_extensionless=False,
                        exclude_paths=DEFAULT_EXCLUDE_PATHS):
    return and_filters([
        extensions_path_filter(extensions, include_extensionless),
        dotfiles_path_filter(),
        exclude_paths_filter(exclude_paths),
    ])


def read_file(root, filename):
    """Return file contents, or None if the file is not found.

    filename is taken relative to root.
    """
    # TODO(benkraft): Cache contents.
    try:
        with open(os.path.join(root, filename)) as f:
            return f.read()
    except IOError as e:
        if e.errno == 2:    # No such file
            return None     # empty file
        raise


def resolve_paths(path_filter, root='.'):
    """All files under root (relative to root), ignoring filtered files."""
    for dirpath, dirnames, filenames in os.walk(root):
        # TODO(benkraft): Avoid traversing excluded directories.
        for name in filenames:
            relname = os.path.relpath(os.path.join(dirpath, name), root)
            if path_filter(relname):
                yield relname


def pos_to_line_col(text, pos):
    """Accept a character position in text, return (lineno, colno).

    lineno and colno are, as usual, 1-indexed.
    """
    lines = text.splitlines(True)
    for i, line in enumerate(lines):
        if pos < len(line):
            return (i + 1, pos + 1)
        else:
            pos -= len(line)
    raise RuntimeError("Invalid position %s!" % pos)


def line_col_to_pos(text, line, col):
    """Accept a line/column in text, return character position.

    lineno and colno are, as usual, 1-indexed.
    """
    lines = text.splitlines(True)
    try:
        return sum(len(line) for line in lines[:line - 1]) + col - 1
    except IndexError:
        raise RuntimeError("Invalid line number %s!" % line)


class Frontend(object):
    def __init__(self):
        # (root, filename) of files we've modified.
        # filename is relative to root.
        self._modified_files = set()

    def handle_patches(self, root, filename, patches):
        """Accept a list of patches for a file, and apply them.

        This may prompt the user for confirmation, inform them of the patches,
        or simply apply them without input.  It is the responsibility of this
        method to do any merging necessary to accomplish that.

        The patches will be ordered by start position.
        """
        raise NotImplementedError("Subclasses must override.")

    def handle_warnings(self, root, filename, warnings):
        """Accept a list of warnings for a file, and tell the user.

        Or don't!  It's up to the subclasses.  The warnings will be ordered by
        start position.  This will be called before any patching, and may raise
        FatalError if we want to not proceed.
        """
        raise NotImplementedError("Subclasses must override.")

    def handle_error(self, root, error):
        """Accept a fatal error, and tell the user we'll skip this file."""
        raise NotImplementedError("Subclasses must override.")

    def write_file(self, root, filename, text):
        """filename is taken to be relative to root.

        Note you need a Frontend to write files (so we can update the
        list of modified files), but not to read them.
        """
        abspath = os.path.abspath(os.path.join(root, filename))
        if text is None:    # it means we want to delete filename
            try:
                os.unlink(abspath)
            except OSError as e:
                if e.errno == 2:   # No such file: already deleted
                    pass
                raise
            # TODO(csilvers): delete our parent dirs if they're empty?
        else:
            try:
                os.makedirs(os.path.dirname(abspath))
            except (IOError, OSError):  # hopefully "directory already exists"
                pass
            with open(abspath, 'w') as f:
                f.write(text)
                self._modified_files.add((root, filename))

    def progress_bar(self, paths):
        """Return the passed iterable of paths, and perhaps update progress.

        Subclasses may override.
        """
        return paths

    def _run_suggestor_on_file(self, suggestor, root, filename):
        """filename is relative to root."""
        try:
            # Ensure the entire suggestor runs before we start patching.
            vals = list(
                suggestor(filename, read_file(root, filename) or ''))
            patches = [p for p in vals if isinstance(p, Patch)
                       and p.old != p.new]
            # HACK: consider addition-ish before deletion-ish.
            patches.sort(key=lambda p: (p.start,
                                        len(p.old or '') - len(p.new or '')))
            warnings = [w for w in vals if isinstance(w, WarningInfo)]
            warnings.sort(key=lambda w: w.pos)

            # Typically when you run a suggestor on a file, all the
            # patches it suggests will be for that file as well, but
            # it's possible for a suggestor to suggest changes to
            # another file (e.g. when moving code from one file to
            # another).  So we group by file-to-change here.
            patches_by_file = {}
            warnings_by_file = {}
            for patch in patches:
                patches_by_file.setdefault(patch.filename, []).append(patch)
            for warning in warnings:
                warnings_by_file.setdefault(warning.filename, []).append(
                    warning)

            seen_filenames = list(set(patches_by_file) | set(warnings_by_file))
            seen_filenames.sort(key=lambda f: (0 if f == filename else 1, f))
            for filename in seen_filenames:
                if filename in warnings_by_file:
                    self.handle_warnings(root, filename,
                                         warnings_by_file[filename])
                if filename in patches_by_file:
                    self.handle_patches(root, filename,
                                        patches_by_file[filename])
        except FatalError as e:
            self.handle_error(root, e)

    def run_suggestor(self, suggestor,
                      path_filter=default_path_filter(), root='.'):
        filenames = resolve_paths(path_filter, root)
        for filename in self.progress_bar(filenames):
            self._run_suggestor_on_file(suggestor, root, filename)

    def run_suggestor_on_modified_files(self, suggestor):
        """Like run_suggestor, but only on files we've modified.

        Useful for fixups after the fact that we don't want to apply to the
        whole codebase, only the files we touched.
        """
        for (root, filename) in self.progress_bar(self._modified_files):
            # If we modified a file by deleting it, no more
            # suggestions for you!
            if os.path.exists(os.path.join(root, filename)):
                self._run_suggestor_on_file(suggestor, root, filename)


class AcceptingFrontend(Frontend):
    """A frontend where we apply all patches without question."""
    def __init__(self, verbose=False, **kwargs):
        super(AcceptingFrontend, self).__init__(**kwargs)
        self.verbose = verbose

    def progress_bar(self, paths):
        if self.verbose:
            paths = list(
                tqdm.tqdm(paths, desc='Computing paths', unit=' files'))
            return tqdm.tqdm(paths, desc='Applying changes', unit=' files')
        else:
            return paths

    def handle_patches(self, root, filename, patches):
        body = read_file(root, filename)
        # We operate in reverse order to avoid having to keep track of changing
        # offsets.
        new_body = body or ''
        for patch in reversed(patches):
            assert filename == patch.filename, patch
            new_body = patch.apply_to(new_body)
        if body != new_body:
            self.write_file(root, filename, new_body)

    def handle_warnings(self, root, filename, warnings):
        body = read_file(root, filename) or ''
        for warning in warnings:
            assert filename == warning.filename, warning
            lineno, _ = pos_to_line_col(body, warning.pos)
            line = body.splitlines()[lineno - 1]
            emit("WARNING:%s\n    on %s:%s --> %s"
                 % (warning.message, filename, lineno, line))

    def handle_error(self, root, error):
        body = read_file(root, error.filename) or ''
        lineno, _ = pos_to_line_col(body, error.pos)
        line = body.splitlines()[lineno - 1]
        emit("ERROR:%s\n    on %s:%s --> %s"
             % (error.message, error.filename, lineno, line))
