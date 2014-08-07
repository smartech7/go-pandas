"""
Base and utility classes for pandas objects.
"""
import datetime

from pandas import compat
import numpy as np
from pandas.core import common as com
import pandas.core.nanops as nanops
import pandas.tslib as tslib
from pandas.util.decorators import Appender, cache_readonly

class StringMixin(object):

    """implements string methods so long as object defines a `__unicode__`
    method.

    Handles Python2/3 compatibility transparently.
    """
    # side note - this could be made into a metaclass if more than one
    #             object needs

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

    def _local_dir(self):
        """ provide addtional __dir__ for this object """
        return []

    def __dir__(self):
        """
        Provide method name lookup and completion
        Only provide 'public' methods
        """
        return list(sorted(list(set(dir(type(self)) + self._local_dir()))))

    def _reset_cache(self, key=None):
        """
        Reset cached properties. If ``key`` is passed, only clears that key.
        """
        if getattr(self, '_cache', None) is None:
            return
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

class PandasDelegate(PandasObject):
    """ an abstract base class for delegating methods/properties """

    def _delegate_property_get(self, name, *args, **kwargs):
        raise TypeError("You cannot access the property {name}".format(name=name))

    def _delegate_property_set(self, name, value, *args, **kwargs):
        raise TypeError("The property {name} cannot be set".format(name=name))

    def _delegate_method(self, name, *args, **kwargs):
        raise TypeError("You cannot call method {name}".format(name=name))

    @classmethod
    def _add_delegate_accessors(cls, delegate, accessors, typ):
        """
        add accessors to cls from the delegate class

        Parameters
        ----------
        cls : the class to add the methods/properties to
        delegate : the class to get methods/properties & doc-strings
        acccessors : string list of accessors to add
        typ : 'property' or 'method'

        """

        def _create_delegator_property(name):

            def _getter(self):
                return self._delegate_property_get(name)
            def _setter(self, new_values):
                return self._delegate_property_set(name, new_values)

            _getter.__name__ = name
            _setter.__name__ = name

            return property(fget=_getter, fset=_setter, doc=getattr(delegate,name).__doc__)

        def _create_delegator_method(name):

            def f(self, *args, **kwargs):
                return self._delegate_method(name, *args, **kwargs)

            f.__name__ = name
            f.__doc__ = getattr(delegate,name).__doc__

            return f

        for name in accessors:

            if typ == 'property':
                f = _create_delegator_property(name)
            else:
                f = _create_delegator_method(name)

            setattr(cls,name,f)

class FrozenList(PandasObject, list):

    """
    Container that doesn't allow setting item *but*
    because it's technically non-hashable, will be used
    for lookups, appropriately, etc.
    """
    # Sidenote: This has to be of type list, otherwise it messes up PyTables
    #           typechecks

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
        return pprint_thing(self, quote_strings=True,
                            escape_chars=('\t', '\r', '\n'))

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__,
                           str(self))

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

    def __unicode__(self):
        """
        Return a string representation for this object.

        Invoked by unicode(df) in py2 only. Yields a Unicode String in both
        py2/py3.
        """
        prepr = com.pprint_thing(self, escape_chars=('\t', '\r', '\n'),
                                 quote_strings=True)
        return "%s(%s, dtype='%s')" % (type(self).__name__, prepr, self.dtype)

def _unbox(func):
    @Appender(func.__doc__)
    def f(self, *args, **kwargs):
        result = func(self.values, *args, **kwargs)
        from pandas.core.index import Index
        if isinstance(result, (np.ndarray, com.ABCSeries, Index)) and result.ndim == 0:
            # return NumPy type
            return result.dtype.type(result.item())
        else:  # pragma: no cover
            return result
    f.__name__ = func.__name__
    return f

class IndexOpsMixin(object):
    """ common ops mixin to support a unified inteface / docs for Series / Index """

    # ndarray compatibility
    __array_priority__ = 1000

    def transpose(self):
        """ return the transpose, which is by definition self """
        return self

    T = property(transpose, doc="return the transpose, which is by definition self")

    @property
    def shape(self):
        """ return a tuple of the shape of the underlying data """
        return self._data.shape

    @property
    def ndim(self):
        """ return the number of dimensions of the underlying data, by definition 1 """
        return 1

    def item(self):
        """ return the first element of the underlying data as a python scalar """
        try:
            return self.values.item()
        except IndexError:
            # copy numpy's message here because Py26 raises an IndexError
            raise ValueError('can only convert an array of size 1 to a '
                             'Python scalar')

    @property
    def data(self):
        """ return the data pointer of the underlying data """
        return self.values.data

    @property
    def itemsize(self):
        """ return the size of the dtype of the item of the underlying data """
        return self.values.itemsize

    @property
    def nbytes(self):
        """ return the number of bytes in the underlying data """
        return self.values.nbytes

    @property
    def strides(self):
        """ return the strides of the underlying data """
        return self.values.strides

    @property
    def size(self):
        """ return the number of elements in the underlying data """
        return self.values.size

    @property
    def flags(self):
        """ return the ndarray.flags for the underlying data """
        return self.values.flags

    @property
    def base(self):
        """ return the base object if the memory of the underlying data is shared """
        return self.values.base

    def max(self):
        """ The maximum value of the object """
        return nanops.nanmax(self.values)

    def argmax(self, axis=None):
        """
        return a ndarray of the maximum argument indexer

        See also
        --------
        numpy.ndarray.argmax
        """
        return nanops.nanargmax(self.values)

    def min(self):
        """ The minimum value of the object """
        return nanops.nanmin(self.values)

    def argmin(self, axis=None):
        """
        return a ndarray of the minimum argument indexer

        See also
        --------
        numpy.ndarray.argmin
        """
        return nanops.nanargmin(self.values)

    def hasnans(self):
        """ return if I have any nans; enables various perf speedups """
        return com.isnull(self).any()

    def value_counts(self, normalize=False, sort=True, ascending=False,
                     bins=None, dropna=True):
        """
        Returns object containing counts of unique values.

        The resulting object will be in descending order so that the
        first element is the most frequently-occurring element.
        Excludes NA values by default.

        Parameters
        ----------
        normalize : boolean, default False
            If True then the object returned will contain the relative
            frequencies of the unique values.
        sort : boolean, default True
            Sort by values
        ascending : boolean, default False
            Sort in ascending order
        bins : integer, optional
            Rather than count values, group them into half-open bins,
            a convenience for pd.cut, only works with numeric data
        dropna : boolean, default True
            Don't include counts of NaN.

        Returns
        -------
        counts : Series
        """
        from pandas.core.algorithms import value_counts
        from pandas.tseries.api import DatetimeIndex, PeriodIndex
        result = value_counts(self, sort=sort, ascending=ascending,
                              normalize=normalize, bins=bins, dropna=dropna)

        if isinstance(self, PeriodIndex):
            # preserve freq
            result.index = self._simple_new(result.index.values, self.name,
                                            freq=self.freq)
        elif isinstance(self, DatetimeIndex):
            result.index = self._simple_new(result.index.values, self.name,
                                            tz=getattr(self, 'tz', None))
        return result

    def unique(self):
        """
        Return array of unique values in the object. Significantly faster than
        numpy.unique. Includes NA values.

        Returns
        -------
        uniques : ndarray
        """
        from pandas.core.nanops import unique1d
        values = self.values
        if hasattr(values,'unique'):
            return values.unique()

        return unique1d(values)

    def nunique(self, dropna=True):
        """
        Return number of unique elements in the object.

        Excludes NA values by default.

        Parameters
        ----------
        dropna : boolean, default True
            Don't include NaN in the count.

        Returns
        -------
        nunique : int
        """
        return len(self.value_counts(dropna=dropna))

    def factorize(self, sort=False, na_sentinel=-1):
        """
        Encode the object as an enumerated type or categorical variable

        Parameters
        ----------
        sort : boolean, default False
            Sort by values
        na_sentinel: int, default -1
            Value to mark "not found"

        Returns
        -------
        labels : the indexer to the original array
        uniques : the unique Index
        """
        from pandas.core.algorithms import factorize
        return factorize(self, sort=sort, na_sentinel=na_sentinel)

    def searchsorted(self, key, side='left'):
        """ np.ndarray searchsorted compat """

        ### FIXME in GH7447
        #### needs coercion on the key (DatetimeIndex does alreay)
        #### needs tests/doc-string
        return self.values.searchsorted(key, side=side)

    #----------------------------------------------------------------------
    # unbox reductions

    all = _unbox(np.ndarray.all)
    any = _unbox(np.ndarray.any)

class DatetimeIndexOpsMixin(object):
    """ common ops mixin to support a unified inteface datetimelike Index """

    def __iter__(self):
        return (self._box_func(v) for v in self.asi8)

    @property
    def _box_func(self):
        """
        box function to get object from internal representation
        """
        raise NotImplementedError

    def _box_values(self, values):
        """
        apply box func to passed values
        """
        import pandas.lib as lib
        return lib.map_infer(values, self._box_func)

    @cache_readonly
    def hasnans(self):
        """ return if I have any nans; enables various perf speedups """
        return (self.asi8 == tslib.iNaT).any()

    @property
    def asobject(self):
        from pandas.core.index import Index
        return Index(self._box_values(self.asi8), name=self.name, dtype=object)

    def tolist(self):
        """
        return a list of the underlying data
        """
        return list(self.asobject)

    def min(self, axis=None):
        """
        return the minimum value of the Index

        See also
        --------
        numpy.ndarray.min
        """
        try:
            i8 = self.asi8

            # quick check
            if len(i8) and self.is_monotonic:
                if i8[0] != tslib.iNaT:
                    return self._box_func(i8[0])

            if self.hasnans:
                mask = i8 == tslib.iNaT
                min_stamp = self[~mask].asi8.min()
            else:
                min_stamp = i8.min()
            return self._box_func(min_stamp)
        except ValueError:
            return self._na_value

    def argmin(self, axis=None):
        """
        return a ndarray of the minimum argument indexer

        See also
        --------
        numpy.ndarray.argmin
        """

        i8 = self.asi8
        if self.hasnans:
            mask = i8 == tslib.iNaT
            if mask.all():
                return -1
            i8 = i8.copy()
            i8[mask] = np.iinfo('int64').max
        return i8.argmin()

    def max(self, axis=None):
        """
        return the maximum value of the Index

        See also
        --------
        numpy.ndarray.max
        """
        try:
            i8 = self.asi8

            # quick check
            if len(i8) and self.is_monotonic:
                if i8[-1] != tslib.iNaT:
                    return self._box_func(i8[-1])

            if self.hasnans:
                mask = i8 == tslib.iNaT
                max_stamp = self[~mask].asi8.max()
            else:
                max_stamp = i8.max()
            return self._box_func(max_stamp)
        except ValueError:
            return self._na_value

    def argmax(self, axis=None):
        """
        return a ndarray of the maximum argument indexer

        See also
        --------
        numpy.ndarray.argmax
        """

        i8 = self.asi8
        if self.hasnans:
            mask = i8 == tslib.iNaT
            if mask.all():
                return -1
            i8 = i8.copy()
            i8[mask] = 0
        return i8.argmax()

    @property
    def _formatter_func(self):
        """
        Format function to convert value to representation
        """
        return str

    def _format_footer(self):
        tagline = 'Length: %d, Freq: %s, Timezone: %s'
        return tagline % (len(self), self.freqstr, self.tz)

    def __unicode__(self):
        formatter = self._formatter_func
        summary = str(self.__class__) + '\n'

        n = len(self)
        if n == 0:
            pass
        elif n == 1:
            first = formatter(self[0])
            summary += '[%s]\n' % first
        elif n == 2:
            first = formatter(self[0])
            last = formatter(self[-1])
            summary += '[%s, %s]\n' % (first, last)
        else:
            first = formatter(self[0])
            last = formatter(self[-1])
            summary += '[%s, ..., %s]\n' % (first, last)

        summary += self._format_footer()
        return summary

    @cache_readonly
    def _resolution(self):
        from pandas.tseries.frequencies import Resolution
        return Resolution.get_reso_from_freq(self.freqstr)

    @cache_readonly
    def resolution(self):
        """
        Returns day, hour, minute, second, millisecond or microsecond
        """
        from pandas.tseries.frequencies import get_reso_string
        return get_reso_string(self._resolution)

    def __add__(self, other):
        from pandas.core.index import Index
        from pandas.tseries.offsets import DateOffset
        if isinstance(other, Index):
            return self.union(other)
        elif isinstance(other, (DateOffset, datetime.timedelta, np.timedelta64)):
            return self._add_delta(other)
        elif com.is_integer(other):
            return self.shift(other)
        else:  # pragma: no cover
            return NotImplemented

    def __sub__(self, other):
        from pandas.core.index import Index
        from pandas.tseries.offsets import DateOffset
        if isinstance(other, Index):
            return self.diff(other)
        elif isinstance(other, (DateOffset, datetime.timedelta, np.timedelta64)):
            return self._add_delta(-other)
        elif com.is_integer(other):
            return self.shift(-other)
        else:  # pragma: no cover
            return NotImplemented

    __iadd__ = __add__
    __isub__ = __sub__

    def _add_delta(self, other):
        return NotImplemented

    def unique(self):
        """
        Index.unique with handling for DatetimeIndex/PeriodIndex metadata

        Returns
        -------
        result : DatetimeIndex or PeriodIndex
        """
        from pandas.core.index import Int64Index
        result = Int64Index.unique(self)
        return self._simple_new(result, name=self.name, freq=self.freq,
                                tz=getattr(self, 'tz', None))

