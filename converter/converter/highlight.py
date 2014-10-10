import regex as re

from converter.ezmatch import Var

from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter, LatexFormatter # pylint: disable=E0611

# FIXME(alexander): this is a mere toy, obviously, but
# good enough for testing purposes. It shouldn't be too hard
# to make this work well with a probabilistic approach.
# pylint: disable=R0911
# pylint: disable=C0301
def _guess_lang(s):
    if re.search(r'(def|class) \w+\(.*\):\s|lambda [^()]+:|if \w.*:', s):
        return 'python'
    if re.search(r'\send\n|(do\s+|\{)\|\w ', s):
        return 'ruby'
    if re.search(r'^(public|private|protected|\s+) class \w+(implements|extends|\{)', s):
        return 'java'
    if re.search(r'^#(define|include|ifdef)\b|\s\*+[a-z]', s):
        return 'c'
    if re.search(r'function [\w$]*\([^()]+\)\{|(if|for|switch|while|catch) \(.*\)\s+\{', s):
        return 'javascript'
    if re.search(r'{\n?\s*[\w-]+:', s):
        return 'css'
    if re.search(r'<(div|span|h[1-6]|a|b|i|p|li|dt|tr|br|hr|img|script|meta|style|input)\b(\s+\w|>)', s):
        return 'html'
    if re.search(r'\\@?[A-Za-z]{2,}[{[]', s):
        return 'latex'
    if re.search(r'\(defn?\b', s):
        return 'clojure'
    if re.search(r'^(SELECT|INSERT INTO|DELETE FROM|UPDATE|CREATE|DROP)\b', s):
        return 'sql'
    if re.search(r'<?|</|/>', s):
        return 'xml'
    return 'bash'

# pylint: disable=C0103,W0622
def _as(format, node):
    PRE = Var('PRE')
    assert node == ('pre', {}, [PRE])
    s = PRE.val
    lang = _guess_lang(s)
    if format == 'html':
        formatter = HtmlFormatter()
    elif format == 'latex':
        formatter = LatexFormatter()
    else:
        raise RuntimeError('Not a valid output format: %r' % format)
    return highlight(s, get_lexer_by_name(lang), formatter)

def as_html(node):
    # HACK(alexander): strip the bogus surrounding div that pygments
    # uses. A `<code>` element might make sense, but this doesn't
    return re.sub(r'(?s)\A<div[^>]*>(.*)</div>\n\Z', '\n\\1\n', _as('html', node))

def as_latex(node):
    return _as('latex', node)
