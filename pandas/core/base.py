"""
Base and utility classes for pandas objects.
"""
from pandas import compat
import numpy as np
from pandas.core import common as com

class StringMixin(object):
    """implements string methods so long as object defines a `__unicode__` method.
    Handles Python2/3 compatibility transparently."""
    # side note - this could be made into a metaclass if more than one object nees

    #----------------------------------------------------------------------
    # Formatting

    def __unicode__(self):
        raise NotImplementedError

    def __str__(self):
        """
        Return a string representation for a particular Object

        Invoked by str(df) in both py2/py3.
        Yields Bytestring in Py2, Unicode String in py3.
        """

        if compat.PY3:
            return self.__unicode__()
        return self.__bytes__()

    def __bytes__(self):
        """
        Return a string representation for a particular object.

        Invoked by bytes(obj) in py3 only.
        Yields a bytestring in both py2/py3.
        """
        from pandas.core.config import get_option

        encoding = get_option("display.encoding")
        return self.__unicode__().encode(encoding, 'replace')

    def __repr__(self):
        """
        Return a string representation for a particular object.

        Yields Bytestring in Py2, Unicode String in py3.
        """
        return str(self)


class PandasObject(StringMixin):
    """baseclass for various pandas objects"""

    @property
    def _constructor(self):
        """class constructor (for this class it's just `__class__`"""
        return self.__class__

    def __unicode__(self):
        """
        Return a string representation for a particular object.

        Invoked by unicode(obj) in py2 only. Yields a Unicode String in both
        py2/py3.
        """
        # Should be overwritten by base classes
        return object.__repr__(self)

class FrozenList(PandasObject, list):
    """
    Container that doesn't allow setting item *but*
    because it's technically non-hashable, will be used
    for lookups, appropriately, etc.
    """
    # Sidenote: This has to be of type list, otherwise it messes up PyTables typechecks

    def __add__(self, other):
        if isinstance(other, tuple):
            other = list(other)
        return self.__class__(super(FrozenList, self).__add__(other))

    __iadd__ = __add__

    # Python 2 compat
    def __getslice__(self, i, j):
        return self.__class__(super(FrozenList, self).__getslice__(i, j))

    def __getitem__(self, n):
        # Python 3 compat
        if isinstance(n, slice):
            return self.__class__(super(FrozenList, self).__getitem__(n))
        return super(FrozenList, self).__getitem__(n)

    def __radd__(self, other):
        if isinstance(other, tuple):
            other = list(other)
        return self.__class__(other + list(self))

    def __eq__(self, other):
        if isinstance(other, (tuple, FrozenList)):
            other = list(other)
        return super(FrozenList, self).__eq__(other)

    __req__ = __eq__

    def __mul__(self, other):
        return self.__class__(super(FrozenList, self).__mul__(other))

    __imul__ = __mul__

    def __reduce__(self):
        return self.__class__, (list(self),)

    def __hash__(self):
        return hash(tuple(self))

    def _disabled(self, *args, **kwargs):
        """This method will not function because object is immutable."""
        raise TypeError("'%s' does not support mutable operations." %
                        self.__class__.__name__)

    def __unicode__(self):
        from pandas.core.common import pprint_thing
        return "%s(%s)" % (self.__class__.__name__,
                           pprint_thing(self, quote_strings=True,
                                        escape_chars=('\t', '\r', '\n')))

    __setitem__ = __setslice__ = __delitem__ = __delslice__ = _disabled
    pop = append = extend = remove = sort = insert = _disabled


class FrozenNDArray(PandasObject, np.ndarray):

    # no __array_finalize__ for now because no metadata
    def __new__(cls, data, dtype=None, copy=False):
        if copy is None:
            copy = not isinstance(data, FrozenNDArray)
        res = np.array(data, dtype=dtype, copy=copy).view(cls)
        return res

    def _disabled(self, *args, **kwargs):
        """This method will not function because object is immutable."""
        raise TypeError("'%s' does not support mutable operations." %
                        self.__class__)

    __setitem__ = __setslice__ = __delitem__ = __delslice__ = _disabled
    put = itemset = fill = _disabled

    def _shallow_copy(self):
        return self.view()

    def values(self):
        """returns *copy* of underlying array"""
        arr = self.view(np.ndarray).copy()
        return arr
