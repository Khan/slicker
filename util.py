import ast
import os
import tokenize

import asttokens


def filename_for_module_name(module_name):
    """filename is relative to a sys.path entry, such as your project-root."""
    return '%s.py' % module_name.replace('.', os.sep)


def module_name_for_filename(filename):
    """filename is relative to a sys.path entry, such as your project-root."""
    return os.path.splitext(filename)[0].replace(os.sep, '.')


class File(object):
    """Represents information about a file.

    TODO(benkraft): Also cache things like _compute_all_imports.
    """
    def __init__(self, filename, body):
        """filename is relative to the value of --root."""
        self.filename = filename
        self.body = body
        self.tree = ast.parse(body)
        self.tokens = asttokens.ASTTokens(body, tree=self.tree)


def is_newline(token):
    # I think this is equivalent to doing
    #      token.type in (tokenize.NEWLINE, tokenize.NL)
    # TODO(benkraft): We don't really handle files with windows newlines
    # correctly -- any newlines we add will be wrong.  Do the right thing.
    return token.string in ('\n', '\r\n')


def get_area_for_ast_node(node, file_info, include_previous_comments):
    """Return the start/end character offsets of the input ast-node + friends.

    We include every line that node spans, as well as their ending newlines,
    though if the last line has a semicolon we end at the semicolon.

    If include_previous_comments is True, we also include all comments
    and newlines that directly precede the given node.
    """
    toks = list(file_info.tokens.get_tokens(node, include_extra=True))
    first_tok = toks[0]
    last_tok = toks[-1]

    if include_previous_comments:
        for istart in xrange(first_tok.index - 1, -1, -1):
            tok = file_info.tokens.tokens[istart]
            if (tok.string and not tok.type == tokenize.COMMENT
                    and not tok.string.isspace()):
                break
        else:
            istart = -1
    else:
        for istart in xrange(first_tok.index - 1, -1, -1):
            tok = file_info.tokens.tokens[istart]
            if tok.string and (is_newline(tok) or not tok.string.isspace()):
                break
        else:
            istart = -1

    # We don't want the *very* earliest newline before us to be
    # part of our context: it's ending the previous statement.
    if istart >= 0 and is_newline(file_info.tokens.tokens[istart + 1]):
        istart += 1

    prev_tok_endpos = (file_info.tokens.tokens[istart].endpos
                       if istart >= 0 else 0)

    # Figure out how much of the last line to keep.
    for tok in file_info.tokens.tokens[last_tok.index + 1:]:
        if tok.type == tokenize.COMMENT:
            last_tok = tok
        elif is_newline(tok):
            last_tok = tok
            break
        else:
            break

    return (prev_tok_endpos, last_tok.endpos)
