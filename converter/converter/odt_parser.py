#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
r"""This module is responsible for the first pass of gdocs generated odt to an
internal representation.

Internal Representation Pseudo-BNF::

    ('[...]' denotes a python list)

    body       ::= [(element|basestring)*]
    element    ::= (head, attrs, body)
    head       ::= basestring
    attrs      ::= attr-dict

    attr-dict  ::= dict([(class-attr | style-attr | misc-attr)*])
    class-attr ::= ('class', [basestring*])
    style-attr ::= ('style', OrderedDict([(basestring, basestring)]*))
    misc-attr  ::= (basestring, basestring)

The second pass (interleaved with the first one, as it turns out) is handled
by the `postprocess` module which has functions for cleaning up the generated
internal representation to deal with the mess that google docs generates.
"""


from decimal import Decimal
from collections import OrderedDict
from cStringIO import StringIO
import logging as log
import os
import regex as re
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from converter.ezmatch import Seq, Var
from converter.utils import format_percentage, make_figure
from converter.internal import (mkel, add_class, iadd_style, merge_attrs,
                                is_code_font)
from converter.xml_namespaces import odt_ns as ns
# FIXME(alexander): really shouldn't be using tidy at this stage
from converter.postprocess import blank, tidy, whack, plaintextify, postprocess
from converter.xmltools import etree2s, to_etree
from converter import odt_writer
from converter import preprocess


# Put some upper bound on how many xml elements the meta-data section can have
# to avoid a polynomial blow-up of runtime costs if for some reason no end
# of the metadata section can be found
MAX_META_ELEMENTS = 1000

#pylint: disable=C0103



FRAME_TAG, IMAGE_TAG = map(ns.draw, ['frame', 'image'])
ANNOTATION_TAG, = map(ns.office, ['annotation'])
(A_TAG, BOOKMARK_START_TAG, BOOKMARK_END_TAG, H_TAG, LIST_TAG,
 LIST_ITEM_TAG, NOTE_TAG, NOTE_BODY_TAG, NOTE_CITATION_TAG,
 P_TAG, S_TAG, SPAN_TAG, TAB_TAG) = map(ns.text, [
     'a', 'bookmark-start', 'bookmark-end', 'h', 'list', 'list-item',
     'note', 'note-body', 'note-citation', 'p', 's', 'span', 'tab'])
CREATOR_TAG = ns.dc('creator')
STYLE_NAME_ATTR = ns.text('style-name')
TABLE_STYLE_NAME_ATTR = ns.table('style-name')
HREF_ATTR = ns.xlink('href')
TEXT_NAME_ATTR = ns.text('name')
TABLE_TAG, TABLE_COLUMN_TAG, TABLE_ROW_TAG, TABLE_CELL_TAG = map(
    ns.table, ['table', 'table-column', 'table-row', 'table-cell'])
LINEBREAK_TAG = ns.text('line-break')

def in_cm(s):
    assert s.endswith('cm')
    return Decimal(s[:-2])

# half an inch
DEFAULT_INDENT_IN_CM = 2.54/2

def in_indents(s):
    assert s.endswith('cm')
    # `max(0, ...)`: full width figures e.g. are negatively indented
    return max(0, int(round(float(s[:-2])/DEFAULT_INDENT_IN_CM)))

def _make_rewrite_odt(z, to_parse):
    buf = StringIO()
    new_odt = ZipFile(buf, mode='w')
    for f in z.filelist:
        ext = os.path.splitext(f.filename)[1].lower()
        compression = (ZIP_STORED if ext in ('png', 'jpg', 'jpeg')
                       # must be first and uncompressed according to spec
                       or f.filename == 'mimetype'
                       else ZIP_DEFLATED)
        if f.filename not in to_parse:
            new_odt.writestr(f.filename, z.open(f.filename).read(),
                             compress_type=compression)

    def rewrite_odt(styles, content, transclusions):
        assert styles.getparent() is content.getparent() is None
        for f, s in zip(to_parse, [styles, content]):
            new_odt.writestr(f, etree2s(s, False), compress_type=ZIP_DEFLATED)
        old = set(new_odt.namelist())
        for href, s in transclusions.iteritems():
            fname = transclusions.new_href_to_original[href]
            if fname in old:
                continue
            new_odt.writestr(fname, s)
        new_odt.close()
        buf.seek(0)
        return buf.read()

    return rewrite_odt


def preparse(path, make_transclusions=None, rewrite=False):
    """Returns xml for styles, content, transclusions and `rewrite_odt`.

    - `rewrite_odt` is a function that take `styles` and `content` xml chunks
       and produces new odt file that has all the contents of the original
       odt, but with replaced styles and content xml.

    """
    to_parse = ['styles.xml', 'content.xml']
    z = ZipFile(path)
    if make_transclusions:
        pics = [f for f in z.namelist() if f.startswith('Pictures/')]
        includes = dict(zip(pics, map(z.open, pics)))
    files = map(z.open, to_parse)
    styles, content = [next(to_etree(f, False).iter()) for f in files]
    return (styles, content,
            make_transclusions and make_transclusions(includes),
            None if not rewrite else _make_rewrite_odt(z, to_parse))

def parse_to_raw_body(infilename, rewritten_input, make_transclusions):
    styles, content, transclusions, rewrite_input = preparse(
        infilename, make_transclusions=make_transclusions,
        rewrite=bool(rewritten_input))
    stys = read_in_styles(styles, content, transclusions)
    raw_body, transclusions, text = parse_styles_and_body(
        stys, content, transclusions)
    rewrite_info = (rewrite_input, rewritten_input, text, stys, content, styles)
    return raw_body, transclusions, rewrite_info

def rewrite_input(meta, unaugmented_meta, transclusions, asides,
                  rewrite_info):
    # pylint: disable=R0914
    rewrite, rewritten_input, text, stys, content, styles = rewrite_info
    # FIXME(alexander): augment the transclusions object with the textwidth so
    # that width in % can be rewritten into width in cm (odt allows no
    # relative measurements in svg:width; although it would be possible to use
    # style:width, this has to occur in a different context). Note that in
    # addition to being a terrible hack, the whole concept of relative widths
    # in typesetr is probably somewhat broken: IIRC they are all computed
    # relative to absolute textwidth whereas we should really be using the
    # textwidth of the containing element
    transclusions.textwidth_cm = stys.textwidth

    meta_items = meta.raw_items()
    # find the end of the meta-data section by iteratively expanding the
    # truncated document until parsing it gives the same metadata as
    # parsing the complete document
    for i in xrange(MAX_META_ELEMENTS):
        raw_body_i = parse_styles_and_body(
            stys, content, transclusions, upto=i)[0]
        unaugmented_meta_i = postprocess(raw_body_i, transclusions,
                                         asides=asides)[0]
        if unaugmented_meta_i == unaugmented_meta:
            new_text, required_styles, extra_transclusions = (
                odt_writer.meta_to_odt_xml(meta_items, transclusions))
            odt_writer.ensure_minimal_styles(styles, required_styles)
            text[:i] = new_text
            break
    else:
        assert False, "meta in odt did not end after MAX_META_ELEMENTS"
    if rewritten_input:
        rewritten_input.write(rewrite(styles, content, extra_transclusions))
        rewritten_input.flush()
        log.info('INPUT FILE REWRITTEN')


class ParseContext(object):
    def __init__(self, stys, list_level=0, list_style=None):
        self.stys = stys
        self.list_level = list_level
        self.list_style = list_style

    def __repr__(self):
        return 'ParseContext(%r, %r, %r)' % (
            self.stys, self.list_level, self.list_style)

    def bump_list_level(self, style):
        return type(self)(self.stys,
                          list_level=self.list_level+1,
                          list_style=style or self.list_style)
    @property
    def list_type(self):
        return self.list_style.sub_list_styles[self.list_level]['list_type']
    @property
    def list_start(self):
        return self.list_style.sub_list_styles[self.list_level]['start']
    @property
    def list_style_type(self):
        return self.list_style.sub_list_styles[self.list_level][
            'list_style_type']

def parse_table_body(body): #pylint: disable=R0914
    def extract_header(elems):
        attrs = []
        for elem in elems:
            _TAG, TATTRS, PATTRS, _SATTRS, _BATTRS, TBODY = map(
                Var,
                "_TAG, TATTRS, PATTRS, _SATTRS, _BATTRS, TBODY".split(', '))
            _BLANK_BODY = Var('_BLANK', blank)
            if elem == (_TAG, TATTRS, _BLANK_BODY):
                # empty cell - accept, but do not propagate attrs, apart
                # from background-color
                bg = TATTRS.val.get('style', {}).get('background-color')
                attrs.append({})
                if bg:
                    iadd_style(attrs[-1], 'background-color', bg)
            elif elem in ((_TAG, TATTRS, [('p', PATTRS,
                                           [('span', _SATTRS,
                                             [('b', _BATTRS, TBODY)])])]),
                          (_TAG, TATTRS, [('p', PATTRS,
                                           [('b', _BATTRS, TBODY)])])):
                attrs.append(merge_attrs(TATTRS.val, PATTRS.val))
            else:
                #not header set
                return False, []

        return True, attrs

    cols = [el for el in body if el[0] == 'col']
    trs = [el for el in body if el[0] == 'tr']

    has_header_row, header_attrs = extract_header(trs[0][2]) #rows[0].body
    if has_header_row:
        header_row = []
        ncols = []
        for index, td in enumerate(trs[0][2]):
            ctag, cattrs, cbody = cols[index]
            header_row.append(mkel('th', header_attrs[index], td[2]))
            if 'class' in header_attrs[index]:
                cattrs = add_class(cattrs, *header_attrs[index]['class'])
            ncols.append(mkel(ctag, cattrs, cbody))
        trs = [mkel('tr', {}, header_row)] + trs[1:]
        cols = ncols

    has_header_column, _col_attrs = extract_header(
        [body[0] for (_, _, body) in trs])
    if has_header_column:
        ntrs = []
        for (trtag, trattrs, trbody) in trs:
            tdtag, tdattrs, tdbody = trbody[0]
            ntd = mkel(tdtag, add_class(tdattrs, 'headcol'), tdbody)
            ntrs.append(mkel(trtag, trattrs, [ntd] + trbody[1:]))
        trs = ntrs
    return [mkel('colgroup', {}, cols)] + trs


def style_id(style):
    """Gets the unique id of a style, which according to
    OpenDocumentv-1.1.pdf, p.480 would seem to be (style:family, style:name):

      The style:name attribute identifies the name of the style. This
      attribute, combined with the style:family attribute, uniquely identifies
      a style. The <office:styles>, <office:automatic-styles> and
      <office:master-styles> elements each must not contain two styles with
      the same family and the same name.

    Of course Google doc seems to have a different interpreation because it
    refers to ('text', 'Standard') when only ('paragraph', 'Standard') exists.

      The parent style cannot be an automatic style and has to exist.

    Well, tough.
    """

    if style.tag in (ns.text('list-style'), ):
        family = None
    else:
        family = style.attrib[ns.style('family')]
    return (family,
            #FIXME verify name defaults to display-name
            style.get(ns.style('name')) or style.get(ns.style('display-name')))

def parent_id(style):
    parent_style = style.get(ns.style('parent-style-name'))
    return parent_style and (style.attrib.get(ns.style('family')), parent_style)

class DocStys(dict):
    """A stylesheet dictionary, containing the parsed styles for a document."""
    def __init__(self, stys=None, textwidth=None, header=None, footer=None):
        # pylint: disable=C0326
        self.header    = header
        self.footer    = footer
        self.textwidth = textwidth
        dict.__init__(self, stys or {})
    def add_odt_style(self, odt_style):
        Sty.from_odt_style(self, odt_style)
    def __repr__(self):
        class_str = type(self).__name__
        prefix = " " * (len(class_str) + 2)
        return '%s({%s},\n%stextwidth=%r, header=%r, footer=%r)' % (
            class_str, ("\n" + prefix).join("%-20r: %r" % (k, sty)
                                            for (k, sty) in self.iteritems()),
            prefix, self.textwidth, self.header, self.footer)

def default_to(value):
    return lambda x: x if x != value else None

class Sty(object):
    name = parent = inherited = type = None # make pylint happy
    # dict of name -> (check, transform)
    #
    # FIXME: the transforms shouldn't do the canoniclaization of default
    # values like text-style: normal => None; because of inheritance that has
    # to happen post-inheritance, so that a parent's style value can be
    # overriden w/ a default-value
    props = dict(
        #level=(int, int),
        type=((
            'title', 'subtitle',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'list', #can't use 'ol', 'ul', because we'll find out later
            'p', 'span', 'table', 'tr', 'td', 'col',
            'footnote', ), None),
        # TEXT
        font_family=(None, default_to('Arial')),
        font_size=(re.compile(r'\d+(.\d+)?(pt|\%)'), None),
        font_weight=(('bold', 'normal'), default_to('normal')),
        font_style=(('italic', 'normal'), default_to('normal')),
        underline=(('solid', 'none'), 'solid'.__eq__),
        line_through=(('solid', 'none'), 'solid'.__eq__),
        # special case black foreground
        color=(re.compile(r'#[\da-f]{6}', re.I), default_to('#000000')),
        # special case white background
        background_color=(re.compile(r'#[\da-f]{6}', re.I),
                          default_to('#ffffff')),
        # HACK: 'sub 58%' -> 'sub' but we should really collate by %;
        # but gdoc doesn't really have more than one level anyway
        text_position=(re.compile(r'(sub|super)\b'), lambda x: x.split()[0]),
        # PARAGRAPH
        text_align=(('start', 'end', # FIXME: treat these as left/right for now
                     'left', 'right', 'center', 'justify'),
                    lambda x: default_to('left')({'start':'left'}.get(x, x))),
        line_height=(re.compile(r'-?\d+([.]\d*)?%'), None),
        margin_left=(re.compile(r'-?\d+([.]\d+)?cm'), default_to('0cm')),
        text_indent=(re.compile(r'-?\d+([.]\d+)?cm'), default_to('0cm')),
        par_break=(('auto', 'column', 'page', 'even-page', 'odd-page'),
                   default_to('auto')),
        sub_list_styles=(None, None),
        # TABLE and TABLE-CELL (FIXME: others)
        min_height=(re.compile(r'\d+(.\d+)?cm'), None),
        )

    @staticmethod
    def _check_in(k, v, allowable):
        if v not in allowable:
            raise TypeError('%s must be in %s' % (k, allowable))
    @staticmethod
    def _check_rex(k, v, regexp):
        if not regexp.match(v):
            raise TypeError('%s must match %s, got %r' % (k, regexp.pattern, v))
    def __setattr__(self, k, v):
        raise TypeError("C'mon, surely you don't like mutable datatypes?")
    def __init__(self, stys, name, **kwargs):
        self.__dict__['name'] = name
        self.__dict__['parent'] = kwargs.pop('parent', None)
        self.props['width'] = (
            re.compile(r'-?\d+(?:.\d+)?cm'),
            lambda x, textwidth=stys.textwidth: format_percentage(
                100*float(x[:-2])/textwidth))

        inherited = set()
        for k, (validate, transform) in self.props.iteritems():
            v = kwargs.pop(k, None)
            if v is None:
                # XXX: treat 'Standard' style color as default (black,
                # effectively). The point of this hack is to work around a
                # problem introduced by another workaround for messy documents
                # where the foreground colour for elements is often explicilty
                # set to black, rather than just the default style color: by
                # hardcoding black as the standard text color we fail to deal
                # correctly, for particular secnarios, with documents which
                # (in most cases weirdly) define a different standard text
                # colour, such as #00000a. Since colour is normally ignored in
                # the final output this is only a problem in cases were its
                # presence effects further processing, such as coalescing and
                # html/tex blocks.
                if self.parent and (k != 'color' or self.parent != 'Standard'):
                    v = getattr(stys[self.parent], k, None)
                    if v is not None:
                        inherited.add(k)
                self.__dict__[k] = v
            else:
                if validate:
                    if isinstance(validate, tuple):
                        self._check_in(k, v, validate)
                    else:
                        self._check_rex(k, v, validate)
                self.__dict__[k] = transform(v) if transform else v

        if kwargs:
            raise TypeError('Unexpected keyword arg %r' % kwargs.popitem()[0])
        self.__dict__['inherited'] = frozenset(inherited)
    def active_props(self):
        return [p for p in self.props
                if getattr(self, p) and p not in (
                    'type', 'parent', 'font_family',
                    'font_size', 'line_height')]

    @staticmethod
    def _rel_depths(levels):
        if not levels:
            return {}
        levels = sorted(levels)
        depths = {levels[0] : 0}
        for i_0, i_1  in zip(levels, levels[1:]):
            depths[i_1] = depths[i_0] + 1 if i_1 == i_0 + 1 else 0
        return depths

    @classmethod
    def _get_list_style(cls, style): # pylint: disable=R0914
        OO_ENUMERATIONS = '1aiAI'
        CSS_ENUMERATIONS = ['decimal', 'lower-alpha', 'lower-roman',
                            'upper-alpha', 'upper-roman']
        # The ODT 1.1 spec lists these as common values
        # •BULLET✔HEAVY CHECK MARK✗BALLOT X
        # ➔HEAV WIDE-HEADED RIGHTWARDS ARROW
        # ➢THREE-D TOP-LIGHTED RIGHTWARDS ARROWHEAD
        # FIXME: allow for all of these
        # 'none', 'asterisks', 'box', 'check', 'circle', 'diamond',
        # 'disc', 'hyphen', 'square',
        #
        # XXX: As an additional hack we map several visually close unicode
        # characters to the same CSS bullets. The first 4 are the canonical
        # values as per spec, IIRC, but he second 4 occur frequently in odt
        # documents and at least 'o' has also been observed in a google doc
        # that came from word
        OO_BULLETS = u'●○■-' u'•◦▪–' u'·o⬛—' # −‐ might also be relevant
        CSS_BULLETS = ['disc', 'circle', 'square', 'hyphen'] * 3

        LISTS = [
            ('ol', ns.text('list-level-style-number'),
             ns.style('num-format'), OO_ENUMERATIONS, CSS_ENUMERATIONS),
            ('ul', ns.text('list-level-style-bullet'),
             ns.text('bullet-char'), OO_BULLETS, CSS_BULLETS)]

        ans = {}
        for list_type, what, oo_attr, oo, css in LISTS:
            oo2css = dict(zip(oo, css))
            xml_frags = style.findall(what)
            levels = [int(props.get(ns.text('level'))) for props in xml_frags]
            rel_depth = cls._rel_depths(levels)
            for props, level in zip(xml_frags, levels):
                v = props.get(oo_attr)
                the_prop = oo_attr.split('}')[1]
                default_value_at_this_depth = css[rel_depth[level] % 3]
                list_style_type = oo2css.get(v)
                if list_style_type is None:
                    log.warn("Don't know list-style %s value '%s'",
                             the_prop, v)
                elif list_style_type == default_value_at_this_depth:
                    list_style_type = None

                start = props.get(ns.text('start-value'))
                if start:
                    start = int(start)
                    assert list_type == 'ol'
                ans[level] = dict(list_type=list_type,
                                  list_style_type=list_style_type,
                                  depth=rel_depth[level],
                                  start=start)
        assert ans
        return 'list', ans




    @classmethod
    def from_odt_style(cls, styles, style): # pylint: disable=R0912
        if style.tag in (ns.style('default-style'),
                         ns.style('page-layout'),
                         ns.text('outline-style'),
                         ns.text('notes-configuration'),
                         ns.text('linenumbering-configuration')):
            # default-style appears to serve no real purpose in google docs
            # page-style probably doesn't really matter anyway
            # notes-configuration also doesn't really look that useful
            log.warn('Skipping %s', style.tag.split('}')[1])
            return None
        family, name = style_id(style)
        assert name

        parent = style.get(ns.style('parent-style-name')) #parent_id(style)
        display_name = style.get(ns.style('display-name'))
        if parent:
            parent_style = styles[parent] #FIXME: verify no forward decls
        def true(xml):
            # fix lxml truth stupidity via boxing
            return [xml] if xml is not None else None

        par_props = (true(style.find(ns.style('paragraph-properties')))
                     or [{}])[0]
        text_props = (true(style.find(ns.style('text-properties'))) or [{}])[0]
        # FIXME below assumes table style never sets table-column (table-row)
        # stuff
        table_props = (true(style.find(ns.style('table-column-properties'))) or
                       true(style.find(ns.style('table-row-properties'))) or
                       true(style.find(ns.style('table-cell-properties'))) or
                       true(style.find(ns.style('table-properties'))) or
                       [{}])[0]

        if style.tag == ns.text('list-style'):
            my_type, sub_list_styles = cls._get_list_style(style)
        elif style.tag == ns.style('style'):
            sub_list_styles = None
            # XXX look for a more robust way to do this
            if display_name and display_name.startswith('Heading'):
                my_type = 'h' + display_name.split()[-1]
            elif parent in ('Title', 'Subtitle'):
                my_type = parent.lower()
            elif name in ('Title', 'Subtitle'):
                my_type = name.lower()
            elif parent and parent_style.type:
                my_type = parent_style.type
            elif family == 'paragraph':
                my_type = 'p'
            elif family.startswith('table'):
                #FIXME actually implement something for these
                my_type = {'table': 'table', 'table-cell': 'td',
                           "table-row": "tr", "table-column": "col"}[family]

            else:
                # In reality all the following are valid:
                # paragraph, text, section, table, table-column, table-row,
                # table-cell, table-page, chart, default, drawing-page,
                # graphic, presentation, control and ruby.
                if family != 'text':
                    log.warn("Unexpected style family: %r", family)
                my_type = 'span'
        else:
            raise TypeError('%r is not at style' % style)

        ans = cls(
            styles,
            name=name, #FIXME
            type=my_type, parent=parent,
            # pylint: disable=C0326
            font_family  = text_props.get(ns.style('font-name')),
            font_size    = text_props.get(ns.fo('font-size')),
            font_weight  = text_props.get(ns.fo('font-weight')),
            font_style   = text_props.get(ns.fo('font-style')),
            color        = (text_props.get(ns.fo('color')) or
                            table_props.get(ns.fo('color'))),
            background_color = (text_props.get(ns.fo('background-color')) or
                                table_props.get(ns.fo('background-color'))),
            # in css: text-decoration [underline] [line-through]
            underline    = text_props.get(ns.style('text-underline-style')),
            line_through = text_props.get(ns.style('text-line-through-style')),
            # in css: vertical-align:sub; font-size:smaller;
            text_position = text_props.get(ns.style('text-position')),

            text_align   = par_props.get(ns.fo('text-align')),
            line_height  = par_props.get(ns.fo('line-height')),
            margin_left  = par_props.get(ns.fo('margin-left')),
            par_break    = par_props.get(ns.fo('break-before')),
            text_indent  = par_props.get(ns.fo('text-indent')),

            sub_list_styles = sub_list_styles,

            width         = table_props.get(ns.style('column-width')),
            min_height    = table_props.get(ns.style('min-row-height')),
            )
        if name in styles:
            log.warn('Overwriting old Sty %r %r => %r', name, styles[name], ans)
        styles[name] = ans
        return ans

    def __repr__(self):
        return "%s(%r, parent=%r, %s)" % (
            type(self).__name__, self.name, self.parent,
            ", ".join("%s=%r" % (k, getattr(self, k))
                      for k in sorted(self.props)
                      if getattr(self, k) is not None
                      and k not in self.inherited))

assert (Sty._rel_depths([1, 2, 3, 5, 6, 7, 8, 10, 9]) == #pylint: disable=W0212
        {1: 0, 2: 1, 3: 2, 5: 0, 6: 1, 7: 2, 8: 3, 9: 4, 10: 5})



def read_in_styles(styles, content, transclusions):
    stys = DocStys()
    # Page properties
    raw_header = styles.find(ns.office('master-styles/')
                             + ns.style('master-page/')
                             + ns.style('header'))
    raw_footer = styles.find(ns.office('master-styles/')
                             + ns.style('master-page/')
                             + ns.style('footer'))
    page_layout = (styles.find(ns.office('automatic-styles/') +
                               ns.style('page-layout/')))
    page_width, lmargin, rmargin, lpad, rpad = [
        in_cm(page_layout.get(ns.fo(k), '0cm')) for k in
        ['page-width',
         'margin-left', 'margin-right',
         'padding-left', 'padding-right']]
    stys.textwidth = float(page_width - (lmargin + rmargin + lpad + rpad))
    log.warn('Textwidth: %fcm', stys.textwidth)
    # the actual meat
    for stylebit in styles.find(ns.office('styles')):
        stys.add_odt_style(stylebit)
    for stylebit in styles.find(ns.office('automatic-styles')):
        stys.add_odt_style(stylebit)
    stys.header, stys.footer = (
        raw is not None and
        list(parse_body(raw, ParseContext(stys), transclusions))
        for raw in [raw_header, raw_footer])
    # NB: the parsing of the content styLes has to come *after* we've got the
    # header and footer, because they'll clobber the automatic styles defined
    # in styles.xml (I'm not sure if that's spec conformant), which apply to
    # the header and footer text
    for stylebit in content.find(ns.office('automatic-styles')):
        stys.add_odt_style(stylebit)
    return stys


def parse_body(xml, context, normalize_transclusion):
    # pylint: disable=R0912,R0915,R0914
    for e in xml:
        text = (e.text or '')
        tail = (e.tail or '')

        # some style properties should be promoted to tags, e.g. underlining
        # and bolding
        tags_from_style = []
        stys_dealt_with = []

        if e.tag in (S_TAG, TAB_TAG):
            yield ' \t'[e.tag == TAB_TAG] * int(e.attrib.get(ns.text('c'), '1'))
            if tail:
                yield tail
            continue

        if e.tag == LINEBREAK_TAG:
            yield mkel('br', {}, [])
            continue

        sty = context.stys.get(e.get(STYLE_NAME_ATTR) or
                               e.get(TABLE_STYLE_NAME_ATTR))
        # handle page breaks
        if sty and sty.par_break:
            assert e.tag in (H_TAG, P_TAG), \
                   "Unexpected page-break in %r" % e.tag
            yield mkel('.pagebreak', {}, [])
            stys_dealt_with.append('par_break')
        # Handle lists specially
        if e.tag == LIST_TAG:
            new_context = context.bump_list_level(sty)
            stys_dealt_with.append('sub_list_styles')
        else:
            new_context = context
        body = list(parse_body(e, new_context, normalize_transclusion))
        assert type(body) is list and not body or type(body[0]) is not list
        attrs = {}
        if text:
            body = [text] + body
        if sty and sty.type.endswith('title'):
            head = sty.type
            body = [plaintextify(body)]
            sty = None
        elif e.tag == H_TAG:
            # skip empty headings; NB: this *must* happen
            # after we extracted eventual page-breaks, which are the only
            # useful information empty headings can contain
            if blank(body):
                continue
            head = sty.type
            # FIXME(alexander): keep track of the headings breadcrumbs in
            # context for two reasons
            #
            #  1. to associate errors with specific headings
            #  2. to warn about bad structure e.g. h1 followed by h4,
            #     rather than h2
        elif e.tag == LIST_TAG:
            head = new_context.list_type
            assert head in ('ol', 'ul')
            list_start = new_context.list_start
            if list_start is not None:
                assert head == 'ol'
                attrs['start'] = str(list_start)

            id_ = e.attrib.get(ns.xml('id')) # pylint: disable=E1101
            if id_ is not None:
                attrs['id'] = id_
            continues = e.attrib.get(ns.text('continue-list'))
            if continues is not None:
                # make this a data attrib, so we can stuff it
                # into the html, which doesn't have direct support
                attrs['data-continue-list'] = continues

        elif e.tag == LIST_ITEM_TAG:
            head = 'li'
        elif e.tag == ANNOTATION_TAG:
            head = 'aside'
        elif e.tag in (CREATOR_TAG, NOTE_CITATION_TAG, BOOKMARK_END_TAG):
            #FIXME: extract content
            if text:
                log.warning('Hey, someone actually specified a %s: %s',
                            e.tag, text)
            if tail:
                yield tail
            continue
        elif e.tag == NOTE_TAG:
            # other valid option is 'endnote'
            assert e.attrib[ns.text('note-class')] == 'footnote'
            # skip ahead and exit early; we only represent the note-body
            assert len(e) == 2 and e[1].tag == NOTE_BODY_TAG
            assert len(body) == 1
            yield body[0]
            if tail:
                yield tail
            continue
        elif e.tag == NOTE_BODY_TAG:
            head = '.footnote'
            # FIXME(alexander): sucky hack to strip the bogus whitespace
            # google docs enters at the beginning of a footnote for some
            # reason. I should really write a more generic whitespace
            # stripping mechanism in the postprocess module that can recognize
            # consecutive whitespace even if seperated-by/wrapped-in inline
            # tags.
            _, B1, B2, = map(Var, '_, B1, B2'.split(', '))
            SPACED_STR = Var('SPACED_STR', lambda s: (isinstance(s, basestring)
                                                      and re.match(r'\s+', s)))
            if body == Seq[('p', _, Seq[SPACED_STR, B2:]), B1:]:
                body[0][2][0] = SPACED_STR.val.lstrip()
        # FIXME(alexander): add anchors for all paras
        elif e.tag == P_TAG:
            margin = sty.margin_left or sty.text_indent if sty else None
            indent_level = in_indents(margin) if margin else 0
            if indent_level:
                head = '.block'
                attrs['indent'] = indent_level
            else:
                head = 'p'

        #FIXME styled links etc. gdocs might not use that...
        #... but we should be able to handle non-span bolding etc.
        elif e.tag == SPAN_TAG:
            # XXX: order can matter; we need
            #   <b><u>command</u><b>
            # not
            #   <u><b>command</b><u>
            #
            # but more generally the minimal coalescing of abutting partially
            # overlapping styles is something that needs to be thought about
            # properly at some point.
            for attr, on_values, html_tags in [
                    ('underline', [True], ['u']),
                    ('font_weight', ['bold'], ['b']),
                    ('font_style', ['italic'], ['i']),
                    ('line_through', [True], ['s']),
                    ('text_position',
                     ['sub', 'super'],
                     ['sub', 'sup'])
            ]:
                value = getattr(sty, attr, None)
                if value:
                    if value not in on_values:
                        log.error("Bad value for %s: %s in %s",
                                  attr, value, e.tag)
                        continue
                    tags_from_style.append(html_tags[on_values.index(value)])
                    stys_dealt_with.append(attr)
            if is_code_font(sty.font_family):
                tags_from_style.append('code')
                stys_dealt_with.append('font_family')
            head = 'span'
        elif e.tag == A_TAG:
            assert e.attrib[ns.xlink('type')] == 'simple'
            head = 'a'
            attrs = dict(href=e.attrib[HREF_ATTR])
            # FIXME the in 'span' check is a bit too general, should use
            # something else to markup textcolor
            body = tidy(whack(lambda x: x in ('span', 'u'), body))
        elif e.tag == BOOKMARK_START_TAG:
            head = 'a'
            attrs = dict(name=e.attrib[TEXT_NAME_ATTR])
            assert (blank(text) and blank(tail) and
                    next(e.itersiblings()).tag == BOOKMARK_END_TAG)
        elif e.tag == TABLE_TAG:
            head = 'table'
            body = parse_table_body(body)
        elif e.tag == TABLE_ROW_TAG:
            head = 'tr'
        elif e.tag == TABLE_CELL_TAG:
            head = 'td'
        #FIXME repetition via table:number-columns-repeated
        #FIXME handle column-groups
        elif e.tag == TABLE_COLUMN_TAG:
            head = 'col'
            sty = context.stys.get(e.attrib.get(ns.table('style-name')))
            if sty and sty.width is not None:
                # XXX this isn't really the column width
                # since google moronically saves this even
                # if set column width is turned off thank you google!
                attrs = dict(style=OrderedDict(width=sty.width))
                stys_dealt_with.append('width')

        elif e.tag == FRAME_TAG:
            # XXX: try to find caption
            # FIXME(alexander): keep figures/tables with captions in context,
            # so that we can produce a lot/loi; add an id for all of them
            inline = e.attrib[ns.text('anchor-type')] == 'as-char'
            width = (e.attrib.get(ns.svg('width')) # pylint: disable=E1101
                     or e.attrib[ns.style('rel-width')])
            # FIXME(alexander): should handle all these, in theory:
            # <http://www.w3.org/TR/SVG11/struct.html#SVGElementWidthAttribute>
            # ("em" | "ex" | "px" | "in" | "cm" | "mm" | "pt" | "pc" )
            assert width.endswith('cm'), \
                'Expected figure width in cm, got %s' % width
            relwidth = float(width[:-2]) / context.stys.textwidth
            head, attrs, body = make_figure(
                relwidth=relwidth, inline=inline,
                # FIXME(alexander): the body[0][1] to access the image
                # will blow up on leading whitespace in the body
                body=list(x for x in body
                          if not (isinstance(x, basestring) and blank(x))),
                src=body[0][1]['src'],
                original_href=e.find(ns.draw('image')).get(ns.xlink('href')))
        elif e.tag == IMAGE_TAG:
            head = 'img'
            attrs = dict(src=normalize_transclusion(e.attrib[HREF_ATTR]))
        else:
            log.warning('Ignoring tag %s', e.tag)
            continue
            # FIXME raise RuntimeError('Unexpected tag: %s' % e.tag)
        sty_tagged = reduce(lambda parsed, tag: [mkel(tag, {}, parsed)],
                            tags_from_style, tidy(body))
        if sty:
            if sty.text_align:
                stys_dealt_with.append('text_align')
                attrs = add_class(attrs, sty.text_align)
            if sty.background_color:
                stys_dealt_with.append('background_color')
                iadd_style(attrs, 'background-color', sty.background_color)
            if sty.color:
                stys_dealt_with.append('color')
                iadd_style(attrs, 'color', sty.color)
        if e.tag == LIST_TAG:
            if new_context.list_style_type:
                attrs = add_class(attrs, new_context.list_style_type)
        # FIXME additional tidy
        parsed = mkel(head, attrs, sty_tagged)
        if head == 'span' and 'style' in attrs:
            B = Var('B')
            if parsed == ('span', attrs, [('code', {}, B)]):
                parsed = mkel('code', {}, [('span', attrs, B.val)])

        leftover_styles = sty and set(sty.active_props()) - set(stys_dealt_with)
        if leftover_styles:
            log.warn('Ignoring style elements: %r in %r "%s"', (
                [(k, getattr(sty, k)) for k in leftover_styles]), head,
                     plaintextify(body))
        preprocess.maybe_anchorize_id(head, attrs, sty_tagged)
        yield parsed
        if tail:
            yield tail

class DEBUG_INFO: pass # pylint: disable=W0232,C0321,C1001

def parse_styles_and_body(stys, content, transclusions, upto=None):
    assert type(stys) is DocStys
    parse_context = ParseContext(stys)
    text = content.find(ns.office('body/') +
                        ns.office('text'))
    DEBUG_INFO.parse_context = parse_context
    DEBUG_INFO.stys = stys
    DEBUG_INFO.content = content
    raw_body = list(parse_body(
        text[:upto], parse_context,
        normalize_transclusion=transclusions.normalize_known_transclusion))
    return raw_body, transclusions, text
