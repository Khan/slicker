"""Utils for handling unicode in source.

Slicker doesn't currently handle unicode identifiers properly -- they aren't
allowed in python 2 anyway -- but it does need to be able to work around
unicode in comments and docstrings.  But doing so is a bit weird, because ast
likes to operate on bytes (it will accept unicode, but effectively converts it
back to bytes, and complains if it has a coding comment), whereas asttokens
(not unreasonably) does everything in unicode.  (In the future, if we support
python 3, we'll also need to do everything in unicode; right now we'd be okay
with either.)  So we have to convert back and forth a bit; this file has utils
we use to do that.

TODO(benkraft): This breaks the rule that khodemod shouldn't do anything
file-format-specific.  Figure out a better way.
TODO(benkraft): If we move a symbol whose definition contains unicode, we don't
currently move/copy the magic coding comment correctly; fix that.
"""
from __future__ import absolute_import

import re

from . import khodemod


# From PEP 263: https://www.python.org/dev/peps/pep-0263/
_PYTHON_ENCODING_RE = re.compile(
    r'^[ \t\v]*#.*?coding[:=][ \t]*([-_.a-zA-Z0-9]+)')


def _get_encoding(filename, text):
    """Determine the encoding of a python file, per PEP 263.

    Note that text may be either string or unicode, depending on whether we're
    reading/decoding or writing/encoding.
    """
    if not filename.endswith('.py'):
        # Not implemented yet!
        return 'ascii'

    for line in text.splitlines()[:2]:
        match = _PYTHON_ENCODING_RE.search(line)
        if match:
            return match.group(1)
    return 'ascii'


def encode(filename, text):
    encoding = _get_encoding(filename, text)
    try:
        return text.encode(encoding)
    except UnicodeEncodeError as e:
        # This one is unlikely, if we decoded successfully, but it's possible
        # we wrote some bad data.
        raise khodemod.FatalError(
            filename, 1,
            "Invalid %s data in file: %s" % (encoding, e))


def decode(filename, text):
    encoding = _get_encoding(filename, text)
    try:
        return text.decode(encoding)
    except UnicodeDecodeError as e:
        raise khodemod.FatalError(
            filename, 1,
            "Invalid %s data in file: %s" % (encoding, e))
