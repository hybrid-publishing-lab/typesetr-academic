from converter.internal import mkel, merge_attrs


def _transform(f, body):
    res = []
    for e in body:
        if isinstance(e, basestring):
            res.append(e)
        else:
            bh, ba, bb = f(e)
            res.append((bh, ba, _transform(f, bb)))
    return res


def endnotify(body, aside_attrs, a_attrs, section_attrs):
    """Transform .footnotes to noterefs and chapter rearnotes.

    Assumes that `body` is a list of `<section>s`.
    """
    ans = []
    for section in body:
        t, a, b = section
        secid = a['id']
        # pylint: disable=W0640
        counter = [0]
        endnotes = []
        def split_footnote(e):
            t, a, b = e
            if t != '.footnote':
                return e
            counter[0] += 1
            ordinal = [str(counter[0])]
            fid = '%s-fn%d' % (secid, counter[0]) if 'id' not in a else a['id']
            endnotes.append(mkel('aside',
                                 merge_attrs(a, aside_attrs, {'id': fid}), b))
            return mkel('a',
                        merge_attrs(a_attrs, {'href': '#' + fid}), ordinal)
        b = _transform(split_footnote, b)
        if len(endnotes) > 0:
            b.append(mkel('section', section_attrs, endnotes))
        ans.append((t, a, b))
    return ans
