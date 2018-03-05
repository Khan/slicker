"""Suggestors relating to removing no longer needed imports.

This file contains the suggestors (in the sense of khodemod.py) which pertain
to removing imports that are no longer used.  After making other changes,
slicker often needs to move imports; we think of this as adding a new import,
and removing an old one.  (In some cases we only do one or the other -- if the
old import is still used, or the new one already exists.) This file is
responsible for the latter.  (The former is generally handled by the suggestor
that moved the reference to the import, since that is more tied to the other
changes being made.)
"""
from __future__ import absolute_import

import tokenize

from . import khodemod
from . import model
from . import util


def _unused_imports(imports, old_fullname, file_info, within_node=None):
    """Decide what imports we can remove.

    Note that this should be run after the patches to references in the file
    have been applied, i.e. in a separate suggestor.

    Arguments:
        imports: set of imports to consider removing.  These should likely be
            the imports that got us the symbol whose references you're
            updating.
        old_fullname: the fullname we deleted.  If it's of a module, then
            imports of that module are definitely unused (as that module
            no longer exists).  If it's of a symbol, this is ignored
            unless old_fullname was an import of just that symbol.
        file_info: the util.File object.
        within_node: if set, only consider imports within this AST node.
            (Useful for deciding whether to remove imports in that node.)

    Returns (set of imports we can remove,
             set of imports that may be used implicitly).

    "set of imports that may be used implicitly" is when we do
    "import foo.bar" and access "foo.baz.myfunc()" -- see
    special case (1) in the module docstring.
    """
    if within_node is None:
        within_node = file_info.tree
    # Decide whether to keep the old import if we changed references to it.
    unused_imports = set()
    implicitly_used_imports = set()
    for imp in imports:
        # This includes all names that we might be *implicitly*
        # accessing via this import (special case (1) of the
        # module docstring, e.g. 'import foo.bar; foo.baz.myfunc()'.
        implicitly_used_names = util.names_starting_with(
            imp.alias.split('.', 1)[0], within_node)
        # This is only those names that we are explicitly accessing
        # via this import, i.e. not via such an "implicit import".
        explicitly_referenced_names = [
            name for name in implicitly_used_names
            if util.dotted_starts_with(name, imp.alias)]

        if imp.name == old_fullname:
            unused_imports.add(imp)
        elif explicitly_referenced_names:
            pass  # import is used
        elif implicitly_used_names:
            implicitly_used_imports.add(imp)
        else:
            unused_imports.add(imp)

    # Now, if there was an import (say 'import foo.baz') we were considering
    # removing but which might be used implicitly, and we are keeping a
    # different import (say 'import foo.bar') that gets us the same things, we
    # can remove the former.
    # We need to compute the full list of imports to do this, because we want
    # to count even imports we weren't asked to look at -- if we were asked to
    # look at 'import foo.baz', an unrelated 'foo.bar' counts too.
    if within_node is file_info.tree:
        # Additionally, if we are not looking at a particular node, we should
        # only consider toplevel imports, since a late 'import foo.bar' doesn't
        # necessarily mean we can remove a toplevel 'import foo.baz'.
        # TODO(benkraft): We can remove the conditional by making
        # model.compute_all_imports support passing both within_node and
        # toplevel_only.
        all_imports = model.compute_all_imports(file_info, toplevel_only=True)
    else:
        all_imports = model.compute_all_imports(
            file_info, within_node=within_node)

    kept_imports = all_imports - unused_imports - implicitly_used_imports
    for maybe_removable_imp in list(implicitly_used_imports):
        prefix = maybe_removable_imp.alias.split('.')[0]
        for kept_imp in kept_imports:
            if util.dotted_starts_with(kept_imp.alias, prefix):
                implicitly_used_imports.remove(maybe_removable_imp)
                unused_imports.add(maybe_removable_imp)
                break

    return (unused_imports, implicitly_used_imports)


def _remove_import_patch(imp, file_info):
    """Remove the given import from the given file.

    Returns a khodemod.Patch, or a khodemod.WarningInfo if we can't/won't
    remove the import.
    """
    toks = list(file_info.tokens.get_tokens(imp.node, include_extra=False))
    next_tok = file_info.tokens.next_token(toks[-1], include_extra=True)
    if next_tok.type == tokenize.COMMENT and (
            '@nolint' in next_tok.string.lower() or
            '@unusedimport' in next_tok.string.lower()):
        # Don't touch nolinted imports; they may be there for a reason.
        # TODO(benkraft): Handle this case for implicit imports as well
        return khodemod.WarningInfo(
            file_info.filename, imp.start,
            "Not removing import with @Nolint.")
    elif ',' in file_info.body[imp.start:imp.end]:
        # TODO(benkraft): better would be to check for `,` in each
        # token so we don't match commas in internal comments.
        # TODO(benkraft): learn to handle this case.
        return khodemod.WarningInfo(
            file_info.filename, imp.start,
            "I don't know how to edit this import.")
    else:
        # TODO(benkraft): Should we look at preceding comments?
        # We end up fighting with fix_python_imports if we do.
        start, end = util.get_area_for_ast_node(
            imp.node, file_info, include_previous_comments=False)
        return khodemod.Patch(file_info.filename,
                              file_info.body[start:end], '', start, end)


def remove_imports_suggestor(old_fullname):
    """The suggestor to remove imports for now-changed references.

    Note that this should run after _fix_uses_suggestor.

    Arguments:
        old_fullname: the pre-move fullname (module when moving a module,
            module.symbol when moving a symbol) that we're moving.  (We
            only remove imports that could have gotten us that symbol.)
    """
    def suggestor(filename, body):
        file_info = util.File(filename, body)

        # First, set things up, and do some checks.
        # TODO(benkraft): Don't recompute these; _fix_uses_suggestor has
        # already done so.
        old_localnames = model.localnames_from_fullnames(
            file_info, {old_fullname})
        old_imports = {ln.imp for ln in old_localnames if ln.imp is not None}

        # Next, remove imports, if any are now unused.
        unused_imports, implicitly_used_imports = _unused_imports(
            old_imports, old_fullname, file_info)

        for imp in implicitly_used_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in unused_imports:
            yield _remove_import_patch(imp, file_info)

    return suggestor


def remove_old_file_imports_suggestor(project_root, old_fullname):
    """Suggestor to remove unused imports from old-file after moving a region.

    When we move the definition of a symbol, it may have been the only user of
    some imports in its file.  We need to remove those now-unused imports.
    This runs after _fix_moved_region_suggestor, which probably added some of
    the imports we will remove to the new location of the symbol.

    Arguments:
        project_root: as elsewhere
        old_fullname: the pre-move fullname of the symbol we are moving
    """
    # TODO(benkraft): Instead of having three suggestors for removing imports
    # that do slightly different things, have options for a single suggestor.
    old_module, old_symbol = old_fullname.rsplit('.', 1)

    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        # We only need to operate on the old file.  Caller should ensure this
        # but we check to be safe.
        if util.module_name_for_filename(filename) != old_module:
            return

        file_info = util.File(filename, body)

        # Remove toplevel imports in the old file that are no longer used.
        # Sadly, it's difficult to determine which ones might be at all related
        # to the moved code, so we just remove anything that looks unused.
        # TODO(benkraft): Be more precise so we don't touch unrelated things.
        unused_imports, implicitly_used_imports = _unused_imports(
            model.compute_all_imports(file_info, toplevel_only=True),
            old_fullname, file_info)
        for imp in implicitly_used_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in unused_imports:
            yield _remove_import_patch(imp, file_info)

    return suggestor


def remove_moved_region_late_imports_suggestor(project_root, new_fullname):
    """Suggestor to remove unused imports after moving a region.

    When we move the definition of a symbol, it may have imported its new
    module as a "late-import"; this suggestor removes any such import.
    It runs after _fix_moved_region_suggestor and
    remove_old_file_imports_suggestor, and only operates on the new file.
    TODO(benkraft): We should also remove late imports if the new file also
    imported the same module at the toplevel.

    Arguments:
        project_root: as elsewhere
        new_fullname: the post-move fullname of the symbol we are moving
    """
    new_module, new_symbol = new_fullname.rsplit('.', 1)

    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        # We only need to operate on the new file; that's where the moved
        # region will be by now.  Caller should ensure this but we check to be
        # safe.
        if util.module_name_for_filename(filename) != new_module:
            return

        file_info = util.File(filename, body)

        # Find the region we moved.
        toplevel_names_in_new_file = util.toplevel_names(file_info)
        if new_symbol not in toplevel_names_in_new_file:
            raise khodemod.FatalError(filename, 0,
                                      "Could not find symbol '%s' in "
                                      "'%s': maybe it's defined weirdly?"
                                      % (new_symbol, new_module))
        moved_node = toplevel_names_in_new_file[new_symbol]

        # Remove imports in the moved region itself that are no longer used.
        # This should probably just be imports of new_module, or things that
        # got us it, so we only look at those.
        unused_imports, implicitly_used_imports = _unused_imports(
            {imp for imp in model.compute_all_imports(
                file_info, within_node=moved_node)
             if model._import_provides_module(imp, new_module)},
            None, file_info, within_node=moved_node)
        for imp in implicitly_used_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in unused_imports:
            yield _remove_import_patch(imp, file_info)

    return suggestor
