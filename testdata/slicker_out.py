#!/usr/bin/env python
import argparse
import difflib
import os
import re
import sys

import codemod_fork as the_other_codemod

# After importing everything else, but before importing fix_python_imports, we
# want to add cwd to the python path, so that fix_python_imports can find what
# modules are third-party correctly.
# TODO(benkraft): refactor fix_python_imports so this is easier.
sys.path.insert(0, os.getcwd())
import fix_python_imports


# TODO(benkraft): configurable
EXCLUDE_PATHS = ['third_party', 'genfiles']


_PLAIN_IMPORT_RE = re.compile(
    r'^\s*import +([\w.]*)(?: +as +(\w*))?\s*(?:$|#)')
_FROM_IMPORT_RE = re.compile(
    r'^\s*from +([\w.]*) +import +(\w*)(?: +as +(\w*))?\s*(?:$|#)')
# Things we don't handle:
# - imports with internal spaces (very rare and mildly annoying to deal with)
# - imports with comma (easy to parse, hard to decide what to keep/modify)
# - from foo import *
# - imports with \ or ( (hard to parse right)
_ANY_PLAIN_IMPORT_RE = re.compile(
    r'^\s*import +([\w., ]*)(?: +as +(\w*))?\s*(?:$|#)')
_ANY_FROM_IMPORT_RE = re.compile(r'^\s*from +([\w.]*) +import\b')
# We try to make this have no false negatives but minimize false positives.
# TODO(benkraft): semicolons can cause false negatives :(
_OTHER_IMPORT_RE = re.compile(r'''^\s*(from +[^#"'()]*(\\|import\b)|'''
                              r'''import +[^#"'()]*\\)''')

# Very aggressive in what it finds.
_ANY_IMPORT_RE = re.compile(r'^\s*(from|import)\b')
_LEADING_WHITESPACE_RE = re.compile('^(\s*)(\S|$)')
_COMMENT_LINE_RE = re.compile('^\s*#')


def _re_for_name(name):
    return re.compile(r'(?<!\.)\b%s\b' % re.escape(name))


class FakeOptions(object):
    safe_headers = True


class UnparsedImportError(ValueError):
    def __init__(self, lines):
        self.lines = lines


def _determine_imports(module, lines):
    """Returns info about the names by which the module goes in this file.

    Returns a set of tuples (imported module, its alias, module's alias).  For
    example, if 'module' is foo.bar.baz, `from foo import bar` would cause us
    to include ('foo.bar', 'bar', 'bar.baz').  See test cases for more
    examples.

    Raises UnparsedImportError if *any* line is something we don't handle.
    """
    module_parts = module.split('.')
    retval = set()
    bad_lines = []
    for i, line in enumerate(lines):
        plain_import = _PLAIN_IMPORT_RE.search(line)
        from_import = _FROM_IMPORT_RE.search(line)
        unhandled_plain_import = _ANY_PLAIN_IMPORT_RE.search(line)
        unhandled_from_import = _ANY_FROM_IMPORT_RE.search(line)
        other_import = _OTHER_IMPORT_RE.search(line)
        if plain_import:
            imported, alias = plain_import.groups()
        elif from_import:
            from_module, imported, alias = from_import.groups()
            alias = alias or imported
            imported = '%s.%s' % (from_module, imported)
        elif unhandled_plain_import:
            imported_partss = [
                imp.strip().split(' ')[0].split('.')
                for imp in unhandled_plain_import.group(1).split(',')]
            if any(imported_parts[0] == module_parts[0]
                   for imported_parts in imported_partss):
                bad_lines.append(line)
            continue
        elif unhandled_from_import:
            # TODO(benkraft): check the parts to see if we care, as in
            # unhandled plain imports.
            imported_parts = unhandled_from_import.group(1).split('.')
            if imported_parts == module_parts[:len(imported_parts)]:
                bad_lines.append(line)
            continue
        elif other_import:
            bad_lines.append(line)
            continue
        else:  # not an import
            continue

        # Check for both implicit and explicit imports
        imported_parts = imported.split('.')
        # We've imported the module or a prefix
        if imported_parts == module_parts[:len(imported_parts)]:
            if alias:
                name = '.'.join([alias] + module_parts[len(imported_parts):])
            else:
                name = module
            retval.add((imported, alias or imported, name))
        # We've imported a module with a common prefix, and not under an alias
        elif imported_parts[0] == module_parts[0] and not alias:
            retval.add((imported, imported, module))
    if bad_lines:
        raise UnparsedImportError(bad_lines)
    return retval


def _had_any_references(module, import_names, symbol, lines):
    for module_imported, _, alias in import_names:
        if module_imported == module:
            # An explicit import of the module.
            return True
        full_re = _re_for_name('%s.%s' % (alias, symbol))
        for line in lines:
            if full_re.search(line):
                # A reference to the module in the body.
                return True
    return False


def the_suggestor(old_name, new_name, use_alias=None):
    def suggestor(lines):
        # TODO(benkraft): This is super ginormous by now, break it up.
        old_module, old_symbol = old_name.rsplit('.', 1)
        new_module, new_symbol = new_name.rsplit('.', 1)

        try:
            # TODO(benkraft): this isn't quite right if they are importing a
            # symbol, rather than a module.
            old_imports = _determine_imports(old_module, lines)
            # Choose the alias to replace with.
            # TODO(benkraft): this might not be totally safe if the existing
            # import isn't toplevel, but probably it will be.
            existing_new_imports = {
                alias for imported_module, _, alias
                in _determine_imports(new_module, lines)
                if imported_module == new_module}
        except UnparsedImportError as e:
            # We couldn't figure out the imports.  Stick a comment in on line 1
            # saying so, to return to the user to fix, and don't process the
            # rest of the file.
            yield the_other_codemod.Patch(
                0, 0, [
                    "# STOP" "SHIP: I couldn't handle this file's imports.\n",
                    "# Reject this change if you know it's a non-issue,\n",
                    "# or accept and fix it up yourself.  Unhandled lines:\n",
                ] + ["#    %s" % line for line in e.lines])
            return

        old_aliases = {alias for _, _, alias in old_imports}

        # If we didn't import the module at all, nothing to do.
        if not old_imports:
            return

        # Or if we didn't reference it, and didn't explicitly import it.
        if not _had_any_references(old_module, old_imports, old_symbol, lines):
            return

        # If for some reason there are multiple existing aliases
        # (unlikely), choose the shortest one, to save us line-wrapping.
        # Prefer an existing explicit import to the caller-provided alias.
        if existing_new_imports:
            final_new_module = max(existing_new_imports, key=len)
        else:
            final_new_module = use_alias or new_module

        final_new_name = '%s.%s' % (final_new_module, new_symbol)

        patched_aliases = set()
        # If any alias changed, we need to fix up references.  (We'll fix
        # up imports either way at this point.)
        for imp in old_aliases - {final_new_module}:
            old_final_re = _re_for_name('%s.%s' % (imp, old_symbol))
            base_suggestor = the_other_codemod.regex_suggestor(
                old_final_re, final_new_name)
            for patch in base_suggestor(lines):
                if patch.new_lines != lines[
                        patch.start_line_number:patch.end_line_number]:
                    patched_aliases.add(imp)
                    yield patch

        # Next, fix up imports.  Don't bother if the file didn't move modules.
        if old_module == new_module:
            return

        # Nor if we didn't fix up references and would have had to.
        # TODO(benkraft): I think we do extra work here if we don't change the
        # alias but also don't have any references.
        if not patched_aliases and final_new_module not in old_aliases:
            return

        # Lines that aren't imports, comments, or references to the new name.
        filtered_lines = [line for line in lines
                          if not _ANY_IMPORT_RE.search(line) and
                          not _COMMENT_LINE_RE.search(line)]

        # Decide whether to keep the old import if we changed references to it.
        removable_imports = set()
        maybe_removable_imports = set()
        for import_info in old_imports:
            imported_module, imported_alias, old_module_alias = import_info
            if final_new_module == old_module_alias:
                # If one of the old imports is for the same alias, it had
                # better be removable!
                removable_imports.add(import_info)
                # But if we also used other names from the old import, that's
                # real bad -- there's no way for us to automatically do the
                # right thing.
                final_new_name_re = _re_for_name(final_new_name)
                final_new_module_re = _re_for_name(final_new_module)
                for line in filtered_lines:
                    # If we refer to the alias, and are not a reference to the
                    # moved symbol, nor an import, nor a comment.
                    # TODO(benkraft): this won't work quite right with multiple
                    # references in one line.
                    if (final_new_module_re.search(line) and
                            not final_new_name_re(line)):
                        yield the_other_codemod.Patch(
                            0, 0, ["# STOP" "SHIP: Your alias will result in "
                                   "import conflicts on this line:\n",
                                   "#    %s" % line,
                                   "Please fix the imports in this file "
                                   "manually.\n"])
                        return
            elif old_module_alias in patched_aliases:
                imported_module_re = _re_for_name(imported_alias)
                imported_prefix_re = _re_for_name(imported_alias.split('.')[0])
                # If we explicitly reference the old module via this alias,
                # keep the import.
                for line in filtered_lines:
                    if imported_module_re.search(line):
                        break
                else:
                    # If we implicitly reference this import, or anything else
                    # that came with it, we may need to keep the import,
                    # because it may have brought something else along.  Ask
                    # the user.
                    for line in filtered_lines:
                        # TODO(benkraft): if this is *any* import, assume we're
                        # safe.
                        if imported_prefix_re.search(line):
                            maybe_removable_imports.add(import_info)
                            break
                    else:
                        removable_imports.add(import_info)

        # Now, if there was an import we were considering removing, and we are
        # keeping a different import that gets us the same things, we can
        # definitely remove the former.
        definitely_kept_imports = (old_imports - removable_imports -
                                   maybe_removable_imports)
        for maybe_removable_import_info in list(maybe_removable_imports):
            _, maybe_removable_imported_alias, _ = maybe_removable_import_info
            for kept_import_info in definitely_kept_imports:
                _, kept_imported_alias, _ = kept_import_info
                if (maybe_removable_imported_alias.split('.')[0] ==
                        kept_imported_alias.split('.')[0]):
                    maybe_removable_imports.remove(maybe_removable_import_info)
                    removable_imports.add(maybe_removable_import_info)
                    break

        if (existing_new_imports and not removable_imports and
                not maybe_removable_imports):
            # We made changes, but still don't need to fix any imports.
            return

        for i, line in enumerate(lines):
            maybe_import = _determine_imports(old_module, [line])
            if maybe_import:
                if maybe_import.issubset(removable_imports):
                    yield the_other_codemod.Patch(i, i+1, [])
                elif (maybe_import.issubset(maybe_removable_imports) and
                      # HACK: sometimes when lines changes under us we may try
                      # to add the comment twice.
                      "may be used implicitly." not in line):
                    yield the_other_codemod.Patch(i, i+1, [
                        "%s  # STOPSHIP: This import may be used implicitly.\n"
                        % line.rstrip()])

                if not existing_new_imports:
                    if '.' in new_module and use_alias:
                        base, suffix = new_module.rsplit('.', 1)
                        if use_alias == suffix:
                            import_stmt = 'from %s import %s' % (base, suffix)
                        else:
                            import_stmt = 'import %s as %s' % (
                                new_module, use_alias)
                    else:
                        if use_alias and use_alias != new_module:
                            import_stmt = 'import %s as %s' % (
                                new_module, use_alias)
                        else:
                            import_stmt = 'import %s' % new_module

                    # We keep the same indentation-level.
                    indent = _LEADING_WHITESPACE_RE.search(line).group(1)
                    yield the_other_codemod.Patch(
                        i, i, ['%s%s\n' % (indent, import_stmt)])
                    existing_new_imports.add(new_module)  # only do this once

        # TODO(benkraft): merge this with the import-adding, so we just show
        # one diff to add in the right place, unless there is additional
        # sorting to do.
        # Now call out to fix_python_imports to do the import-sorting
        change_record = fix_python_imports.ChangeRecord('fake_file.py')

        # A modified version of fix_python_imports.GetFixedFile
        file_line_infos = fix_python_imports.ParseOneFile(
            ''.join(lines), change_record)
        fixed_lines = fix_python_imports.FixFileLines(
            change_record, file_line_infos, FakeOptions())

        if fixed_lines is None:
            return
        fixed_lines = ['%s\n' % line for line in fixed_lines
                       if line is not None]
        if fixed_lines == lines:
            return

        # Unfortunately we have to give the diff all at once, and make the user
        # accept or reject it all, because otherwise the file could change
        # under us and we won't know how to apply the rest.
        # TODO(benkraft): something better
        diffs = difflib.SequenceMatcher(None, lines, fixed_lines).get_opcodes()
        if diffs[0][0] == 'equal':
            del diffs[0]
        if diffs[-1][0] == 'equal':
            del diffs[-1]

        yield the_other_codemod.Patch(diffs[0][1], diffs[-1][2],
                            fixed_lines[diffs[0][3]:diffs[-1][4]])

    return suggestor


def main():
    # NOTE(benkraft): We really shouldn't fix the following comment, but we do.
    # TODO(benkraft): support other the_other_codemod args
    # TODO(benkraft): Allow moving multiple symbols (from/to the same modules)
    # at once.
    parser = argparse.ArgumentParser()
    parser.add_argument('old_name')
    parser.add_argument('new_name')
    # TODO(benkraft): We don't handle mocks right when there is an alias.
    parser.add_argument('-a', '--alias', metavar='ALIAS',
                        help='Alias to use when adding new import lines.')
    parsed_args = parser.parse_args()
    path_filter = the_other_codemod.path_filter(['py'], EXCLUDE_PATHS)
    suggestor = the_suggestor(parsed_args.old_name, parsed_args.new_name,
                              use_alias=parsed_args.alias)
    query = the_other_codemod.Query(suggestor, path_filter=path_filter)
    query.run_interactive()


if __name__ == '__main__':
    main()
