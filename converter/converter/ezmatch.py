#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
def _pred_repr(pred, pargs, pkwargs):
    if not pred:
        return ''
    else:
        myrepr = lambda x: x.__name__ if hasattr(x, '__name__') else repr(x)
        f = myrepr(pred)
        args = map(myrepr, pargs)
        kwargs = ["%s=%r" % (k, myrepr(v)) for (k, v) in pkwargs.values()]
        return "(%s)" % ", ".join([f] + args + kwargs)

class Var(object):
    def __init__(self, name=None, pred=None, *args, **kwargs):
        # pylint: disable=C0103
        self._name = name
        self._pred, self._pargs, self._pkwargs = pred, args, kwargs
        self.match = None

    def __call__(self, pred, *args, **kwargs):
        return type(self)(self._name, pred, *args, **kwargs)

    def __eq__(self, other):
        self.match = (self._pred is None or
                      self._pred(other, *self._pargs, **self._pkwargs))
        if self.match and not self._name.startswith('_'):
            self.val = other # pylint: disable=W0201
        return self.match

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return "%s%s" % (self._name,
                         _pred_repr(self._pred, self._pargs, self._pkwargs))

class FixedRepr(object):
    def __init__(self, repr_str):
        self.repr = repr_str
    def __repr__(self):
        return self.repr

class SeqSlice(object):
    def __init__(self, args=(), pred=None, *pargs, **pkwargs):
        for x in args[:-1]:
            assert type(x) is not slice
        self.args = args
        self._pred, self._pargs, self._pkwargs = pred, pargs, pkwargs

    def __call__(self, pred, *pargs, **pkwargs):
        return type(self)(self.args, pred, *pargs, **pkwargs)

    def __getitem__(self, args):
        return type(self)(args if type(args) is tuple else (args,),
                          self._pred, *self._pargs, **self._pkwargs)

    def __repr__(self):
        return 'Seq' + repr(
            [{slice:  lambda a: FixedRepr((repr(a.start) if a.start is not None
                                           else '') + ':'),
              type(Ellipsis): lambda a: FixedRepr('...')}.get(type(a),
                                                              lambda a: a)(a)
             for a in self.args]) + _pred_repr(
                 self._pred, self._pargs, self._pkwargs)

    def __eq__(self, other):
        try:
            othert = tuple(other)
        except TypeError:
            return False
        match = (self._pred is None or
                 self._pred(other, *self._pargs, **self._pkwargs))
        if not match:
            return False
        if self.args and type(self.args[-1]) is slice:
            return self.args[:-1] == othert[:len(self.args)-1] and (
                self.args[-1].start is None or
                self.args[-1].start == other[len(self.args)-1:])
        return self.args == othert

    def __ne__(self, other):
        return not self == other

Seq = SeqSlice() # pylint: disable=C0103
__all__ = ('Var', 'Seq')
