#!/usr/bin/env python
import argparse
import ast
import collections
import difflib
import os
import re
import sys
import textwrap

import codemod

# After importing everything else, but before importing fix_python_imports, we
# want to add cwd to the python path, so that fix_python_imports can find what
# modules are third-party correctly.
# TODO(benkraft): refactor fix_python_imports so this is easier.
sys.path.insert(0, os.getcwd())
import fix_python_imports


# TODO(benkraft): configurable
EXCLUDE_PATHS = ['third_party', 'genfiles']


_LEADING_WHITESPACE_RE = re.compile('^(\s*)(\S|$)')
_FINAL_COMMENT_RE = re.compile('(\s*#.*)?$')


def _re_for_name(name):
    return re.compile(r'(?<!\.)\b%s\b' %
                      re.escape(name).replace(r'\.', r'\s*\.\s*'))


class FakeOptions(object):
    safe_headers = True


# imported: the module or symbol we actually imported.
# imported_alias: the alias under which we imported it.
# name_alias: the alias of the module or symbol we were looking for.
# So if we searched for 'foo.bar.baz' and found 'from foo import bar', we'd
# represent that as Import('foo.bar', 'bar', 'bar.baz').  See test cases for
# more examples.
Import = collections.namedtuple(
    'Import', ['imported', 'imported_alias', 'name_alias'])


def _compute_all_imports(lines):
    """Returns info about the imports in this file.

    Returns a set of pairs (name, imported as).
    """
    try:
        # TODO(benkraft): cache the AST.
        root = ast.parse(''.join(lines))
    except SyntaxError:
        return set()
    imports = set()
    for node in ast.walk(root):
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            if isinstance(node, ast.ImportFrom) and node.level != 0:
                # TODO(benkraft): Figure out how to handle these!  It's
                # unfortunately tricky for us to get the filename we're working
                # on, so we just ignore them and cross our fingers for now.
                continue
            for alias in node.names:
                if isinstance(node, ast.Import):
                    imports.add((alias.name, alias.asname or alias.name))
                else:
                    imports.add(('%s.%s' % (node.module, alias.name),
                                 alias.asname or alias.name))
    return imports


def _determine_imports(symbol, lines):
    """Returns info about the names by which the symbol goes in this file.

    Returns a set of Import namedtuples.
    """
    imports = set()
    symbol_parts = symbol.split('.')
    for name, alias in _compute_all_imports(lines):
        imported_parts = name.split('.')
        if alias == name:
            if imported_parts[0] == symbol_parts[0]:
                imports.add(Import(name, name, symbol))
        else:
            nparts = len(imported_parts)
            # If we imported the symbol, or a less-specific prefix (e.g. its
            # module, or a parent of that)
            if symbol_parts[:nparts] == imported_parts:
                symbol_alias = '.'.join(
                    [alias] + symbol_parts[nparts:])
                imports.add(Import(name, alias, symbol_alias))
    return imports


def _dotted_starts_with(string, prefix):
    """Like string.startswith(prefix), but in the dotted sense.

    That is, abc is a prefix of abc.de but not abcde.ghi.
    """
    return prefix == string or string.startswith('%s.' % prefix)


def _dotted_prefixes(string):
    """All prefixes of string, in the dotted sense.

    That is, all strings p such that _dotted_starts_with(string, p), in order
    from shortest to longest.
    """
    string_parts = string.split('.')
    for i in xrange(len(string_parts)):
        yield '.'.join(string_parts[:i + 1])


def _name_for_node(node):
    """Return the dotted name of an AST node, if there's a reasonable one.

    This only does anything interesting for Name and Attribute, and for
    Attribute only if it's like a.b.c, not (a + b).c.
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        value = _name_for_node(node.value)
        if value:
            return '%s.%s' % (value, node.attr)


def _names_starting_with(prefix, lines):
    """Returns all dotted names in the file beginning with 'prefix'.

    Does not include imports or string references or anything else funky like
    that.  Includes prefixes, so if you do a.b.c and ask for things beginning
    with a, we'll return {'a', 'a.b', 'a.b.c'}.  "Beginning with prefix" in the
    dotted sense (see _dotted_starts_with).
    """
    root = ast.parse(''.join(lines))
    all_names = (_name_for_node(node) for node in ast.walk(root))
    return {name for name in all_names
            if name and _dotted_starts_with(name, prefix)}


def _had_any_references(name, imports, lines):
    for imp in imports:
        if _dotted_starts_with(name, imp.imported):
            # An explicit import of the name or a prefix (e.g. module)
            # TODO(benkraft): This is currently too loose, and should only look
            # for prefixes module <= prefix <= name.
            return True
        if _names_starting_with(name, lines):
            return True
    return False


def _check_import_conflicts(lines, added_name, is_alias):
    """Return any imports that will conflict with ours.

    added_name should be the name of the import, not the symbol.

    TODO(benkraft): If that's due to our alias, we could avoid using
    said alias.
    TODO(benkraft): Also check if there are variable-names that
    collide.
    """
    imports = _compute_all_imports(lines)
    if is_alias:
        # If we are importing with an alias, we're looking for existing
        # imports with whose prefix we collide.
        return {name for name, alias in imports
                if _dotted_starts_with(alias, added_name)}
    else:
        # If we aren't importing with an alias, we're looking for
        # existing imports who are a prefix of us.
        return {name for name, alias in imports
                if _dotted_starts_with(added_name, alias)}


def _imports_to_remove(old_imports, existing_new_imports, new_name,
                       patched_aliases, lines):
    # Decide whether to keep the old import if we changed references to it.
    removable_imports = set()
    maybe_removable_imports = set()
    for imp in old_imports:
        if imp.name_alias in existing_new_imports:
            # This is the existing new import!  Don't touch it.
            continue
        elif new_name == imp.name_alias:
            # If one of the old imports is for the same alias, it had
            # better be removable!  (We've already checked for conflicts.)
            removable_imports.add(imp)
        elif imp.name_alias in patched_aliases:
            # Anything starting with the relevant prefix.
            relevant_names = _names_starting_with(
                imp.imported_alias.split('.')[0], lines)
            explicit_names = {
                name for name in relevant_names
                if _dotted_starts_with(name, imp.imported_alias)}
            handled_names = {
                name for name in relevant_names
                if any(_dotted_starts_with(name, prefix)
                       for prefix in _dotted_prefixes(new_name))}

            # If we explicitly reference the old module via this alias,
            # keep the import.
            if explicit_names:
                break
            # If we implicitly reference this import, and the new import
            # will not take care of it, we need to ask the user what to do.
            elif relevant_names - explicit_names - handled_names:
                maybe_removable_imports.add(imp)
            else:
                removable_imports.add(imp)

    # Now, if there was an import we were considering removing, and we are
    # keeping a different import that gets us the same things, we can
    # definitely remove the former.
    definitely_kept_imports = (old_imports - removable_imports -
                               maybe_removable_imports)
    for maybe_removable_imp in list(maybe_removable_imports):
        for kept_imp in definitely_kept_imports:
            if (maybe_removable_imp.imported_alias.split('.')[0] ==
                    kept_imp.imported_alias.split('.')[0]):
                maybe_removable_imports.remove(maybe_removable_imp)
                removable_imports.add(maybe_removable_imp)
                break

    return removable_imports, maybe_removable_imports


def the_suggestor(old_name, new_name, name_to_import, use_alias=None):
    def suggestor(lines):
        # PART THE FIRST:
        #    Set things up, do some simple checks, decide whether to operate.

        # TODO(benkraft): This is super ginormous by now, break it up.
        assert _dotted_starts_with(new_name, name_to_import), (
            "%s isn't a valid name to import -- not a prefix of %s" % (
                name_to_import, new_name))

        old_imports = _determine_imports(old_name, lines)
        # Choose the alias to replace with.
        # TODO(benkraft): this might not be totally safe if the existing
        # import isn't toplevel, but probably it will be.
        existing_new_imports = {
            imp.name_alias for imp
            in _determine_imports(new_name, lines)
            if name_to_import == imp.imported}

        # If we didn't import the module at all, nothing to do.
        if not old_imports:
            return

        # Or if we didn't reference it, and didn't explicitly import it.
        # TODO(benkraft): We should still look for mocks and such here.
        if not _had_any_references(old_name, old_imports, lines):
            return

        old_aliases = {imp.name_alias for imp in old_imports}

        # If for some reason there are multiple existing aliases
        # (unlikely), choose the shortest one, to save us line-wrapping.
        # Prefer an existing explicit import to the caller-provided alias.
        if existing_new_imports:
            final_new_name = max(existing_new_imports, key=len)
        elif use_alias and name_to_import == new_name:
            final_new_name = use_alias
        elif use_alias:
            final_new_name = '%s.%s' % (
                use_alias, new_name[len(name_to_import) + 1:])
        else:
            final_new_name = new_name

        if not existing_new_imports:
            dupe_imports = _check_import_conflicts(
                lines, use_alias or name_to_import, bool(use_alias))
            if dupe_imports:
                yield codemod.Patch(
                    0, 0,
                    ["# STOP" "SHIP: Your alias will conflict with the "
                     "following imports:\n"] +
                    ["#    %s\n" % imp for imp in dupe_imports] +
                    ["# Not touching this file.\n"])
                return

        # PART THE SECOND:
        #    Patch references to the symbol inline -- everything but imports.

        patched_aliases = set()
        # If any alias changed, we need to fix up references.  (We'll fix
        # up imports either way at this point.)
        for imp in old_aliases - {final_new_name}:
            old_final_re = _re_for_name(imp)
            base_suggestor = codemod.multiline_regex_suggestor(
                old_final_re, final_new_name)
            for patch in base_suggestor(lines):
                # HACK: we don't want to fix up imports here; we'll fix them up
                # later.
                if _determine_imports(old_name, textwrap.dedent(
                        ''.join(lines[
                            patch.start_line_number:patch.end_line_number]))
                                      .splitlines(True)):
                    continue
                if patch.new_lines != lines[
                        patch.start_line_number:patch.end_line_number]:
                    patched_aliases.add(imp)
                    yield patch

        # PART THE THIRD:
        #    Add/remove imports, if necessary.

        # Nor if we didn't fix up references and would have had to.
        # TODO(benkraft): I think we do extra work here if we don't change the
        # alias but also don't have any references.
        if not patched_aliases and final_new_name not in old_aliases:
            return

        removable_imports, maybe_removable_imports = _imports_to_remove(
            old_imports, existing_new_imports, final_new_name,
            patched_aliases, lines)

        if (existing_new_imports and not removable_imports and
                not maybe_removable_imports):
            # We made changes, but still don't need to fix any imports.
            return

        had_explicit_import = any(
            # TODO(benkraft): As in _had_any_references, this is too weak -- we
            # should only call an import explicit if it is of the symbol's
            # module.
            _dotted_starts_with(old_name, imp.imported)
            for imp in old_imports)
        added_on_lines = set()
        for i, line in enumerate(lines):
            # Parse the line on its own to see if it's an import.  This is
            # kinda fragile.  We have to strip leading indents to make it work.
            # TODO(benkraft): Track line numbers, and look for the right line
            # instead of having to guess.  It's hard because they could change.
            # TODO(benkraft): This doesn't handle multiline imports quite
            # correctly.
            maybe_imports = _determine_imports(old_name, [line.lstrip()])
            removed_import = False
            if maybe_imports:
                # Consider whether to remove the import.
                if ('@UnusedImport' in line or
                        '@Nolint' in line and 'unused' in line):
                    # Never remove a deliberately unused import.
                    pass
                elif maybe_imports.issubset(removable_imports):
                    removed_import = True
                    yield codemod.Patch(i, i+1, [])
                elif maybe_imports.intersection(removable_imports):
                    yield codemod.Patch(i, i+1, [
                        "%s  # STOP" "SHIP: I don't know how to edit this "
                        "import.\n" % line.rstrip()])
                elif (maybe_imports.intersection(maybe_removable_imports) and
                      # HACK: sometimes when lines changes under us we may try
                      # to add the comment twice.
                      "may be used implicitly." not in line):
                    yield codemod.Patch(i, i+1, [
                        "%s  # STOP" "SHIP: This import may be used "
                        "implicitly.\n" % line.rstrip()])

                # HACK: if we added an import on the previous line, don't add
                # one here -- there's no way we need it.  This mitigates the
                # issue where sometimes we process a line again because we
                # added a line just before it (and didn't delete it).  It
                # doesn't totally solve the issue, in the case where the user
                # did a manual edit, but hopefully in that case they are paying
                # attention.
                if i - 1 in added_on_lines:
                    continue

                # Consider whether to add an import.
                # If there previously existed an explicit import, we add at the
                # location of each explicit import, and only those.  If not, we
                # add at the first implicit import only.
                # TODO(benkraft): This doesn't work correctly in the case where
                # there was an implicit toplevel import, and an explicit late
                # import, and the moved symbol was used outside the scope of
                # the late import.  To handle this case, we'll need to do much
                # more careful tracing of which imports exist in which scopes.
                is_explicit = any(
                    # TODO(benkraft): As above, this check is too weak.
                    _dotted_starts_with(old_name, imp.imported)
                    for imp in maybe_imports)
                # HACK: if we are processing a line that looks identical to the
                # immediately previous one, we don't add anything for it -- we
                # may just be seeing the same line again, because we added a
                # line in front of it.
                # TODO(benkraft): If the user has edited the patches to add two
                # lines, this won't work, but hopefully in that case they will
                # notice what's going on and bail.
                if not existing_new_imports and (
                        is_explicit or not had_explicit_import):
                    if '.' in name_to_import and use_alias:
                        base, suffix = name_to_import.rsplit('.', 1)
                        if use_alias == suffix:
                            import_stmt = 'from %s import %s' % (base, suffix)
                        else:
                            import_stmt = 'import %s as %s' % (
                                name_to_import, use_alias)
                    else:
                        if use_alias and use_alias != name_to_import:
                            import_stmt = 'import %s as %s' % (
                                name_to_import, use_alias)
                        else:
                            import_stmt = 'import %s' % name_to_import

                    # We keep the same indentation-level.
                    indent = _LEADING_WHITESPACE_RE.search(line).group(1)
                    # If we removed an import here, grab its comment.
                    if removed_import:
                        comment = _FINAL_COMMENT_RE.search(line).group(0)
                    else:
                        comment = ''
                    yield codemod.Patch(
                        i, i, ['%s%s%s\n' % (indent, import_stmt, comment)])
                    added_on_lines.add(i)
                    if not is_explicit:
                        # If we are adding at implicit imports, only do so for
                        # the first one.
                        existing_new_imports.add(name_to_import)

        # PART THE FOURTH:
        #    Resort imports, if necessary.

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

        yield codemod.Patch(diffs[0][1], diffs[-1][2],
                            fixed_lines[diffs[0][3]:diffs[-1][4]])

    return suggestor


def main():
    # TODO(benkraft): support other codemod args
    # TODO(benkraft): Allow moving multiple symbols (from/to the same modules)
    # at once.
    parser = argparse.ArgumentParser()
    parser.add_argument('old_name')
    parser.add_argument('new_name')
    parser.add_argument('-m', '--module', action='store_true',
                        help=('Treat moved name as a module, rather than a '
                              'symbol.'))
    # TODO(benkraft): We don't handle mocks right when there is an alias.
    parser.add_argument('-a', '--alias', metavar='ALIAS',
                        help=('Alias to use when adding new import lines.'
                              'If this has a dot (e.g. it is a symbol, not a '
                              'module), all parts except the first must match '
                              'the real name.'))
    parsed_args = parser.parse_args()
    path_filter = codemod.path_filter(['py'], EXCLUDE_PATHS)
    # TODO(benkraft): Allow specifying explicitly what to import, so we can
    # import a symbol (although KA never wants to do that).
    if parsed_args.module:
        name_to_import = parsed_args.new_name
    else:
        name_to_import, _ = parsed_args.new_name.rsplit('.', 1)
    suggestor = the_suggestor(parsed_args.old_name, parsed_args.new_name,
                              name_to_import, use_alias=parsed_args.alias)
    query = codemod.Query(suggestor, path_filter=path_filter)
    query.run_interactive()


if __name__ == '__main__':
    main()
