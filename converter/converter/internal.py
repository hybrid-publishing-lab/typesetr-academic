"""Constructors for the (html-like) internal doc representation."""
from collections import OrderedDict

from .ezmatch import Var, Seq

def is_code_font(name):
    return name and (name.lower().endswith(' mono') or name in (
        'Anonymous Pro', 'Consolas', 'Courier', 'Courier New', 'Envy Code R',
        'Fixed', 'fixed'
        'GNU Unifont', 'Inconsolata', 'Inconsolata-g', 'Lucida Console',
        'M+ 1m', 'Menlo', 'Monaco', 'Monofur', 'OCR-A', 'OCR-B',
        'Pragmata Pro', 'Source Code Pro', 'Terminal', 'Terminus',
    ))

# there is also .block, but it's just intermediate
PSEUDO_BLOCK_TAGS = ('.footnote', '.pagebreak', 'title', 'subtitle')
PSEUDO_INLINE_TAGS = () # must not cull space around it

INLINE_TAG = ('span',
              'a',
              'b', 'i', 's', 'u',
              # 'em', 'strong',
              # 'mark',
              'sup', 'sub', 'small', # big is dead
              'code', # 'kbd', 'var', 'samp',
              # 'abbr', 'time',
              'cite', # 'q'
              # 'dfn',
              'wbr',
             ) + PSEUDO_INLINE_TAGS
H_TAGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
INLINE_BLOCK_TAGS = (
    #'data', 'del', 'ins',
)
TABLE_TAGS = (
    # 'thead', 'tbody',
    'caption',
    'colgroup', 'col',
    'th', 'tr', 'td'
)

NON_EMPTY_BLOCK_TAGS = H_TAGS + (
    'dl', 'ol', 'ul',
    'li', 'dt', 'dd', # extra cat?
    'section', 'footer', #'header', 'hgroup',
    'p', 'aside', # article, 'output'
    #'noscript',
    'blockquote',
    'figure',
    'figcaption',
    'pre',
    # 'output',
    'table', 'tfoot',
    #'form', 'fieldset'
)
# XXX: main reason div is here is for `<div class="pagebreak"/>`,
BLOCK_TAGS = NON_EMPTY_BLOCK_TAGS + ('hr', 'br',
                                     'div') + TABLE_TAGS + PSEUDO_BLOCK_TAGS
MEDIA_TAGS = ('img',
              #'object',
              #'audio', 'video', 'canvas',
             )

ALLOWED_TAGS = INLINE_TAG + BLOCK_TAGS + MEDIA_TAGS + (
    'head', 'meta', 'body')

assert len(ALLOWED_TAGS) == len(set(ALLOWED_TAGS))

COLOR_TYPES = ('color', 'background-color')

# fully void = no body, and, optionally, not attrs either
FULLY_VOID_TAGS = ('hr', 'br', 'wbr') + TABLE_TAGS  + (
    '.pagebreak', 'figcaption', 'caption')

__all__ = ['mkcmd', 'mkel', 'mklit', 'varcmd', 'varlit']

def mkel(head, attrs, body, allow_var=False):
    """Sanity checking internal representation element constructor.

    >>> mkel('b', {}, ['bold'])
    ('b', {}, ['bold'])
    >>> mkel('b', {}, 'bold')
    Traceback (most recent call last):
    [...]
    AssertionError: Expected a list for the body, got 'bold'
    """
    assert (isinstance(head, basestring)
            or allow_var and isinstance(head, Var)), \
            ("Expected a basestring for the tag, got:%r" % (head,))
    assert (isinstance(attrs, dict) and 'style' not in attrs or
            allow_var and isinstance(attrs, (Var, dict)) or
            isinstance(attrs['style'], OrderedDict)), \
        ("Expected a dict for the attrs, got %r" % (attrs,))
    assert (isinstance(body, list) and (
        not body or type(body[0]) is not list)) or (
            allow_var and isinstance(body, (Var, type(Seq)))), \
        ("Expected a list for the body, got %r" % (body,))
    return (head, attrs, body)

def mkerr(body, description, *args, **kwargs):
    return mkel('ERR', {'info': [description, args, kwargs]},
                body)

def mkcmd(name, body=None, allow_var=False):
    """Sanity checking special command constructor.

    >>> mkcmd('author', ['Alexander Schmolck'])
    ('CMD', {'class': ['author']}, ['Alexander Schmolck'])
    """
    return mkel('CMD', {'class': [name]}, body if body is not None else [],
                allow_var)

def mklit(name, allow_var=False):
    return mkel('LIT', {'class': [name]}, [], allow_var)

def varlit(name):
    return mklit(name, True)

def varcmd(*args):
    """Like mkcmd, but also accepts Vars in all fields."""
    return mkcmd(*args, allow_var=True)

def varel(*args):
    """Like mkel, but also accepts Vars in all fields."""
    return mkel(*args, allow_var=True)

# pylint: disable=W0231
def shared(x, seen=None):
    """Debugging utility -- return any shared (mutable) structure(s) in `x`.
    """
    seen = seen or {}
    ans = []
    # Probably better here than:
    #     mutable = not isinstance(x, (basestring, int, float, NoneType))
    mutable = not x.__hash__
    if mutable and id(x) in seen:
        ans.append(x)
    else:
        seen[id(x)] = x
        if isinstance(x, (list, tuple, dict, set, frozenset)):
            for y in x:
                ans.extend(shared(y, seen).values())
    return dict((id(k), k) for k in ans)


def show_shared(x):
    """PPrint `x` with shared structure highlighted."""
    import pprint
    import struct
    import hashlib
    def hash_based_color(x):
        xs = struct.unpack('b'*3 + 'x'*13, hashlib.md5(str(x)).digest())
        r, g, b = (x % 6 for x in xs)
        return '\x1b[38;5;%dm' % (16 + (r * 36) + (g * 6) + b)

    class PP(pprint.PrettyPrinter):
        def __init__(self, x):
            pprint.PrettyPrinter.__init__(self)
            self.bad = set(shared(x).keys())

        def _format(self, object, *args): # pylint: disable=W0622
            bad = id(object) in self.bad and id(object)
            if bad:
                self._stream.write(hash_based_color(bad))
            pprint.PrettyPrinter._format(self, object, *args)
            if bad:
                self._stream.write('\x1b[0m')
    PP(x).pprint(x)


def add_class(attrs, *cs):
    if 'class' in attrs:
        assert attrs['class'] == sorted(set(attrs['class']))
    attrs = attrs.copy()
    classes = sorted(set(cs if 'class' not in attrs else
                         list(cs) + attrs['class']))
    attrs['class'] = classes
    return attrs

def iadd_style(attrs, *kvs):
    style = attrs.setdefault('style', OrderedDict())
    assert isinstance(style, OrderedDict)
    for (k, v) in zip(kvs, kvs[1:]):
        style[k] = v

def add_style(attrs, *kvs):
    attrs = attrs.copy()
    iadd_style(attrs, *kvs)
    return attrs

def _merge_attrs(a, b):
    """Merge attrs in `a` and `b`, possibly reusing structure.

    >>> a = {'class': ['a', 'b'], 'style': OrderedDict([('color', 'red')])}
    >>> merge_attrs(a, {}) is a
    False
    >>> merge_attrs(a, {'class': ['c']})
    {'style': OrderedDict([('color', 'red')]), 'class': ['a', 'b', 'c']}
    >>> b = {'class': ['a', 'b', 'c'],
    ...      'style': OrderedDict([('width', '100%'),('color', 'green')])}
    >>> merge_attrs(a, b)['class']
    ['a', 'b', 'c']
    >>> merge_attrs(a, b)['style']
    OrderedDict([('color', 'green'), ('width', '100%')])
    >>> merge_attrs({},  {'style': OrderedDict([('color', '#1f497d')])})
    {'style': OrderedDict([('color', '#1f497d')])}
    """
    attrs = a.copy()
    for what in set(a.keys() +  b.keys()):
        if what in ('style', 'class'):
            aw, bw = a.get(what, OrderedDict()), b.get(what, {})
            if aw or bw:
                if what == 'class':
                    attrs['class'] = (aw or []) + [v for v in bw if v not in aw]
                else:
                    aw = aw.copy()
                    for k in bw:
                        aw[k] = bw[k]
                    attrs[what] = aw
        else:
            if what in b:
                attrs[what] = b[what]
    return attrs

def merge_attrs(a, *bs):
    return reduce(_merge_attrs, bs, a)
