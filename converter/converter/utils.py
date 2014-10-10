#-*- encoding: utf-8 -*-
from collections import OrderedDict
import logging as log

def format_percentage(x):
    return ('%.2f' % x).rstrip('0').rstrip('.') + '%'

def snap_width_percentage(width_percentage):
    SNAPS_PER_PAGE = 33 # pylint: disable=C0103
    snaps = round(SNAPS_PER_PAGE * (width_percentage/100.0))
    # significantly over text width - full size figure
    xlarge = snaps > SNAPS_PER_PAGE + 1
    snaps = min(snaps, SNAPS_PER_PAGE)
    width = round(100 * snaps / SNAPS_PER_PAGE, 2)
    return width, xlarge

def parse_percentage(percentage_str):
    assert percentage_str.endswith('%')
    return float(percentage_str[:-1])


MAX_INLINE_WIDTH_RATIO = .75


def make_figure(relwidth, inline, body, src, original_href):
    width_percentage, xlarge = snap_width_percentage(relwidth * 100.0)
    width_percentage_str = format_percentage(width_percentage)
    # large inline image heuristic: Large inlined images are likely a
    # user error; unfortunately its impossible to see in Google Docs
    # if a figure starts a paragraph or is inline and simply large
    # enough to visually appear to be in a a separate paragraph. This
    # may require some additional cleanup in postprocessing to ensure
    # a pargraph that contains a block figure is split into 2
    if inline and relwidth > MAX_INLINE_WIDTH_RATIO:
        # XXX(alexander): should really make this into a user-facing
        # message
        log.info('Figure %r (%r) at %s>%s of text-width; '
                 'switch to freestanding', src, original_href,
                 width_percentage_str, '%.0f%%' % (MAX_INLINE_WIDTH_RATIO*100))
        inline = False
    if inline:
        log.info('Figure %r (%r) kept inline for now: %s',
                 src, original_href, width_percentage_str)
    attrs = dict(
        style=OrderedDict([
            ('display', 'inline' if inline else 'block'),
            ('width', width_percentage_str),
        ]))
    if not inline and width_percentage >= 100:
        attrs['class'] = ['fullwidth' if xlarge else 'textwidth']
    return 'figure', attrs, body
