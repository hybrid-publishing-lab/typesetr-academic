#-*- file-encoding: utf-8 -*-
from contextlib import contextmanager
from functools import partial
import logging as log
import regex as re
import unicodedata
import urlparse

from converter.citations import CITE_REX, EN_DASH
from converter.docerror import docproblem
from converter.ezmatch import Var, Seq
from converter.internal import mkel, H_TAGS
from converter import highlight
from converter import literal
from converter import postprocess
from converter.unparse import unparse_literal
from converter.utils import parse_percentage

UNICODE_TO_LATEX_TEXT = {
    u'#': '\\#',
    u'$': '\\$',
    u'%': '\\%',
    u'&': '\\&',
    u'<': '{\\textless}',
    u'>': '{\\textgreater}',
    u'\\':'{\\textbackslash}',
    u'^': '\\^{}', #FIXME \textasciicircum ?
    u'_': '\\_',
    u'`': '\\`{}',
    u'{': '\\{',
    u'|': '{\\textbar}',
    u'}': '\\}',
    u'~': '{\\textasciitilde}', # FIXME not necessarily ideal
    u'[': '{[}',
    u']': '{]}',
    u'\xa0': '~', #?
    # FIXME '', -, --, ---, ...,
    # FIXME: do ?` & !` need special treatment
}
UNICODE_TO_LATEX_TEXT_REX = re.compile(
    "[%s]" % "".join(map(re.escape, sorted(UNICODE_TO_LATEX_TEXT))))

SECTION_COMMANDS = ("part chapter "
                    "section subsection subsubsection paragraph subparagraph "
                    "subsubparagraph").split()

# `\def\languageshorthands#1{}` = nuke languageshorthands to prevent babel
# from extending the set of escape sequences in a language-specific fashion
# e.g. with language ngerman `"a` -> `ä` etc. breaking our escaping
BABEL_HEADER = r'''\usepackage[%(lang)s]{babel}
\usepackage[%(lang)s]{isodate}
\def\languageshorthands#1{}
'''


def entity(name, value):
    return cmd('newcommand', (), ('\\' + name, quote(value)))

def join(*xs):
    return "".join(xs)

def quote(s):
    return UNICODE_TO_LATEX_TEXT_REX.sub(
        lambda m: UNICODE_TO_LATEX_TEXT[m.group()], s)

def freshline(x):
    return u'\n' + x # FIXME replace w/ \v and cleanup

def nl(x): # pylint: disable=C0103
    return x + u'\n'

def mklabel(x):
    return cmd('label', [], [x])


EMPTY_CMD_ARGS = dict(
    item=' ')

def raw(s):
    return s

def cmd(name, opts=(), args=()):
    return u'\\%(name)s%(opts)s%(args)s' % dict(
        name=name,
        opts=''.join(
            map('[%s]'.__mod__, opts or [])),
        args=((''.join(map('{%s}'.__mod__, args)))
              if args
              else EMPTY_CMD_ARGS.get(name, '{}')))

def texcmd(name, body):
    return u'{\\%(name)s{}%(body)s}' % dict(
        name=name,
        body=body)

def env(name, body, opts, args):
    return '''\n\\begin{%(name)s}%(opts)s%(args)s
%(body)s\n
\\end{%(name)s}
''' % dict(name=name,
           body=body,
           opts=('[%s]' % ','.join(opts)) if opts else '',
           args=''.join(map('{%s}'.__mod__, args)))

## def _list(kind, items):
##     return env(kind, join(*(join(cmd('item'), ' ', item) for item in items)),
##                [],[])


def blockquote(text):
    return env('quoting', text, [], [])

def itemize(items):
    return env('tystrul', items, [], [])

def caption(text):
    return cmd('caption', [], [text])

def table(colspec, body, tablecaption=None):
    ncols = len(colspec)
    body_parts = (
        [env('tystrtable',
             tabular("".join(colspec), body), '', {2*ncols})] +
        ([caption(tablecaption)] if tablecaption is not None else []))
    if tablecaption is not None:
        return env('table', join(*body_parts), ['h'], [])
    else:
        return join(*body_parts)

def tabular(colspec, body):
    return env('tystrtabular',
               join(nl(r'\toprule'),
                    # FIXME(alexander): rstrip = hack for #694
                    nl(body.rstrip()),
                    nl(r'\tabularnewline'),
                    r'\bottomrule'),
               [],
               [colspec])

def rowh(body):
    return cmd('tystrth', [], [body])

def width_percentage_to_frac_str(width):
    return "%.4f" % (parse_percentage(width)/100)

# pylint: disable=C0103
def figure(img, width, classes, figcaption=None, # pylint: disable=R0913
           fakecaption=False, rawincludegraphics=False):
    width_frac_str = width_percentage_to_frac_str(width)
    if rawincludegraphics:
        fig = cmd('includegraphics',
                  [r'width=%s\linewidth' % width_frac_str],
                  [img])
        post = figcaption
    else:
        post = cmd('vspace', [], ['1.5em'])
        LARGE_FIGURE = "tystrfullwidthfigure"
        BASE_FIGURE = "tystrblockfigure"

        xlarge = 'fullwidth' in classes

        figure_cmd = LARGE_FIGURE if xlarge else BASE_FIGURE
        if figcaption is None:
            fig = cmd(figure_cmd + 'nocap', [width_frac_str], [img])
        else:
            if fakecaption:
                fig = join(nl(cmd(figure_cmd + 'nocap',
                                  [width_frac_str], [img])),
                           nl(figcaption))
            else:
                fig = cmd(figure_cmd, [width_frac_str], [figcaption, img])
    return nl(nl(join(nl(fig), post) if post else fig))

def metaimage(img, transclusions, width=None, display=None):
    args = []
    if width is not None:
        w = parse_percentage(width)/100.0
        args.append('width=%.3f' % w)
    if display is not None:
        args.append('display=' + display)
    src = transclusions.add_literal_image(img)
    return cmd('tystrimage', [','.join(args)], [src])

def colh(body):
    return cmd('tystrcolh', [], [body])

def marginfigure(img):
    return cmd('tystrmarginfigure', [], [img])

def textwidth_percent(percentage_str):
    return r'%.4f\unpaddedwidth-\nestedcolsep' % (
        parse_percentage(percentage_str)/100)


# FIXME(alexander): Originally this just extracted the labels right at the
# beginning of heading or list-element bodies, but now it pulls them
# everywhere, because gdocs odt export now apparently puts the bookmark labels
# at at the end of the heading body. The internal linking logic needs a bit of
# an overhaul anyway, as the whole point-anchor (a name=...) approach is
# weaker than what odt supplies (but that's unused in gdocs so far) and
# deprecated in html (ids are the way to go).
def extract_labels(body):
    HREF = Var('HREF')
    labels = []
    newbody = []
    for e in body:
        if e == ('a', {'name': HREF}, []):
            labels.append(HREF.val.lstrip('#'))
        else:
            newbody.append(e)
    return labels, newbody


def _make_url_escaper(chars):
    return partial(re.compile('[' + re.escape(chars) + ']').sub,
                   lambda c: '%%%X' % ord(c.group()))

_href_escape = _make_url_escaper(r'{}[]^\"|')

def url_fix(s):
    scheme, netloc, path, params, query, fragments = urlparse.urlparse(s)  # pylint: disable=W0633
    # pylint: disable=E1121
    # NB: path and params/query need normally to be escaped slightly differently
    # but for the stuff in _href_escape, I think we're good
    return urlparse.urlunparse([
        scheme, netloc.lower()] +
                               map(_href_escape,
                                   [path, params, query, fragments]))


def latexify_href(url):
    r"""Make an url safe as argument to hyperrefs \href command.

    \href attempts some escaping on its own, but this can't be relied upon and
    interently can't deal with latex's special `^^`, which happens before
    tokenization. Since hrefs can occur in moveable arguments, it seems wise
    urlencode everything that has special meaning in latex (one specific case
    where we ran into errors is '#', which normally gets handled fine; see
    <http://suchideas.com/articles/computing/latex/errors/>)

    >>> href = r'http://www.google.com/search?q={\weird\}%20[^chars^]:@#!'
    >>> print latexify_href(href)
    http://www.google.com/search?q=\%7B\%5Cweird\%5C\%7D\%20\%5B\%5Echars\%5E\%5D:@\#!
    """
    return _href_escape(url).replace('#', '\\#').replace('%', '\\%')

_NUM2ROMAN = "".join(map(chr, range(256))).replace('0123456789', 'ZABCDEFGHI')
def urldef(href, defs):
    if href.count('{') != href.count('}'):
        href = _href_escape(href)
    urlname = r'tystrurl%s' % str(len(defs) + 1).translate(_NUM2ROMAN)
    defs.append(raw(r'\urldef{\%s}\url{%s}' % (urlname, href)))
    return cmd(urlname, [], [])

def small(text):
    return  texcmd('small', text)

def red(text):
    return cmd('textcolor', [], ['red', text])

def problem_anchor(n, body):
    return join(cmd('hypertarget', [], ['docproblem%d' % n, '']), body)

def reduce_right(f, seq, *initial):
    return reduce(lambda x, y: f(y, x), reversed(seq), *initial)

def docwarns(latex_body, *warnings):
    ns = [docproblem(*warning, level='warning') for warning in warnings]
    return reduce_right(problem_anchor, ns, latex_body)

def docwarn(latex_body, warning_fmt, *args):
    return docwarns(latex_body, (warning_fmt,) + args)

NBSP = unicodedata.lookup('NO-BREAK SPACE')


MOVABLE = {'section'}


class LatexWriter(object):
    _PRIVATE1 = u'\ue001'
    # FIXME(alexander): should maybe add 'keywords' to the list below,
    # but then quoting commas should hopefully not be needed in keywords anyway
    # at least not in most cases
    _COMMA_SEPARATED_XMP_FIELDS = [
        'author',
        'contactemail', 'contactphone', 'contacturl', 'contactaddress']
    # pylint: disable=C0326
    INLINE_EMPH_TO_LATEX = dict(
        b='textbf', i='textit',
        u='uline',  s='sout') # these need ulem.sty or some manual defs

    def __init__(self, transclusions=None, section_corresponds_to='h1'):
        self.transclusions = transclusions
        self.section_offset = (SECTION_COMMANDS.index('section') -
                               H_TAGS.index(section_corresponds_to))
        assert section_corresponds_to in H_TAGS
        self.post_float_yuck = [] # latex stuff we need to write once we're
                                  # out of the float
        self.urldefs = [] # we need to move raw urls to the beginning
        self.context = [] # am I in a table, list etc?

    def xmp_meta(self, head):
        """Create XMP metadata for pdf (via hyperxmp.sty).

        Note that generating well structured pdf output with latex is a fool's
        errand, so this has some shortcomings:

        - dc:language  should be of type 'bag'.
        - XMP and info entries aren't synched for
          'xmp:CreateDate'/'CreationDate' and 'pdf:Producer'/'Producer'.
        - For PDF/A we'd also need 'pdfaid:part' and 'pdfaid:conformance', on
          first sight it looks like hypermp.sty takes a hardcoded guess, with
          two possible outcomes: nothing or PDF/A-1b.

        In an ideal world we'd probably only create valid PDF/A-2u or PDF/X
        documents, but both seem pretty much impossible to achieve from latex
        directly, with even the trivial metadata stuff above being a pain and
        then we'd also need to deal, at the very least, with ICC Profiles and
        unicode mappings (already somewhat painful for reasons of historical
        baggage in PDF and the font standards it supports and really horrible
        in latex because e.g. of issues with zero-width glyphs and math
        characters without unicode equivalent). PDF/A-2a would also require
        tagging.

        """
        fallbacks = {'description': 'abstract'}
        xmps = []
        for k in 'lang title author description keywords copyright'.split():
            if k in head:
                mk = k
            else:
                if not k in fallbacks or fallbacks[k] not in head:
                    continue
                mk = fallbacks[k]
            v = unparse_literal(head[mk], roundtrip=False, plain=True)
            # typesetr uses ';' to separate fields (like keywords or multiple
            # authors), because ',' is often ambiguous where ';' almost never
            # is.
            if k in self._COMMA_SEPARATED_XMP_FIELDS:
                if ',' in v:
                    v = v.replace(',', self._PRIVATE1).replace(';', ',')
                    latex_v = cmd('xmpquote', [],
                                  [self.latexify(v).replace(
                                      self._PRIVATE1, r'\xmpcomma{}')])
                else:
                    latex_v = self.latexify(v.replace(';', ','))
            else:
                latex_v = self.latexify(v)
            xmps.append(raw('pdf%s={%s}' %
                            (k if k != 'description' else 'subject', latex_v)))
        # FIXME(alexander): append version info?
        xmps.append(raw('pdfcreator={Typesetr}'))
        return ',\n'.join(xmps)



    def section(self, h, body, labels=[]): # pylint: disable=W0102
        hyperrefless_body = postprocess.whack(
            {'.footnote', 'figure', 'a'}.__contains__, body, True)
        # sections that have footnotes in them need special
        # handling to avoid latex chocking see:
        # <http://www.tex.ac.uk/cgi-bin/texfaq2html?label=ftnsect>
        if hyperrefless_body == body:
            opt = []
        else:
            opt = [self.latexify(postprocess.tidy(hyperrefless_body))]
        sec_cmd = SECTION_COMMANDS[H_TAGS.index(h) + self.section_offset]
        sec = freshline(nl(cmd(sec_cmd, opt, [self.latexify(body)])))
        if labels:
            return join(sec, nl(join(*map(mklabel, labels))))
        else:
            return sec

    def value_to_latex(self, value): # pylint: disable=R0911
        # FIXME: localize date, bools etc
        if isinstance(value, (basestring, tuple)):
            return self.latexify(value)
        if isinstance(value, literal.Multiline):
            # the '\mbox' is there to deal with empty lines since consecutive
            # '\\'s don't work
            return "\\\\\n".join(self.latexify(x) or r'\mbox{}'
                                 for x in value.data)
        if isinstance(value, (list, tuple)): # rich text
            return self.latexify(value)
        if isinstance(value, bool):
            return ('no', 'yes')[value]
        if isinstance(value, literal.Date):
            # this should handle English, German, French, Italian but not
            # Spanish and Portuguese, although fixing that wouldn't be too
            # hard
            return r'{\origdate\printdate{%s}}' % value.to_value()
        if isinstance(value, literal.Image):
            return metaimage(value, self.transclusions, **value.style)
        # FIXME(alexander): this should only happen for empty images
        # but there ought to be a better way
        elif value is None:
            return ''
        # FIXME, nasty fallthrough, takes care of Lang
        # and possibly others we might add later
        else:
            return str(value)


    #FIXME: quick hack for pictures in metadata fields
    def head_entity(self, name, value):
        return cmd('newcommand', (), ('\\' + name, self.value_to_latex(value)))

    def make_latex_head(self, head):
        head_cmds = [self.head_entity(latexify_metavarname(n), v)
                     for (n, v) in head.iteritems()
                     if n != 'lang']
        return '\n'.join(head_cmds + self.urldefs)

    def maybe_add_bibliography_section(self, latex_body, bib, bib_preamble):
        if not bib:
            return latex_body
        bib_cmds = []
        if bib_preamble:
            bib_cmds.append(nl(cmd('defbibnote', [],
                                   ['bibPreamble',
                                    self.latexify(bib_preamble)])))
            bib_opts = ['prenote=bibPreamble']
        else:
            bib_opts = []
        bib_cmds.append(cmd('printbibliography', bib_opts))
        return join(nl(nl(latex_body)), *bib_cmds)

    def bad_command(self, head, attrs, body):
        assert head in ('LIT', 'CMD')
        bad_cmd = attrs['class'][0]
        n = docproblem('Unknown command: {}', bad_cmd)

        warning = small(red(self.latexify(
            u"CONVERSION ERROR: Not a valid command"
            u" (only use underlining for commands): “")))
        the_cmd = self.latexify(
            mkel('u', {}, [bad_cmd + (':' if head == 'CMD' else '')]))
        warning_end = small(red(self.latexify(u'”')))
        return join(problem_anchor(n, join(warning, the_cmd, warning_end)),
                    self.latexify(body))

    def munge_cite(self, node, b):
        cite_type, = node[1]['class']
        paren = cite_type.endswith('p')
        latex_cmd = cite_type if not paren else cite_type[:-1]
        post = b[1:]
        # FIXME(alexander): ugly hack to work around biblatex stupidity -- it
        # apparently doesn't recognize utf-8 en-dashes as range indicators
        latex_post = post and [self.latexify(post).replace(EN_DASH, '--')]
        the_cite = cmd(latex_cmd, latex_post, b[:1])
        if not paren:
            return the_cite
        else:
            return cmd('parentext', [], [the_cite])

    def enumerate_(self, items, **kwargs):
        opts = ['%s=%s' % (k, self.latexify(kwargs[k]))
                for k in ['start', 'resume', 'series']
                if kwargs.get(k) is not None]
        return env('tystrol', items, opts, [])

    def handle_emphasis(self, emph, body):
        r"""Boldens italicizes or strikes-through latex text.

        Harder than it sounds: The problem being that \textbf and \textit
        don't work across paragraphs and \bfseries and \itshape don't do
        italic correction (i.e. the end of the emphasized text juts into what
        follows it, because the space is not widened as necessary).

        >>> writer = LatexWriter()
        >>> print writer.handle_emphasis('b', ['some bold text'])
        \textbf{some bold text}
        >>> print writer.handle_emphasis(
        ...     'b', [('p', {}, [('i', {},  ['some bold italic'])]), 'text'])
        {\bfseries{}\textit{some bold italic}
        <BLANKLINE>
        text\/}
        >>>

        With strikethrough and underline the problem is even worse. TeX itself
        has no underline/strikethrough at all and the default LaTeX \underline
        command is broken (e.g. makes the text un(line)breakable). All
        replacements like soul's \ul and ulem's \uline have weird limitations
        that cause random breakage, so we push these styles down into the body
        recursively.

        >>> print writer.handle_emphasis(
        ...  'u', [('p', {}, [('i', {},
        ...                     [('b', {}, ['ul bold italic'])])]), 'text'])
        {\itshape{}{\bfseries{}\uline{ul bold italic}\/}\/}
        <BLANKLINE>
        \uline{text}

        """
        # can safely use \textit/\textbf etc.
        INLINE_TEXT = Var('INLINE_TEXT', # pylint: disable=C0103
                          lambda x: isinstance(x, basestring) and '\n' not in x)
        if body == [INLINE_TEXT]:
            return cmd(self.INLINE_EMPH_TO_LATEX[emph], [],
                       [self.latexify(body)])
        else:
            if emph in ('b', 'i'):
                # need to use itshape/bfseries and do italic correction (r'\/')
                return texcmd(dict(b='bfseries', i='itshape')[emph],
                              join(self.latexify(body), r'\/'))
            else:
                assert emph in ('u', 's')
                # XXX: it might be better to have latexify as the outmost call
                # here rather than join indivudally converted parts. That would
                # allow for further rewrite logic in other parts of the latex
                # converter.
                return join(*(
                    self.handle_emphasis(emph, [e])
                    if isinstance(e, basestring)
                    else self.latexify(
                        mkel(*e[:2], body=[
                            mkel(emph, {}, [subbody_part])
                            for subbody_part in e[2]]))
                    for e in body))

    def am_inside(self, env):
        return env in self.context

    @contextmanager
    def inside(self, env):
        self.context.append(env)
        yield
        self.context.pop()

    def latexify(self, ast): # pylint: disable=E0102,R0914,R0915,R0911,R0912
        if isinstance(ast, list):
            return re.sub('\n\n$', '\n',
                          join(*map(self.latexify, ast)))
        else:
            node = ast
            if isinstance(node, basestring):
                return quote(node)
            else:
                assert isinstance(node, tuple)
                h, a, b = node
                if h == 'div':  # canonicalize pseudo-elements
                    h = a['class'].pop()
                    assert not a['class']
                    del a['class']

                if h[:-1] == 'h':
                    if self.am_inside('list') or self.am_inside('table'):
                        return docwarn(
                            self.latexify(b),
                            'Cannot have sections inside lists or tables: %r' %
                            postprocess.plaintextify(b))
                    else:
                        with self.inside('section'):
                            if a:
                                log.warn('heading w/ attr %r', a)
                            labels, b = extract_labels(b)
                            return self.section(h, b, labels)
                elif h == 'p':
                    ans = nl(self.latexify(b))
                    if self.am_inside('.footnote') and self.am_inside('table'):
                        return docwarn(ans,
                                       'Multi-paragraph footnotes in tables are'
                                       ' unsupported')
                    return nl(ans)
                elif h == 'span':
                    return self.latexify(b) # XXX
                elif h in ('ol', 'ul'):
                    ol = partial(self.enumerate_,
                                 start=a.get('start'),
                                 series=a.get('id'),
                                 resume=a.get('data-continue-list'))
                    with self.inside('list'):
                        return nl(
                            freshline({
                                'ol': ol,
                                'ul': itemize}[h](
                                    self.latexify(b))))
                elif h == 'li':
                    labels, b = extract_labels(b)
                    labelling = (join(*(map(mklabel, labels) + [' ']))
                                 if labels else '')
                    return join(freshline(cmd('item')),
                                labelling, self.latexify(b))
                elif h == 'table':
                    nested_table = self.am_inside('table')
                    with self.inside('table'):
                        # pylint: disable=C0103
                        CLASS_TO_SPEC = {'left': 'P', 'center': 'C',
                                         'right': 'R', 'justify': 'N'}
                        b = b[:]
                        tablecaption = None
                        if b[0][0] == 'caption':
                            with self.inside('caption'):
                                tablecaption = self.latexify(b[0][2])
                            del b[0]

                        colgroup = [el for el in b if el[0] == 'colgroup']
                        rows = [el for el in b if el[0] == 'tr']
                        assert len(colgroup) == 1, \
                                "Expected single colgroup in table %s" % b
                        cols = colgroup[0][2]
                        colspecs = []
                        for col_h, col_a, col_b in cols:
                            if col_h != 'col':
                                break
                            assert not col_b

                            coltype = 'P'
                            for cls in CLASS_TO_SPEC:
                                if cls in col_a.get('class', []):
                                    coltype = CLASS_TO_SPEC[cls]

                            coltype = "%s{%s}" % (coltype, textwidth_percent(
                                col_a['style']['width']))

                            colspecs.append(coltype)
                        rows = "\\tabularnewline\n".join(
                            map(self.latexify, rows))
                        if nested_table and tablecaption:
                            docproblem(
                                "Tables within tables can't have captions;"
                                " outputing caption as normal text",
                                level='warning')


                            ans = join(nl(table(colspecs, rows)), tablecaption)
                        else:
                            ans = table(colspecs, rows, tablecaption)
                    if self.post_float_yuck and not self.am_inside('table'):
                        ans = join(ans, *self.post_float_yuck)
                        del self.post_float_yuck[:]
                    return ans
                elif h == 'col': # FIXME
                    assert False, "Unexpected col"
                elif h == 'tr':
                    return " & ".join(map(self.latexify, b))
                elif h == 'td':
                    if 'headcol' in a.get('class', []):
                        return colh(self.latexify(b))
                    return self.latexify(b)
                elif h == 'th':
                    if 'headcol' in a.get('class', []):
                        return rowh(colh(self.latexify(b)))
                    return rowh(self.latexify(b))
                elif h == 'figure':
                    b = b[:]
                    if b[0][0] == 'figcaption':
                        with self.inside('caption'):
                            figcaption = self.latexify(b[0][2])
                        del b[0]
                    else:
                        figcaption = None
                    assert len(b) == 1 and b[0][0] == 'img'
                    img = b[0][1]['src']
                    inline = False
                    warns = []
                    if a['style']['display'] == 'inline':
                        if self.am_inside('table'):
                            warns.append([
                                'Margin figures not supported in tables, '
                                'inserting into table cell'])
                        else:
                            inline = True
                    if inline:
                        if figcaption:
                            warns.append(
                                ['Ignoring figcaption for inline figure:'
                                 ' "%s"', figcaption])
                        ans = marginfigure(img=img)
                    else:
                        fakecaption = figcaption and self.am_inside('table')
                        if fakecaption:
                            warns.append([
                                "Figures in tables can't have captions; "
                                "outputing caption as normal text"])
                        # inside blockquotes more complicated figure
                        # environments don't seem to work reliably
                        rawincludegraphics = self.am_inside('blockquote')
                        ans = figure(img=img,
                                     classes=a.get('class', []),
                                     width=a['style']['width'],
                                     figcaption=figcaption,
                                     fakecaption=fakecaption,
                                     rawincludegraphics=rawincludegraphics)
                    if self.post_float_yuck and not self.am_inside('table'):
                        ans = join(ans, *self.post_float_yuck)
                        del self.post_float_yuck[:]
                    return ans if not warns else docwarns(ans, *warns)
                elif h == 'img':
                    assert False, 'unexpected image'
                elif h == 'a':
                    if 'name' in a:
                        # we can't do that blindly, because we want to
                        # generate labels for things like lists and headings
                        # this is only a fallback for anchors outside of
                        # 'labelled' envs
                        return cmd('hypertarget', [],
                                   [a['name'].lstrip('#'), ''])
                    elif 'href' in a:
                        if a['href'].startswith('#'):
                            return cmd('hyperref',
                                       [latexify_href(a['href'][1:])],
                                       [self.latexify(b)])
                        ##
                        # XXX(alexander): handle bare urls specially, because
                        # we want more relaxed linebreaking rules for them.
                        # Note that we're not using \url directly, because
                        # it's not robust and also can't cope with certain
                        # arguments, such as unbalanced '{'/'}'s. Also, even
                        # with fairly aggressive hyphenization params, this is
                        # in in itself not enough to resolve all overfull hbox
                        # issues with urls, although it's not 100% clear to me
                        # why.
                        elif b and a['href'] in (b[0], url_fix(b[0])):
                            # XXX(alexander): use url_fixed version here?
                            return urldef(a['href'], self.urldefs)
                        else:
                            ans = cmd('href', [], [latexify_href(a['href']),
                                                   self.latexify(b)])
                            if b[0].startswith('http'):
                                ans = docwarn(
                                    ans,
                                    'Suspicious link with body/href'
                                    ' mismatch: %r != %r' % (
                                        a['href'].encode('utf-8'), b[0]))
                            return ans
                    else:
                        assert False, 'Malformed link: %s' % ((h, a, b),)
                elif h == 'aside':
                    return cmd('comment', [], [self.latexify(b)])
                elif h in ('b', 'i', 'u', 's'):
                    assert not a, 'unexpected <%s %r' % (h, a)
                    return self.handle_emphasis(h, b)
                elif h == 'code':
                    #FIXME: write something more specialized
                    return cmd('texttt', [], [self.latexify(b)])
                elif h == 'sup':
                    return cmd('textsuperscript', [], [self.latexify(b)])
                elif h == 'sub':
                    return cmd('textsubscript', [], [self.latexify(b)])
                elif h == '.footnote':
                    with self.inside('.footnote'):
                        if self.am_inside('caption'):
                            self.post_float_yuck.append(cmd('footnotetext',
                                                            [],
                                                            [self.latexify(b)]))
                            return cmd(r'protect\footnotemark', [], [])
                        else:
                            return cmd('footnote', [], [self.latexify(b)])
                elif h == '.pagebreak':
                    return nl(cmd('clearpage', [], [self.latexify(b)]))
                elif h == 'br':
                    assert a == {}
                    assert b == []
                    return nl(cmd('newline'))
                elif h == 'blockquote':
                    with self.inside('blockquote'):
                        return blockquote(self.latexify(b))
                elif (h == 'footer' and b == [Seq['cite', :]]
                      and self.am_inside('blockquote')):
                    return nl(cmd('attrib', [], [self.latexify(b[0][2])]))
                elif node == ('CMD', {'class': ['$']}, b):
                    return join('$', b[0], '$')
                elif node == ('CMD', {'class': [Var('CITE', CITE_REX.match)]},
                              b):
                    return self.munge_cite(node, b)
                elif node == ('CMD', {'class': ['tex']}, b):
                    return b[0]
                elif h in ('CMD', 'LIT'):
                    return self.bad_command(*node)
                elif h == 'pre':
                    return highlight.as_latex(node)
                elif h == 'wbr':
                    return '{}'
                else:
                    #FIXME(alexander): set 1 as error-code?
                    log.error('Unexpected tag: %s %r %r', h, a, b)
                    return join("")
                    ## assert False, 'unexpected tag: ' + h





def latexify_metavarname(name):
    assert not re.search('[^a-z-]', name), 'Bad meta-name: ' + name
    return "tystr" + name.split('-')[0] + (
        "".join(p.capitalize() for p in name.split('-')[1:]))

assert latexify_metavarname('multi-part-name') == 'tystrmultiPartName'
assert latexify_metavarname('name') == 'tystrname'



def write(out_file, style_template, bib, # pylint: disable=R0913,W0613
          meta, parsed_body, transclusions):
    head = meta.items()
    with open(style_template.latex_template) as f:
        tex_tmpl = f.read().decode('utf-8')
        writer = LatexWriter(
            transclusions=transclusions,
            section_corresponds_to=style_template.section_corresponds_to,
            )
        bib = head.pop('bibliography', None)
        latex_body = writer.maybe_add_bibliography_section(
            writer.latexify(parsed_body),
            bib=bib,
            bib_preamble=head.pop('bibliography-preamble', None))
        latex_head = writer.make_latex_head(head)
        latex_meta = writer.xmp_meta(head)
        print >> out_file, (
            tex_tmpl.
            replace('INTERPOLATEBABEL',
                    BABEL_HEADER % dict(lang=head['lang'].to_babel())).
            replace('INTERPOLATEHEAD', latex_head).
            replace('INTERPOLATEMETA', latex_meta).
            replace('INTERPOLATEBODY', latex_body).encode('utf-8'))
