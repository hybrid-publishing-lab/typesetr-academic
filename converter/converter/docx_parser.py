# -*- encoding: utf-8 -*-
import itertools

from functools import partial
import hashlib

from collections import OrderedDict
from cStringIO import StringIO
import logging as log

import regex as re

from converter.ezmatch import Seq, Var
from converter.utils import make_figure, parse_percentage
from converter.internal import (mkel, add_style, merge_attrs, is_code_font,
                                add_class)
from converter.transclusions import Transclusions
from converter.xml_namespaces import docx_ns as ns
# FIXME(alexander): really shouldn't be using tidy at this stage
from converter.postprocess import whack
from converter.xmltools import tup2etree
from converter import odt_parser

from converter import literal
from converter.unparse import unparse_literal
from converter import docxlite
from converter.docxlite import val


# http://startbigthinksmall.wordpress.com/2010/01/04/points-inches-and-emus-measuring-units-in-office-open-xml/
EMU_PER_CM = 360000.0


SOFT_HYPHEN = u'\u00ad'       # FIXME(alexander): make this a pseudo-tag
ZERO_WIDTH_SPACE = u'\u200b'  # same as <wbr>
NON_BREAKING_HYPHEN = u'\u2011'

# FIXME(aph): this is gruesome
(P_TAG, P_PROPS_TAG, HYPERLINK_TAG, RUN_TAG, RUN_PROPS_TAG, TEXT_TAG, TAB_TAG,
 TABLE_TAG, TABLE_ROW_TAG, TABLE_COLUMN_TAG, TABLE_COLUMN_PROPERTIES_TAG,
 SECTION_PROPERTIES_TAG,
 BREAK_TAG, CR_TAG,
 BOOKMARK_START_TAG, BOOKMARK_END_TAG,
 FOOTNOTE_REFERENCE_TAG, ENDNOTE_REFERENCE_TAG,
 FOOTNOTE_REF_TAG, ENDNOTE_REF_TAG,
 SOFT_HYPHEN_TAG, NON_BREAKING_HYPHEN_TAG) = map(ns.w, [
     'p', 'pPr', 'hyperlink', 'r', 'rPr', 't', 'tab',
     'tbl', 'tr', 'tc', 'tcPr',
     'sectPr',
     'br', 'cr',
     'bookmarkStart', 'bookmarkEnd',
     'footnoteReference', 'endnoteReference', 'footnoteRef', 'endnoteRef',
     'softHyphen', 'noBreakHyphen'])


def intdigest(x):
    "Produce a valid xsd:uint string from the hash of `x`"
    return str(int(hashlib.sha512(x).hexdigest()[:8], 16))

# This *really* is pretty close to a minimal docx image template, unfortunately.
# Most of these bits are even directly needed to just make the schema validate.
DRAWING_TEMPLATE = lambda rid, w, h, inline: (
    'w:drawing', {},
    [('wp:inline' if inline else 'wp:anchor', {},
      [('wp:extent', {'cx': w, 'cy': h}, []),
       ('wp:docPr',
        {'id': intdigest('docPr' + rid), 'name': rid, 'descr': rid}, []),
       ('a:graphic', {},
        [('a:graphicData',
          {'uri': 'http://schemas.openxmlformats.org/drawingml/2006/picture'},
          [('pic:pic', {},
            [('pic:nvPicPr', {},
              [('pic:cNvPr',
                {'id': intdigest('nvPicPr' + rid), 'name': rid}, []),
               ('pic:cNvPicPr', {'preferRelativeResize': '0'}, [])]),
             ('pic:blipFill', {},
              [('a:blip', {'r:embed': rid}, []),
               ('a:srcRect', {'b': '0', 'l': '0', 'r': '0', 't': '0'}, []),
               ('a:stretch', {}, [('a:fillRect', {}, [])])]),
             ('pic:spPr', {}, [
                 ('a:xfrm', {},
                  [('a:ext', {'cy': w, 'cx': h}, [])]),
                 ('a:prstGeom', {'prst': 'rect'}, []),
                 ('a:ln', {}, [])])])])])])])


def style_to_tag(stylename):
    # FIXME(alexander): should use outlineLvl instead of this
    # ugly hack
    if stylename.startswith('Heading'):
        # FIXME validate
        return 'h' + stylename[-1]
    if stylename in ('Title', 'Subtitle'):
        return stylename.lower()
    if stylename:
        log.debug('Unknown paragraph style: %r', stylename)
    return 'p'


def flatmap(f, xs):
    return [y for x in xs for y in f(x)]


def add_bg(a, rgb):
    # HACK: according to spec, the hex should be all uppercase,
    # but google docs gets this wrong, hence the `.upper()`
    rgb = rgb.upper()
    assert re.match('^#[0-9A-F]{6}$', rgb)
    if rgb == '#FFFFFF':  # HACK for google docs
        return a
    return add_style(a, 'background-color', rgb)


class ListBuilder(object):
    WORD_OL_TO_CSS = {
        'decimal': 'decimal',
        'lowerLetter': 'lower-alpha',
        'lowerRoman': 'lower-roman',
        'upperLetter': 'upper-alpha',
        'upperRoman': 'upper-roman',
        'hebrew1': 'hebrew',
        'iroha': 'katakana-iroha',
        'aiueo': 'hiragana-aiueo',
        'ideographDigital': 'cjk-ideographic'
    }
    WORD_UL_TO_CSS = {
        u'●': 'disc',
        u'○': 'circle',
        u'■': 'square',
        u'-': 'hyphen',
    }

    def __init__(self, doc):
        self.doc = doc
        self.reset()

    def reset(self):
        # pylint: disable=W0201
        self.lists = []
        self.append_points = [self.lists]
        self.in_list = False

    def list_type(self, numid, level):
        # XXX(ash): where did we get this list from?
        ol_defaults = ['decimal', 'lowerLetter', 'lowerRoman']
        ul_defaults = u'●○■'
        num_style = self.doc.get_num_style(numid, level)
        fmt = num_style.numFmt
        attrs = {}
        if fmt == 'bullet':
            fmt = num_style.lvlText
            if (fmt != ul_defaults[level % len(ul_defaults)] and
                    fmt in self.WORD_UL_TO_CSS):
                attrs['class'] = [self.WORD_UL_TO_CSS[fmt]]
            return 'ul', attrs
        else:
            if (fmt != ol_defaults[level % len(ol_defaults)] and
                    fmt in self.WORD_OL_TO_CSS):
                attrs['class'] = [self.WORD_OL_TO_CSS[fmt]]
            return 'ol', attrs

    @classmethod
    def build_list(cls, tree):
        _ = Var('_')
        if isinstance(tree, list):
            ans = []
            for (tag, attr), body in itertools.groupby(
                    tree,
                    lambda x: (_, _) if isinstance(x, list) else x[0]):
                this_body = []
                if tag is _:
                    body, = body
                    ans.append(mkel('.block', {}, cls.build_list(body)))
                else:
                    for x in body:
                        if isinstance(x, list):
                            item = cls.build_list(x)
                            this_body[-1][2].extend(item)
                        else:
                            item = [x[1]]
                            this_body.append(mkel('li', {}, item))
                    ans.append(mkel(tag, attr, this_body))
        return ans

    @property
    def level(self):
        return len(self.append_points) - 1

    def flush(self):
        if self.in_list:
            try:
                return self.build_list(self.lists)
            finally:
                self.reset()
        return []

    def process(self, e, handle_p):
        numPr = e.find(P_PROPS_TAG + '/' + ns.w('numPr'))
        numid = val(numPr, ns.w('numId'))
        if not numid:
            return self.flush() + [handle_p(e, in_list=False)]

        self.in_list = True  # pylint: disable=W0201
        level = int(val(numPr, ns.w('ilvl')) or 0)
        while level != self.level:
            if level > self.level:
                self.append_points[-1].append([])
                self.append_points.append(self.append_points[-1][-1])
            else:
                self.append_points.pop()
        self.append_points[self.level].append(
            (self.list_type(numid, level),
             handle_p(e, in_list=True)))
        return []


def apply_html_style(tag, run):
    '''
    >>> run1 = mkel('w:r', {}, ['...'])

    >>> run2 = apply_html_style('b', run1)

    >>> run2 # doctest: +NORMALIZE_WHITESPACE
    ('w:r', {}, [('w:rPr', {}, [('w:b', {'w:val': '1'}, [])]),
                 '...'])

    >>> apply_html_style('i', run2) # doctest: +NORMALIZE_WHITESPACE
    ('w:r', {}, [('w:rPr', {}, [('w:b', {'w:val': '1'}, []),
                                ('w:i', {'w:val': '1'}, [])]),
                 '...'])
    '''
    rpr = {
        'u': mkel('w:u', {'w:val': 'single'}, []),
        'b': mkel('w:b', {'w:val': '1'}, []),
        's': mkel('w:strike', {'w:val': '1'}, []),
        'i': mkel('w:i', {'w:val': '1'}, []),
    }[tag]
    t, a, b = run
    if b[0][:1] == ('w:rPr',):
        assert b[0][1] == {}
        rprs = b[0][2] + [rpr]
        b = b[1:]
    else:
        rprs = [rpr]
    b = [mkel('w:rPr', {}, rprs)] + b
    return mkel(t, a, b)


def lift_code(para):
    def is_code(element):
        return element[:1] == ('code',)
    # pylint: disable=C0103
    ALL_CODE = Var('ALL_CODE', lambda xs: all(is_code(x) for x in xs))
    if para == ('p', {}, ALL_CODE):
        # XXX(ash): maybe should do this coalescing of adjacent `code`
        # bodies in postprocess?
        new_body = []
        for e in ALL_CODE.val:
            _, attrs, body = e
            if attrs:
                log.warn('ignoring attrs on code tag %r', e)
            new_body.extend(body)
        return mkel('code', {}, new_body)
    else:
        return para


def hacky_flatten_block(block):
    # XXX(ash): move to postprocess
    # pylint: disable=C0103
    BLOCK_ATTRS = Var('BLOCK_ATTRS')
    P_ATTRS = Var('P_ATTRS')
    BODY = Var('BODY')
    if block == ('.block', BLOCK_ATTRS, [('p', P_ATTRS, BODY)]):
        return mkel('.block',
                    merge_attrs(BLOCK_ATTRS.val, P_ATTRS.val),
                    BODY.val)
    else:
        return block


def first_of_tag(element, tag):
    for e in element.iterchildren(tag):
        return e

def make_p(*body):
    return mkel('w:p', {}, list(body))

def make_pic(rid, w, h, inline):
    return DRAWING_TEMPLATE(rid, str(w.emu.real), str(h.emu.real), inline)

def mk_t(s):
    return ('w:t', {'xml:space': 'preserve'}, [s])

def meta_to_runs(what, intern_image, total_w):
    # pylint: disable=R0911
    recurse = partial(meta_to_runs, intern_image=intern_image, total_w=total_w)
    if isinstance(what, basestring):
        return [mkel('w:r', {}, [mk_t(what)])]
    elif isinstance(what, list):
        return flatmap(recurse, what)
    elif isinstance(what, tuple):
        t, _, b = what
        runs = recurse(b)
        if t in ('b', 'i', 's', 'u'):
            return [apply_html_style(t, run) for run in runs]
        else:
            log.warn("Didn't understand html tag %r", what)
            return runs
    elif isinstance(what, literal.Image):
        rid = intern_image(what)
        target_w = parse_percentage(what.style['width']) * total_w
        w, h = what.get_size()
        w, h = [docxlite.Emu(x * target_w / h) for x in (w, h)]
        inline = (what.style['display'] == 'inline')
        return [mkel('w:r', {}, [make_pic(rid, w, h, inline)])]
    elif isinstance(what, literal.Bibliography):
        return recurse(what.data)
    else:
        log.warn('Fallthrough: %r', what)
        return recurse(unparse_literal(what))

class Docx(object):
    # get "normal" inline images (i.e. ignnores VML and similar crap)
    IMAGE_XPATH = (
        './*[self::wp:inline|self::wp:anchor]'
        '[.//a:graphicData'
        '[@uri="http://schemas.openxmlformats.org/drawingml/2006/picture"]]')
    JC_TO_CLASS = {
        'left': 'left',
        'right': 'right',
        'center': 'center',
        'both': 'justify',
    }
    STYLE_TO_HTML = OrderedDict((ns.w(x), x[0]) for x in
                                ['u', 'b', 'bCs', 'i', 'iCs', 'strike'])

    HIGHLIGHT_TO_RGB = {
        'black': '000000',
        'blue': '0000ff',
        'cyan': '00ffff',
        'darkBlue': '000080',
        'darkCyan': '008080',
        'darkGray': '808080',
        'darkGreen': '008000',
        'darkMagenta': '800080',
        'darkRed': '800000',
        'darkYellow': '808000',
        'green': '00ff00',
        'lightGray': 'c0c0c0',
        'magenta': 'ff00ff',
        'red': 'ff0000',
        'white': 'ffffff',
        'yellow': 'ffff00',
        'none': None,
    }

    def __init__(self, infilename, make_transclusions):
        self.doc = doc = docxlite.Document(infilename)
        # pylint: disable=W0212
        self.numbering = doc.numbering
        self.body = doc.document.e.find(ns.w('body'))
        self.rels = doc.document.rels
        sprops = docxlite.parse_sectPr(self.body[-1])
        self.textwidth_emu = (sprops.page_width.emu.real
                              - sprops.right_margin.emu.real
                              - sprops.left_margin.emu.real)
        if make_transclusions:
            self.transclusions = make_transclusions(self.doc.get_images())
        else:
            self.transclusions = None
        self.default_indent_twips = 720

    def parse(self):
        return (self.parse_body(self.body, current_part='document'),
                self.transclusions)

    def handle_omath(self, e):  # pylint: disable=W0613
        return []

    def handle_p_content(self, e, current_part):
        if e.tag == RUN_TAG:
            return self.handle_run(e)
        elif e.tag == HYPERLINK_TAG:
            internalId = e.attrib.get(ns.r('id'))
            if internalId is None:
                ref = '#' + e.attrib[ns.w('anchor')]
            else:
                rels = self.doc.get_rels_for(current_part)
                ref = rels[internalId].attrib['Target']
            # 'u', 'span' = nuke bogus color and underline
            # styling that google docs likes to add to links;
            # XXX(alexander): rewrite colour less bluntly;
            # this also nukes background color
            handle_p = partial(self.handle_p_content, current_part=current_part)
            body = whack(('u', 'span').__contains__, flatmap(handle_p, e))
            if not body:
                log.warn('hyperlink with no body to: %r', ref)
            return [mkel('a', {'href': ref}, body)]
        elif e.tag == BOOKMARK_END_TAG:
            return []
        elif e.tag == BOOKMARK_START_TAG:
            return [mkel('a', {'name':  e.attrib[ns.w('name')]}, [])]
        elif e.tag == ns.m('oMath'):
            return self.handle_omath(e)
        else:
            log.warn('Ignoring unknown tag %s', e.tag)
            return []

    def transclude(self, pic):
        # for id:
        # pylint: disable=W0622

        if self.transclusions is None:
            return []

        width_emu = float(val(pic, ns.wp('extent'), 'cx'))
        embeds = pic.xpath('.//a:blip/@r:embed', namespaces=ns.dict)
        try:
            id, = embeds
        except ValueError:
            log.warn('Expected exactly one r:embed with an image id, got %r',
                     embeds)
            return []

        href = self.transclusions.normalize_known_transclusion(id)
        return [make_figure(relwidth=width_emu/self.textwidth_emu,
                            inline={'anchor': False,
                                    'inline': True}[pic.tag.split('}')[1]],
                            body=[mkel('img', {'src': href}, [])],
                            src=href, original_href=id)]

    def make_footnote(self, e):
        # pylint: disable=W0622
        id = e.attrib[ns.w('id')]
        ps = (self.doc.get_footnote if e.tag == FOOTNOTE_REFERENCE_TAG
              else self.doc.get_endnote)(id).iterfind(P_TAG)
        footnote_part = 'footnotes'  # XXX what about endnotes
        return mkel('.footnote', {},
                    [self.handle_p(p, current_part=footnote_part) for p in ps])

    def handle_run(self, r):
        # XXX(ash): pylint is right about this being too complex
        # pylint: disable=R0912
        _ = Var('_')
        ans = []
        rPr = first_of_tag(r, RUN_PROPS_TAG)
        content = rPr.itersiblings() if rPr is not None else iter(r)
        for e in content:
            # pylint: disable=W0622
            type = e.attrib.get(ns.w('type'))
            if e.tag == TEXT_TAG:
                ans.append(e.text)
            elif e.tag == TAB_TAG:
                # XXX(alexander): this can also work like a '_' or '…' \dotfill
                ans.append('\t')
            elif e.tag in (FOOTNOTE_REF_TAG, ENDNOTE_REF_TAG):
                # XXX(ash): what is going on here
                pass
            elif e.tag == BREAK_TAG and type in ('page', 'column'):
                ans.append(mkel('.pagebreak', {}, []))
            elif e.tag == BREAK_TAG or e.tag == CR_TAG:
                assert (type is None) or (type == 'textWrapping')
                ans.append(mkel('br', {}, []))
            # FIXME, tags below untested
            elif e.tag == SOFT_HYPHEN_TAG:
                ans.append(SOFT_HYPHEN)
            elif e.tag == NON_BREAKING_HYPHEN_TAG:
                ans.append(NON_BREAKING_HYPHEN)
            elif e.tag == ns.w('drawing'):
                ans.extend(
                    flatmap(self.transclude, e.xpath(self.IMAGE_XPATH,
                                                     namespaces=ns.dict)))
            elif e.tag in (FOOTNOTE_REFERENCE_TAG, ENDNOTE_REFERENCE_TAG):
                ans.append(self.make_footnote(e))
            else:
                # movie,
                # rt, ruby, rubyAlign etc. for ruby stuff
                # sym, with special handling for wingdings I guess...
                log.warn('Unknown tag %r', e.tag)
        if rPr is not None and ans != Seq[Seq['.footnote', _:], _:]:
            ans = self.apply_rpr(rPr, ans)

        return ans

    def apply_rpr(self, rPr, ans):
        stys = {x.tag for x in rPr.iterchildren(*self.STYLE_TO_HTML)}
        if stys:
            for (t, html) in self.STYLE_TO_HTML.iteritems():
                if t in stys:
                    ans = [mkel(html, {}, ans)]
        color = val(rPr, ns.w('color'))
        if color:
            a = add_style({}, 'color', '#' + color)
            ans = [mkel('span', a, ans)]  # FIXME word colors

        # `None` here == turn highlighting off; it's different from no value
        highlight = self.HIGHLIGHT_TO_RGB.get(val(rPr, ns.w('highlight')),
                                              False)
        if highlight is False: # higher precedence than shade
            highlight = val(rPr, ns.w('shd'), ns.w('fill'))
        if highlight:
            ans = [mkel('span', add_bg({}, '#' + highlight), ans)]
        vertalign = val(rPr, ns.w('vertAlign'))
        if vertalign and vertalign != 'baseline':
            ans = [mkel(vertalign[:3], {}, ans)]
        if is_code_font(val(rPr, ns.w('rFonts'), ns.w('ascii'))):
            ans = [mkel('code', {}, ans)]
        return ans

    def handle_p(self, e, current_part, in_list=False):
        attrs = {}
        pPr = first_of_tag(e, P_PROPS_TAG)
        jc_class = self.JC_TO_CLASS.get(val(pPr, ns.w('jc')))
        if jc_class:
            attrs = add_class(attrs, jc_class)
        tag = style_to_tag(val(pPr, ns.w('pStyle')) or '')
        content = iter(e) if pPr is None else pPr.itersiblings()
        handle_p = partial(self.handle_p_content, current_part=current_part)
        ans = mkel(tag, attrs, flatmap(handle_p, content))
        left_indent = val(pPr, ns.w('ind'), ns.w('left')) or 0.0
        indent = int(round(float(left_indent) / self.default_indent_twips))
        if (not in_list) and indent:
            ans = lift_code(ans)
            ans = mkel('.block', {'indent': indent}, [ans])
            ans = hacky_flatten_block(ans)
        return ans

    def parse_body(self, xml, current_part):
        builder = ListBuilder(self.doc)
        body = []

        for e in xml:
            if e.tag == P_TAG:
                handle_p = partial(self.handle_p, current_part=current_part)
                body.extend(builder.process(e, handle_p))
            else:
                body.extend(builder.flush())
                if e.tag == TABLE_TAG:
                    body.append(self.parse_table(e, current_part))
                elif e.tag == SECTION_PROPERTIES_TAG:
                    pass
                else:
                    log.warn('Unrecognized element: %s', e.tag)

        body.extend(builder.flush())
        return body

    def parse_table(self, e, current_part):
        # XXX(ash): simplify
        # pylint: disable=R0914
        def cell_bg(tc):
            if tc[0].tag == TABLE_COLUMN_PROPERTIES_TAG:
                bg = val(tc[0], ns.w('shd'), ns.w('fill'))
                if bg:
                    return add_bg({}, '#' + bg)
            return {}

        def skip_past(e, child):
            if e[0].tag == child:
                return e[0].itersiblings()
            return e.iterchildren()

        def parse_rows(e, has_header_row, has_header_col):
            def is_header(i, j):
                return i == 0 and has_header_row or j == 0 and has_header_col

            return [
                mkel('tr', {},
                     [mkel('th' if is_header(i, j) else 'td', cell_bg(tc),
                           self.parse_body(
                               skip_past(tc, TABLE_COLUMN_PROPERTIES_TAG),
                               current_part=current_part))
                      for (j, tc) in enumerate(tr.iterfind(TABLE_COLUMN_TAG))])
                for (i, tr) in enumerate(e.iterfind(TABLE_ROW_TAG))]

        tblPr = first_of_tag(e, ns.w('tblPr'))
        tbl_stuff = tblPr.itersiblings()
        tblGrid = next(tbl_stuff)
        # according to the schema this is always true
        assert tblGrid.tag == ns.w('tblGrid'), tblGrid.tag
        look = tblPr.find(ns.w('tblLook'))
        if look is None:
            has_header_row = has_header_col = False
        else:
            # this is actually the canonical check;
            # the identical per cell/row props are just for caching
            has_header_row, has_header_col = (
                look.attrib.get(k) == "1"
                for k in (ns.w('firstRow'), ns.w('firstColumn')))

        grid_cols = tblGrid.iterchildren(ns.w('gridCol'))
        col_widths = [int(gc.attrib[ns.w('w')]) for gc in grid_cols]
        col_total = sum(col_widths)
        col_pcts = [100. * w / col_total for w in col_widths]
        cols = [mkel('col',
                     add_style({}, 'width', '%s%%' % w),
                     []) for w in col_pcts]
        rows = parse_rows(e, has_header_row, has_header_col)
        table = odt_parser.parse_table_body(cols + rows)
        return mkel('table', {}, table)

    def strip_meta(self, unaugmented_meta, transclusions, asides):
        # XXX(ash): :(
        from converter.postprocess import postprocess
        for i in range(len(self.body)):
            raw_body_i = self.parse_body(self.body[:i], current_part='document')
            unaugmented_meta_i = postprocess(raw_body_i, transclusions,
                                             asides=asides)[0]
            if unaugmented_meta_i == unaugmented_meta:
                self.body[:i] = []
                return
        raise Exception('failed to find the end of the metadata')

    @staticmethod
    def meta_to_docx(meta, intern_image, total_w):
        tups = []

        meta_copy = meta.raw_items().copy()

        to_runs = partial(meta_to_runs, intern_image=intern_image,
                          total_w=total_w)

        for name in ['Title', 'Subtitle']:
            bit = meta_copy.pop(name.lower(), None)
            if bit:
                pr = mkel('w:pPr', {}, [
                    # FIXME(ash): currently we don't ensure the styles exist
                    mkel('w:pStyle', {'w:val': name}, [])
                ])
                tups.append(make_p(pr, *to_runs(bit)))

        for k, v in meta_copy.iteritems():
            body = (to_runs([mkel('u', {}, [str(k) + ':']), ' '])
                    + to_runs(v))
            tups.append(make_p(*body))

        return [tup2etree(tup, nsmap=ns.dict) for tup in tups]

    def intern_image(self, image):
        assert isinstance(image, literal.Image)
        f = StringIO(image.data)
        rid = self.doc.add_image(f, image.mimetype)
        return rid

    def insert_meta(self, meta):
        self.body[:0] = self.meta_to_docx(meta, self.intern_image,
                                          self.textwidth_emu)

    def save_to(self, f):
        self.doc.save(f)


def parse_to_raw_body(infilename, rewritten_input=None,
                      make_transclusions=None):
    doc = Docx(infilename, make_transclusions)
    raw_body, transclusions = doc.parse()
    rewrite_info = (rewritten_input, doc)
    return (raw_body, transclusions, rewrite_info)


def rewrite_input(meta, unaugmented_meta, transclusions, asides, rewrite_info):
    rewritten_input, doc = rewrite_info
    doc.strip_meta(unaugmented_meta, transclusions, asides)
    doc.insert_meta(meta)
    doc.save_to(rewritten_input)

if __name__ == '__main__':
    # pylint: disable=C0103
    body, tcl, (rewritten, doc) = parse_to_raw_body(
        'converter/test/data/comprehensive-test-from-odt.docx',
        make_transclusions=Transclusions
    )
    doc.doc.add_image('foo', 'image/asdf')
