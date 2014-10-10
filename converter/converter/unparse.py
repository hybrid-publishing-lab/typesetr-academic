#-*- file-encoding: utf-8 -*-
from converter.postprocess import plaintextify

def unparse_literal(lit, roundtrip=True, plain=False): # pylint: disable=R0911
    """Return a string representation of `lit`.

    - `roundtrip` affects how literals with context-dependent values are
       hanlded, e.g.  when ``roundtrip=False`` then
       ``Date('today') -> "2014-01-01"`` (instead of ``"today"``).

    - `plain` controls if rich text content is converted to plaintext (e.g.
       for pdf or epub metadata)
    """
    # FIXME(alexander): try to break cyclic imports
    import converter.html_writer
    if lit is None:
        return '' # XXX(alexander)
    if isinstance(lit, basestring):
        return lit
    if isinstance(lit, bool):
        return ('no', 'yes')[lit]
    if not roundtrip and hasattr(lit, 'to_value'):
        return lit.to_value()
    if hasattr(lit, 'to_string'):
        return lit.to_string()
    if isinstance(lit, list): # Rich-text
        if plain:
            return plaintextify(lit)
        return converter.html_writer.write_body(lit)
    assert False, "Unknown literal type %r" % (lit,)
