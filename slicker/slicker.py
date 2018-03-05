#!/usr/bin/env python

"""A tool to move python modules and/or symbols and fix up all references.

Renaming a file (aka module) in python is non-trivial: you not only
need to rename the file, you need to find all other files that import
you and fix up their imports.  And if code refers to your file in a
string (e.g. for mocking) you need to fix that up too.  Slicker is a
tool to help with that: it will rename the file and fix up references
in code, strings, and comments.

But wait, there's more!  Slicker can also move individual top-level
symbols from one file to another.  (The destination file can be new.)
You can use this to "break up" files into smaller pieces, or just move
components that would better fit elsewhere.  The types of symbols that
can be moved are:
* top-level functions
* top-level classes
* top-level constants and variables


SPECIAL CASES IN PYTHON IMPORTS

One of the reasons slicker is complex is that python imports can do
a number of pathological things, if you're not careful.  Here are the
ones we have to deal with the most:
0) In addition to imports at the top of the file, there can be imports
   inside functions.  These are often used to avoid circular imports, or
   to avoid pulling in a module until it's certainly needed.  Often the
   same file will have several such imports of the same module, in
   different functions.  These aren't really a pathological case, just
   one that requires special handling in some places.  We call them
   "late imports".
1) If you do `import foo.bar`, and some other file (perhaps another one
   you import) does `import foo.baz`, then your `foo` now also has a
   `foo.baz`, and so you can do `foo.baz.func()` with impunity, even
   though no import in your file directly mentions that module.  (This
   is because `foo` in both files refers to the same object -- a.k.a.
   `sys.modules['foo']` -- and so when the other file does
   `import foo.baz` it attaches `baz` to that shared object.)  We call
   these "implicit imports", or say you accessed `foo.baz.func`
   "implicitly". Note that if you do `from foo import bar` this problem
   can't arise, as you don't have access to any `foo`.
2) Similarly, if you do `import foo` and some other file does
   `import foo.bar`, your foo now also has a `foo.bar`.  Slicker doesn't
   handle this case as well, as it's hard to tell whether `bar` is a
   symbol defined in `foo.py` (in which case this pattern is fine) or a
   module `foo/bar.py` (in which case it's not great).
3) Modules can import the same file in multiple ways.  For example, you
   might do both `import foo.bar` and `from foo import bar`, in which
   case `foo.bar.func` is available as both `foo.bar.func` and
   `bar.func`.  Hopefully you don't do that.
4) Modules can import themselves.  For example, `foo/bar.py` might do
   'import foo.bar`, in which case a function `func` defined in it is
   available as both `func` and `foo.bar.func`.  Hopefully you don't do
   that either.

TERMINOLOGY USED INTERNALLY

0) "late import", "implicit import": see special cases (0) and (1) above.
1) "fullname": the fully-qualified symbol or module being moved.  If you
   are moving class Importer from foo/bar.py to foo/baz.py, then
   the old "fullname" is foo.bar.Importer and the new "fullname" is
   foo.baz.Importer.
2) "localname": how the symbol-being-moved is referred to in the current
   file that we're analyzing.  If you're moving class Importer from
   foo/bar.py to foo/baz.py, and qux.py has a line:
       import foo.bar as foo_bar
   then the "localname" while processing qux.py is "foo_bar.Importer".
"""
from __future__ import absolute_import

import argparse
import ast
import itertools
import sys
import tokenize

from . import cleanup
from . import inputs
from . import khodemod
from . import model
from . import moves
from . import removal
from . import replacement
from . import util


def _check_import_conflicts(file_info, old_fullname, added_name, is_alias):
    """Return any imports that will conflict with ours.

    Suppose our file says `from foo import bar as baz` and
    we want to add `import baz` (or `import qux as baz`).
    That's not going to work!  (Python allows it but one name
    will shadow the other.) Similarly if our file has
    `import baz.bang`.

    added_name should be the alias of the import, not the symbol.

    Returns a list of import objects.

    TODO(benkraft): If that's due to our alias, we could avoid using
    said alias.
    TODO(benkraft): We shouldn't consider it a conflict if the only
    user of the conflicting import is the moved symbol.  (We do that
    now for full-file moves but not for symbol-moves.)
    TODO(benkraft): Also check if there are variable-names that
    collide.
    TODO(benkraft): Also check if there are names defined in the
    file that collide.
    """
    imports = model.compute_all_imports(file_info)

    # Ignore imports of old_fullname, those are going to be deleted.
    imports = {imp for imp in imports if imp.name != old_fullname}

    # TODO(csilvers): perhaps a more self-evident way to code this would
    # be: complain if there is any shared prefix between added_import.alias
    # and some_existing_import.alias.
    if is_alias:
        # If we are importing with an alias, we're looking for existing
        # imports with whose prefix we collide.
        # e.g. we're adding 'import foo.bar as baz' or 'from foo import baz'
        # and the existing code has 'import baz' or 'import baz.bang' or
        # 'from qux import baz' or 'import quux as baz'.
        return {imp for imp in imports
                if util.dotted_starts_with(imp.alias, added_name)}
    else:
        # If we aren't importing with an alias, we're looking for
        # existing imports who are a prefix of us.
        # e.g. we are adding 'import foo' or 'import foo.bar' and the
        # existing code has 'import baz as foo' or 'from baz import foo'.
        # TODO(csilvers): this is actually ok in the case we're going
        # to remove the 'import baz as foo'/'from baz import foo' because
        # the only client of that import is the symbol that we're moving.
        return {imp for imp in imports
                if util.dotted_starts_with(added_name, imp.alias)}


def _choose_best_localname(file_info, fullname, name_to_import, import_alias):
    """Decide what localname we should refer to fullname by in this file.

    If there's already an import of fullname, we'll use it.  If not, we'll
    choose the best import to add, based on name_to_import and import_alias.

    Returns: (the localname we should use,
              whether we need to add an import if we want to use it).

    (Note that if _choose_best_localname suggests to add an import, but the
    caller determines that we don't even need to add any references to this
    localname, said caller should likely ignore us and not add an import.)

    TODO(benkraft): Perhaps we should instead return the full text of the
    import we should add, if applicable?
    """
    # If name_to_import is already imported in this file,
    # figure out what the localname for our symbol would
    # be using this existing import.  That is, if we are moving
    # 'foo.myfunc' to 'bar.myfunc' and this file already has
    # 'import bar as baz' then existing_new_localnames would be
    # {'baz.myfunc'}.
    existing_new_localnames = {
        ln.localname
        for ln in model.localnames_from_fullnames(file_info, {fullname})
        if ln.imp is None or name_to_import == ln.imp.name
    }

    if existing_new_localnames:
        # Prefer an existing explicit import to the caller-provided alias.
        # If for some reason there are multiple existing localnames
        # (unlikely), choose the shortest one, to save us line-wrapping.
        # TODO(benkraft): this might not be totally safe if the existing
        # import isn't toplevel, but probably it will be.
        return min(existing_new_localnames, key=len), False
    elif import_alias:
        return import_alias + fullname[len(name_to_import):], True
    else:
        return fullname, True


def _add_contextless_import_patch(file_info, import_texts):
    """Add imports to the file_info, in a reasonable place.

    We use this in the case where there is no particular context to copy or
    point at which to place the import; we just want to guess something
    reasonable -- near existing imports if any.

    Arguments:
        file_info: the File object to add to.
        import_texts: a list of import statements as strings, like
            'from foo import bar'.

    Returns a patch.
    """
    joined_imports = ''.join(import_texts)
    last_toplevel_import = None
    for stmt in file_info.tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            last_toplevel_import = stmt

    if last_toplevel_import:
        start, end = util.get_area_for_ast_node(
            last_toplevel_import, file_info, include_previous_comments=False)
        return khodemod.Patch(
            file_info.filename, '', joined_imports, end, end)
    else:
        # There are no existing toplevel imports.  Find the first
        # place to add an import: after any comments, docstrings,
        # and newlines.  (*Not* after indents and the like!)
        # TODO(benkraft): We should really add before trailing
        # whitespace, but fix_pytnon_imports will mostly fix that.
        for tok in file_info.tokens.tokens:
            if not (tok.type == tokenize.COMMENT
                    or tok.type == tokenize.STRING
                    or util.is_newline(tok)):
                pos = tok.startpos
                break
        else:
            # The file has no code; add at the end.
            pos = len(file_info.body)

        # We add the absolute_import because KA style requires it.
        # (It's a good idea anyway.)
        text_to_add = (
            'from __future__ import absolute_import\n\n'
            '%s\n\n' % joined_imports)

        return khodemod.Patch(file_info.filename, '', text_to_add, pos, pos)


def _determine_import_to_add(import_alias, name_to_import, old_localnames,
                             file_info):
    """Determine the import to use for the import of a renamed symbol.

    If you've renamed foo.bar.myfunc() to baz.bang.myfunc(), and you're
    now editing somefile.py to change its call of foo.bar.myfunc() to
    baz.bang.myfunc(), you're probably going to have to replace somefile's
    `import foo.bar` with `import baz.bang`.  Or maybe you're replacing
    somefile's `from foo import bar` with `from baz import bang`?  Or
    `import foo.bar as foo_bar` with `import baz.bang as baz_bang`?  This
    is the function that determines what syntax to use for the new
    (baz.bang) import.

    In the easy case, import_alias tells us the alias to use for the new
    import.  But usually import_alias will be a special value: FROM,
    NONE, RELATIVE, or AUTO.  In the FROM case, we return an alias that
    will turn name_to_import into a from-import.  In the NONE case, we
    return an alias that will leave name_to_import untouched.  In the
    RELATIVE case, we write the import as a relative import, if it's
    reasonable to do so, and use FROM otherwise.  In the AUTO case,
    we'll keep the same form that the old import (`import foo.bar` or
    `from bar import foo` or whatever`) had.  old_localnames is the
    structure that lets us figure that out.

    Returns an Import object that we should add.
    """
    # When resolving the alias, we need to know what import we might be
    # replacing.  We only consider the "best" such import.  Luckily
    # old_localnames is in quality order.
    old_import = next((ln.imp for ln in old_localnames if ln.imp is not None),
                      None)

    # If import_alias is AUTO, use old_localnames to figure out what
    # kind of alias we actually want to use.
    if import_alias == 'AUTO':
        if not old_import:
            # No existing import to go by -- perhaps the symbol used to exist
            # locally in this file -- so we just default to full-import.
            import_alias = 'NONE'
        elif old_import.relativity == 'explicit':
            # The old import was relative -- keep it if we (reasonably) can.
            import_alias = 'RELATIVE'
        elif old_import.alias == old_import.name:
            # The old import is a regular, full import.
            import_alias = 'NONE'
        elif old_import.alias == old_import.name.rsplit('.', 1)[1]:
            # The old import is a from-import.
            import_alias = 'FROM'
        else:
            # The old import is an as-import.
            import_alias = old_import.alias

    # Now resolve the alias.
    relativity = 'absolute'
    if import_alias == 'RELATIVE':
        module_name = util.module_name_for_filename(file_info.filename)
        if old_import and hasattr(old_import.node, 'level'):
            max_level = max(1, old_import.node.level)
        else:
            max_level = 1

        if max_level > module_name.count('.'):
            # The ... gets us all the way back up to the root.
            # This is a questionable idea, so we only do it if
            # we're closely following an existing import.
            if old_import and old_import.relativity == 'explicit':
                relativity = 'explicit'
        else:
            max_relative_to = module_name.rsplit('.', max_level)[0]
            if name_to_import.startswith(max_relative_to):
                relativity = 'explicit'
            # Otherwise, this would require making the relative import go
            # further up than it did before; we make the somewhat-arbitrary
            # choice that FROM (rather than NONE) is the best fallback.)

    if import_alias in ('NONE', None):
        import_alias = name_to_import
    elif import_alias in ('RELATIVE', 'FROM'):
        import_alias = name_to_import.rsplit('.', 1)[-1]

    return model.Import(
        name_to_import, import_alias, relativity, None, file_info)


# TODO(benkraft): Once slicker can do it relatively easily, move the
# use-fixing suggestors and helpers to their own file.
def _fix_uses_suggestor(old_fullname, new_fullname,
                        name_to_import, import_alias=None):
    """The suggestor to fix all references to a file or symbol.

    Note that this adds new imports for any references we updated, but does not
    remove the old ones; see removal.remove_imports_suggestor.

    Arguments:
        old_fullname: the pre-move fullname (module when moving a module,
            module.symbol when moving a symbol) that we're moving.
        new_fullname: the post-move fullname (module when moving a module,
            module.symbol when moving a symbol) that we're moving.
        name_to_import: the module or module.symbol we want to add to
            provide access to new_fullname.  (KA style is to disallow
            importing symbols explicitly, so it would always be the module
            for KA code.)  If you are moving a module, name_to_import should
            probably be the same as new_fullname (though it could technically
            be a prefix of new_fullname).
        import_alias: what to call the import.  Logically, we will suggest
            adding "import name_to_import as import_alias" though we may
            use "from" syntax if it amounts to the same thing.  It can
            also be a special value:
               "FROM": always use from-syntax for every use we fix
               "NONE" (or None): always use name_to_import
               "RELATIVE": use relative-import syntax when reasonable
               "AUTO": if the import we're fixing used `from` or `as`,
                       we do too; if it was relative, we do that too;
                       otherwise we use name_to_import.
    """
    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        old_last_part = old_fullname.rsplit('.', 1)[-1]
        if old_last_part not in body:
            # As an optimization, don't operate on files that definitely don't
            # mention the moved symbol at all.  (For many moves, that's most of
            # them!)   We check for the last part of it, because that catches
            # all the different ways you can refer to it (including e.g.
            # 'import a.x ; a.b.c()' and 'from a.b import c as d ; d()').  It
            # might be better to do a regex search for '\b<old_last_part>\b'
            # but the difference doesn't seem worth the extra time.  This does
            # miss one case: string references where you split the string in
            # the middle of an identifier.  Those are hopefully rare.
            return

        file_info = util.File(filename, body)

        # First, set things up, and do some checks.
        assert util.dotted_starts_with(new_fullname, name_to_import), (
            "%s isn't a valid name to import -- not a prefix of %s" % (
                name_to_import, new_fullname))

        old_localnames = list(  # so we can re-use it
            model.localnames_from_fullnames(file_info, {old_fullname}))
        old_localname_strings = {ln.localname for ln in old_localnames}

        # Figure out what the new import should look like.
        new_import = _determine_import_to_add(
            import_alias, name_to_import, old_localnames, file_info)

        new_localname, need_new_import = _choose_best_localname(
            file_info, new_fullname, name_to_import, new_import.alias)

        # Now, patch references -- replace_in_file does all the work.
        patches, used_localnames = replacement.replace_in_file(
            file_info, old_fullname, old_localname_strings,
            new_fullname, new_localname)
        for patch in patches:
            yield patch

        # Finally, add a new import, if necessary.
        if need_new_import and used_localnames:
            conflicting_imports = _check_import_conflicts(
                file_info, old_fullname, new_import.alias,
                new_import.alias != new_import.name)
            if conflicting_imports:
                raise khodemod.FatalError(
                    file_info.filename, conflicting_imports.pop().start,
                    "Your alias will conflict with imports in this file.")

            old_imports = {ln.imp for ln in old_localnames
                           if ln.imp is not None}

            # Decide where to add the new import.  The issue here is that
            # we may be replacing a "late import" (an import inside a
            # function) in which case we want the new import to be
            # inside the same function at the same place.  In fact, we
            # might be late-importing the same module in *several*
            # functions, and each one has to get replaced properly.
            explicit_imports = {
                imp for imp in old_imports
                # TODO(benkraft): This is too weak -- we should only
                # call an import explicit if it is of the symbol's module
                # (see special case (2) in module docstring).
                if util.dotted_starts_with(old_fullname, imp.name)}

            if not explicit_imports:
                # We need to add a totally new toplevel import, not
                # corresponding to an existing one.  (So we also don't
                # need to worry about copying comments or indenting.)
                yield _add_contextless_import_patch(
                    file_info, ['%s\n' % new_import.import_stmt()])
            else:
                # There were existing imports of the old name,
                # so we try to match those.
                # TODO(benkraft): This doesn't work correctly in the case
                # where there was an implicit toplevel import, and an
                # explicit late import, and the moved symbol was used
                # outside the scope of the late import.  To handle this
                # case, we'll need to do much more careful tracing of which
                # imports exist in which scopes.
                for imp in explicit_imports:
                    # Copy the old import's context, such as opening indent
                    # and trailing newline.
                    # TODO(benkraft): If the context we copy is a comment, and
                    # we are keeping the old import, maybe don't copy it?
                    # TODO(benkraft): Should we look at preceding comments?
                    # We end up fighting with fix_python_imports if we do.
                    start, end = util.get_area_for_ast_node(
                        imp.node, file_info, include_previous_comments=False)
                    pre_context = body[start:imp.start]
                    post_context = body[imp.end:end]
                    # Now we can add the new import and have the same context
                    # as the import we are taking the place of!
                    text_to_add = ''.join(
                        [pre_context, new_import.import_stmt(), post_context])
                    yield khodemod.Patch(filename, '', text_to_add,
                                         start, start)

    return suggestor


def _fix_moved_region_suggestor(project_root, old_fullname, new_fullname):
    """Suggestor to fix up all the references to symbols in the moved region.

    When we move the definition of a symbol, it may reference other things in
    the source and/or destination modules as well as itself.  We need to fix up
    those references.  This works a lot like _fix_uses_suggestor, but we're
    actually sort of doing the reverse, since it's our code that's moving while
    the things we refer to stay where they are.  Like _fix_uses_suggestor, we
    additionally add necessary imports to the new file, although we leave it to
    removal.remove_moved_region_imports_suggestor to remove now-unused imports
    from the old file.

    Note that this should run after move_symbol_suggestor; it operates on the
    definition in its new location.  It only makes sense for symbols; when
    moving modules we don't encounter this issue.

    Arguments:
        project_root: as elsewhere
        old_fullname, new_module: the fullname of the symbol we are
            moving, before and after the move.
    """
    old_module, old_symbol = old_fullname.rsplit('.', 1)
    new_module, new_symbol = new_fullname.rsplit('.', 1)

    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        # We only need to operate on the new file; that's where the moved
        # region will be by now.  (But we do look at both old and new.)
        # Caller should ensure this but we check to be safe.
        if util.module_name_for_filename(filename) != new_module:
            return

        file_info = util.File(filename, body)
        old_filename = util.filename_for_module_name(old_module)
        old_file_info = util.File(
            old_filename,
            khodemod.read_file(project_root, old_filename) or '')

        # Find the region we moved.
        toplevel_names_in_new_file = util.toplevel_names(file_info)
        if new_symbol not in toplevel_names_in_new_file:
            raise khodemod.FatalError(filename, 0,
                                      "Could not find symbol '%s' in "
                                      "'%s': maybe it's defined weirdly?"
                                      % (new_symbol, new_module))
        node_to_fix = toplevel_names_in_new_file[new_symbol]

        # The moved region is full of localnames that make sense in the context
        # of old_file, but not new_file (since a localname depends on the
        # imports of the file, plus on whether it is a reference to something
        # in the current file).  For instance, if the code reegion had the text
        # `return oldfile_func() + newfile.newfile_func()` we want to rewrite
        # that to say `return oldfile.oldfile_func() + newfile_func()`, as well
        # as adding `import oldfile` to newfile.

        # Here, we make a LocalName object for each such localname, which will
        # help us rewrite them and add imports later.
        names_in_moved_code = {
            name for name, node in util.all_names(node_to_fix)}
        # To construct the LocalNames, we typically need to associate an import
        # with them.  These imports live in the old file, if they're toplevel,
        # because that's where this code snippet used to live, or in the moved
        # region itself, if they're late.
        old_imports = itertools.chain(
            model.compute_all_imports(old_file_info, toplevel_only=True),
            model.compute_all_imports(file_info, within_node=node_to_fix))
        # Now construct the localnames.  The only special case is the moved
        # symbol itself, because it's already been moved to the new file, so
        # when we look at the old file we won't find it.
        localnames_in_old_file = list(model.localnames_from_localnames(
            old_file_info, names_in_moved_code, old_imports))
        localnames_in_old_file.append(
            model.LocalName(old_fullname, old_symbol, None))
        # We construct a dict where, for each localname we've found above, we
        # map from the new fullname associated with the localname to the
        # LocalName object (containing the old fullname and its localname in
        # the old file).  (Note that for every symbol except the moved symbol,
        # those two fullnames are the same.)  Usually there will be only one
        # such localname for each fullname, but in case there are multiple (for
        # reasons described in the docstring of localnames_from_fullnames), we
        # actually store a set of such LocalName objects.
        names_to_fix = {}
        for localname in localnames_in_old_file:
            if localname.fullname == old_fullname:
                # This is the moved symbol; we found it under its old fullname
                # but we want to track it under its new fullname.
                names_to_fix.setdefault(new_fullname, set()).add(localname)
            else:
                names_to_fix.setdefault(localname.fullname, set()).add(
                    localname)

        # If name-to-fix A is a prefix of name-to-fix B, then we can remove
        # B: it will get fixed when A does!  This happens for code like:
        #   fn(module_to_move.myclass, module_to_move.myclass.classvar)
        names_to_fix = {
            name: value for (name, value) in names_to_fix.iteritems()
            if not any(prefix in names_to_fix
                       for prefix in util.dotted_prefixes(
                               name, proper_only=True))
        }

        # Now, we fix up each name in turn.  This is the part that follows
        # _fix_uses_suggestor fairly closely.
        imports_to_add = set()
        for new_fullname_to_fix, old_localnames_to_fix in (
                names_to_fix.iteritems()):
            old_localname_strings = {
                ln.localname for ln in old_localnames_to_fix}
            # Find the old fullname (which should be the fullname in each item
            # of old_localnames_to_fix) and choose an import that we got it
            # from -- we choose the one with the shortest alias to minimize
            # line-wrapping.
            old_fullname_to_fix, _, imp = min(
                old_localnames_to_fix,
                key=lambda ln: -1 if ln.imp is None else len(ln.imp.alias))

            # Figure out by what name we'll refer to new_fullname_to_fix in the
            # new file.  _choose_best_localname does most of the work, but we
            # have to figure out what module we want to tell
            # _choose_best_localname to import if necessary.
            if imp and util.dotted_starts_with(new_fullname_to_fix, imp.name):
                # If we got new_fullname_to_fix from an explicit import in the
                # old file, we'll do whatever that import did.
                name_to_import = imp.name
                import_alias = imp.alias
            elif imp:
                # If we got new_fullname_to_fix from an implicit import in the
                # old file, we'll still do whatever that import did.
                # TODO(benkraft): If we had an implicit import, we should
                # probably make it explicit rather than just copying.
                name_to_import = imp.name
                import_alias = None
            else:
                # If there was no corresponding import, we know this was a
                # symbol in the old file, so we tell _choose_best_localname to
                # import the module (where it now lives -- which is different
                # for the moved symbol itself), with no alias.
                # TODO(benkraft): Allow specifying an alias for the old module
                # in the new file.
                name_to_import, _ = new_fullname_to_fix.rsplit('.', 1)
                import_alias = None

            new_localname, need_new_import = _choose_best_localname(
                file_info, new_fullname_to_fix, name_to_import,
                import_alias)

            # Now, patch references.
            patches, used_localnames = replacement.replace_in_file(
                file_info, old_fullname_to_fix, old_localname_strings,
                new_fullname_to_fix, new_localname, node_to_fix)
            for patch in patches:
                yield patch

            # We also *add* imports in this suggestor, because otherwise it's
            # too hard to tell what imports we need to add by the time we get
            # to removal.remove_moved_region_imports_suggestor.  Luckily, that
            # doesn't complicate things much here.
            if used_localnames and need_new_import:
                conflicting_imports = _check_import_conflicts(
                    file_info, old_fullname, import_alias or name_to_import,
                    bool(import_alias))
                if conflicting_imports:
                    raise khodemod.FatalError(
                        file_info.filename, conflicting_imports.pop().start,
                        "Your alias will conflict with imports in this file.")

                if imp and (not imp.relativity == 'explicit' or
                            old_module.split('.')[:-imp.node.level] ==
                            new_module.split('.')[:-imp.node.level]):
                    # Otherwise, if we have an import, and it's not relative,
                    # or it is, but the new and old module are in the same
                    # package, we can keep it -- just copy the text.
                    # For example, maybe we're moving 'from . import baz'
                    # from foo/bar.py to foo/foobar.py, we can keep it,
                    # but if we moved it to newfoo/bar.py, we have to
                    # write 'from foo import baz' instead.
                    start, end = util.get_area_for_ast_node(
                        imp.node, old_file_info,
                        include_previous_comments=False)
                    import_stmt = old_file_info.body[start:end]
                else:
                    # Otherwise, we must create an import out of whole cloth,
                    # or at least rewrite it a bit -- decide what text to use.
                    #
                    # If rewriting, we make sure to keep the alias -- that is,
                    # we convert 'from . import bar' to 'from foo import bar',
                    # rather than falling back on a fully qualified import
                    # ('import foo.bar').
                    new_import = model.Import(
                        name_to_import, imp.alias if imp else name_to_import,
                        relativity='absolute', node=None, file_info=file_info)
                    import_stmt = '%s\n' % new_import.import_stmt()
                imports_to_add.add(import_stmt)

        if imports_to_add:
            yield _add_contextless_import_patch(file_info, imports_to_add)

    return suggestor


def make_fixes(old_fullnames, new_fullname, import_alias=None,
               project_root='.', automove=True, verbose=False):
    """Do all the fixing necessary to move old_fullnames to new_fullname.

    Arguments: parallel to the commandline -- see there for details.

    We proceed as follows.  Each step runs one or more khodemod suggestors to
    make its changes.
    1) Figure out what the inputs mean, in terms of what modules/symbols need
       to go where (inputs.expand_and_normalize).
    2) For each moved module or symbol:
       2a) If automove is set, and we're moving a module, simply move it to its
           new filename (moves.move_module_suggestor).
       2b) If automove is set, and we're moving a symbol, first move the
           definition-region (moves.move_symbol_suggestor), then update
           it and the imports of the source and destination files to match
           (_fix_moved_region_suggestor and
           removal.remove_moved_region_imports_suggestor).
    3) Fix references in all other files, including updating their imports
       (_fix_uses_suggestor and removal.remove_imports_suggestor).
    4) Clean up: remove the module(s) we moved things out of, if it is now
       empty (cleanup.remove_empty_files_suggestor), and resort imports in any
       file we touched (cleanup.import_sort_suggestor).
    """
    def log(msg):
        if verbose:
            print msg

    # TODO(benkraft): Support other khodemod frontends.
    frontend = khodemod.AcceptingFrontend(verbose=verbose)

    # Return a list of (old_fullname, new_fullname) pairs that we can rename.
    old_new_fullname_pairs = inputs.expand_and_normalize(
        project_root, old_fullnames, new_fullname)

    for (oldname, newname, is_symbol) in old_new_fullname_pairs:
        if automove:
            log("===== Moving %s to %s =====" % (oldname, newname))
            if is_symbol:
                old_filename = util.filename_for_module_name(
                    oldname.rsplit('.', 1)[0])
                move_suggestor = moves.move_symbol_suggestor(
                    project_root, oldname, newname)
            else:
                old_filename = util.filename_for_module_name(oldname)
                move_suggestor = moves.move_module_suggestor(
                    project_root, oldname, newname)
            frontend.run_suggestor_on_files(move_suggestor, [old_filename],
                                            root=project_root)
            if is_symbol:
                new_filename = util.filename_for_module_name(
                    newname.rsplit('.', 1)[0])
                fix_moved_region_suggestor = _fix_moved_region_suggestor(
                    project_root, oldname, newname)
                frontend.run_suggestor_on_files(
                    fix_moved_region_suggestor, [new_filename],
                    root=project_root)

                remove_old_file_imports_suggestor = (
                    removal.remove_old_file_imports_suggestor(
                        project_root, oldname))
                frontend.run_suggestor_on_files(
                    remove_old_file_imports_suggestor, [old_filename],
                    root=project_root)

                remove_moved_region_late_imports_suggestor = (
                    removal.remove_moved_region_late_imports_suggestor(
                        project_root, newname))
                frontend.run_suggestor_on_files(
                    remove_moved_region_late_imports_suggestor, [new_filename],
                    root=project_root)

        log("===== Updating references of %s to %s =====" % (oldname, newname))
        if is_symbol:
            name_to_import = newname.rsplit('.', 1)[0]
        else:
            name_to_import = newname

        fix_uses_suggestor = _fix_uses_suggestor(
            oldname, newname, name_to_import, import_alias)
        frontend.run_suggestor(fix_uses_suggestor, root=project_root)

        remove_imports_suggestor = removal.remove_imports_suggestor(oldname)
        frontend.run_suggestor_on_modified_files(remove_imports_suggestor)

    log("===== Cleaning up empty files & whitespace =====")
    frontend.run_suggestor_on_modified_files(
        cleanup.remove_empty_files_suggestor)
    frontend.run_suggestor_on_modified_files(
        cleanup.remove_leading_whitespace_suggestor)

    log("===== Resorting imports =====")
    import_sort_suggestor = cleanup.import_sort_suggestor(project_root)
    frontend.run_suggestor_on_modified_files(import_sort_suggestor)

    log("===== Move complete! =====")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('old_fullnames', metavar='old_fullname', nargs='+',
                        help=('fullname to move: can be path.to.package, '
                              'path.to.package.module, '
                              'path.to.package.module.symbol, '
                              'some/dir, some/dir/file.py, or "-" to read '
                              'such inputs from stdin (one per line)'))
    parser.add_argument('new_fullname',
                        help=('fullname to rename to. This can always be of '
                              'the same "type" as old_fullname, but can '
                              'also be one level up: e.g. moving a symbol '
                              'to a module, or a module to a package. It '
                              '*must* be one level up if multiple '
                              'old_fullnames are specified.'))
    parser.add_argument('--no-automove', dest='automove',
                        action='store_false', default=True,
                        help=('Do not automatically move OLD_FULLNAME to '
                              'NEW_FULLNAME. Callers must do that before '
                              'running this script.'))
    parser.add_argument('-a', '--alias', default='AUTO',
                        help=('Alias to use when adding new import lines.  '
                              'This is the module-alias, even if you are '
                              'moving a symbol.  Should be a python name '
                              'or one of the special values: AUTO FROM NONE. '
                              'AUTO says to use the same format as the import '
                              'it is replacing (on a case-by-case basis). '
                              'FROM says to always use a from-import. '
                              'RELATIVE says to use a relative import '
                              'when reasonable, and FROM otherwise. '
                              'NONE says to always use the full import. '
                              'Default is %(default)s'))
    parser.add_argument('-f', '--use-from', action='store_true',
                        help='Convenience flag for `-a FROM`')
    parser.add_argument('--root', default='.',
                        help=('The project-root of the directory-tree you '
                              'want to do the renaming in.  old_fullname, '
                              'and new_fullname are taken relative to root.'))
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Print some information about what we're doing.")
    parsed_args = parser.parse_args()

    if parsed_args.old_fullnames == ['-']:
        old_fullnames = sys.stdin.read().splitlines()
    else:
        old_fullnames = parsed_args.old_fullnames

    if parsed_args.use_from:
        alias = 'FROM'
    else:
        alias = parsed_args.alias or 'NONE'    # empty string is same as NONE

    make_fixes(
        old_fullnames, parsed_args.new_fullname,
        import_alias=alias,
        project_root=parsed_args.root,
        automove=parsed_args.automove,
        verbose=parsed_args.verbose)


if __name__ == '__main__':
    # Note that pip-installed slicker calls main() directly, rather than
    # running this file as a script; this is just included for completeness.
    main()
