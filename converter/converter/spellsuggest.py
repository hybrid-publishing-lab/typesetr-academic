from itertools import count

import jellyfish

# FIXME(alexander): jellyfish doesn't correctly work with unicode characters,
# so for now, replace them. Since it's only used for metavariable names and
# these don't presently contain unicode, the results should remain correct.
# However, we should eventually submit a fix or just write our own
# (pure-python) implementation of the algorithm.
def deunicode(s):
    return "".join(chr(x) if x < 128 else '#' for x in map(ord, s))

def spell_suggest(word, possibilities):
    r"""Return a ordered list of spelling suggestions for `word`.

    Suggestions are drawn from `possibilities`. If the word is too dissimilar
    the list will be empty.

    >>> possible='''title subtitle client project author recipients version date
    ... tnc toc toc-depth title subtitle client project author recipients
    ... confidential tnc toc toc-depth'''.split()
    >>> spell_suggest('recipient', possible)
    ['recipients']
    >>> spell_suggest('t&c', possible)
    ['tnc']
    >>> spell_suggest('foobar', possible)
    []
    """
    # pylint: disable=E1101
    dist, best_i = min(
        zip((jellyfish.damerau_levenshtein_distance(deunicode(word),
                                                    poss)
             for poss in possibilities),
            count()))
    if dist <= min(3, len(possibilities[best_i])/2):
        return [possibilities[best_i]]
    return []
