# -*- file-encoding: utf-8 -*-

import base64
import random
import struct

from converter.ezmatch import Var, Seq
from converter.internal import mkel, H_TAGS
from converter.postprocess import plaintextify, whack_elt


def make_stable_gensym(seed):
    rng = random.Random()
    rng.seed(seed)
    def stable_gensym():
        # pylint: disable=W0622
        bytes = struct.pack('>Q', rng.getrandbits(64))
        return 'G.' + base64.b32encode(bytes)[:12].lower()
    return stable_gensym


def lift_anchor_id(attr, body, gensym, kill_anchor):
    """Map `x=$X y=$Y> <a name=$ID/> ...` to `x=$X id=$ID>...`.

    Only lift if `'id'` not in `attr`.
    """
    # about general multiple-id handling strategy

    # pylint: disable=C0103
    REF, REST = map(Var, 'REF, REST'.split(', '))
    if (body == Seq[('a', {'name': REF}, []), REST:] or
        body == Seq[('a', {'id': REF}, []), REST:]): # pylint: disable=C0330
        if 'id' not in attr:
            attr = attr.copy()
            attr['id'] = REF.val
            if kill_anchor:
                body = REST.val
    elif 'id' not in attr:
        attr['id'] = gensym()
    return attr, body


def ensec(heading, section, kill_anchor, gensym):
    h, attr, body = heading
    assert h in H_TAGS
    # reasons for lifting the anchor id to the section include:
    # - epub seems to require sections to have id's
    # - endnotify expects sections to have id's
    attr, body = lift_anchor_id(attr, body, gensym, kill_anchor)
    return mkel('section', attr, [mkel(h, {}, body)] + section)


def tocify_heading(e, gensym):
    """Transform a heading into `('h*', {'id':ID}, [STRING])`.

    This assumes `h*` already has an id or is followed by an anchor.
    """
    # pylint: disable=C0103
    h, a, b = e
    assert h in H_TAGS
    a, b = lift_anchor_id(a, b, gensym, kill_anchor=True)
    return (h, {'id': a['id']}, [plaintextify(b)])


def _sectionize(body, level, toc_upto, kill_anchors, gensym):
    gobbled = []
    toc = []
    while True:
        if not body:
            return gobbled, toc
        e = body.pop(0)
        if e and e[0] in H_TAGS:
            if e[0] <= level:
                body.insert(0, e)
                return gobbled, toc
            if level <= toc_upto:
                toc.append(tocify_heading(e, gensym))
            subgobble, subtoc = _sectionize(body, e[0], toc_upto,
                                            kill_anchors, gensym)
            gobbled.append(ensec(e, subgobble, kill_anchors, gensym))
            if subtoc:
                toc.append(subtoc)
        else:
            gobbled.append(e)


# XXX(ash): not sure about providing this default for `gensym`
def sectionize(body, toc_upto=H_TAGS[-1], h_less_section='pre-section',
               kill_anchors=True, gensym=make_stable_gensym(0)):
    ur"""DESTRUCTIVELY wrap `<h*>`s in body in `<sections>` and return a toc.

    The `sections` lift the ids from the `h*`s, or if the `h*`s have none,
    from their anchors.

    Note that there are two cases::

           well-structured case              not-so-well-structured
       ____________/\_____________    ________________/\______________
      /                           \  /                                \

                                                ⊤                     sᵦ₀
                                                |                      |
                                           _____|                      |
       h1      s₁₀                         h3                s₃₀      eᵦ₀
       |_       |                       ___|                 |
       | h2     |      s₂₀              h2          s₂₀      e₃₀
       | |      |       |               |            |
       | h2     |      e₂₀ s₂₁          h2          e₂₀ s₂₁
       | |—–h3  |           |   s₃₀     |—————h4         |       s₄₀
       | |  |   |           |    |      |     |          |        |
       |_|__|   |           |    |     _|_____|          |        |
       h1      e₁₀ s₁₁     e₂₁  e₃₀   h1        s₁₀     e₂₁      e₄₀
       |            |                 |          |
       ⊥           e₁₁                ⊥         e₁₀

    For the not-so-well-structured case, what should happen with content
    preceding any sections is determined by `h_less_section` – if it's a
    non-empty string, then it gets wrapped into a section with that string as
    id. Strange section structure (h3 precding h2, h2 followed directly by h4
    tc.) is not handled specially in any way (it should probably be
    flagged and optionally repaired at ingress).
    """
    if h_less_section:
        buf = []
        front_secced = mkel('section', {'id': h_less_section}, buf)
        while body and body[0] and body[0][0] not in H_TAGS:
            buf.append(body.pop(0))
        if buf:
            body.insert(0, front_secced)
    return _sectionize(body, level='h0', toc_upto=toc_upto,
                       kill_anchors=kill_anchors, gensym=gensym)


def unsectionize(body):
    def is_bogus_section(e):
        t, a, _ = e
        return t == 'section' and ('endnotes' not in a.get('class', []))
    return whack_elt(is_bogus_section, body)
