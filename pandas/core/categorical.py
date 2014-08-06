# pylint: disable=E1101,W0232

import numpy as np
from warnings import warn

from pandas import compat
from pandas.compat import u

from pandas.core.algorithms import factorize, unique
from pandas.core.base import PandasObject
from pandas.core.index import Index, _ensure_index
from pandas.core.indexing import _is_null_slice
from pandas.tseries.period import PeriodIndex
import pandas.core.common as com
from pandas.util.terminal import get_terminal_size
from pandas.core.config import get_option
from pandas.core import format as fmt

def _cat_compare_op(op):
    def f(self, other):
        if isinstance(other, (Categorical, np.ndarray)):
            values = np.asarray(self)
            f = getattr(values, op)
            return f(np.asarray(other))
        else:
            if other in self.levels:
                i = self.levels.get_loc(other)
                return getattr(self._codes, op)(i)
            else:
                return np.repeat(False, len(self))

    f.__name__ = op

    return f

def _is_categorical(array):
    """ return if we are a categorical possibility """
    return isinstance(array, Categorical) or isinstance(array.dtype, com.CategoricalDtype)

def _maybe_to_categorical(array):
    """ coerce to a categorical if a series is given """
    if isinstance(array, com.ABCSeries):
        return array.values
    return array


_codes_doc = """The level codes of this categorical.

Level codes are an array if integer which are the positions of the real
values in the levels array.

There is not setter, used the other categorical methods and the item setter on
Categorical to change values in the categorical.
"""

_levels_doc = """The levels of this categorical.

Setting assigns new values to each level (effectively a rename of
each individual level).

The assigned value has to be a list-like object. If the number of
level-items is less than number of level-items in the current level,
all level-items at a higher position are set to NaN. If the number of
level-items is more that the current number of level-items, new
(unused) levels are added at the end.

To add level-items in between, use `reorder_levels`.

Raises
------
ValueError
    If the new levels do not validate as levels

See also
--------
Categorical.reorder_levels
Categorical.remove_unused_levels
"""
class Categorical(PandasObject):

    """
    Represents a categorical variable in classic R / S-plus fashion

    `Categoricals` can only take on only a limited, and usually fixed, number
    of possible values (`levels`). In contrast to statistical categorical
    variables, a `Categorical` might have an order, but numerical operations
    (additions, divisions, ...) are not possible.

    All values of the `Categorical` are either in `levels` or `np.nan`.
    Assigning values outside of `levels` will raise a `ValueError`. Order is
    defined by the order of the `levels`, not lexical order of the values.

    Parameters
    ----------
    values : list-like
        The values of the categorical. If levels are given, values not in levels will
        be replaced with NaN.
    levels : Index-like (unique), optional
        The unique levels for this categorical. If not given, the levels are assumed
        to be the unique values of values.
    ordered : boolean, optional
        Whether or not this categorical is treated as a ordered categorical. If not given,
        the resulting categorical will be ordered if values can be sorted.
    name : str, optional
        Name for the Categorical variable. If name is None, will attempt
        to infer from values.
    compat : boolean, default=False
        Whether to treat values as codes to the levels (old API, deprecated)

    Attributes
    ----------
    levels : ndarray
        The levels of this categorical
    codes : Index
        The codes (integer positions, which point to the levels) of this categorical, read only
    ordered : boolean
        Whether or not this Categorical is ordered
    name : string
        The name of this Categorical

    Raises
    ------
    ValueError
        If the levels do not validate
    TypeError
        If an explicit ``ordered=True`` is given but no `levels` and the `values` are not sortable


    Examples
    --------
    >>> from pandas import Categorical
    >>> Categorical([1, 2, 3, 1, 2, 3])
    1
    2
    3
    1
    2
    3
    Levels (3): Int64Index([1, 2, 3], dtype=int64), ordered

    >>> Categorical(['a', 'b', 'c', 'a', 'b', 'c'])
    a
    b
    c
    a
    b
    c
    Levels (3): Index(['a', 'b', 'c'], dtype=object), ordered

    >>> a = Categorical(['a','b','c','a','b','c'], ['c', 'b', 'a'])
    >>> a.min()
    'c'
    """
    ndim = 1
    """Number of dimensions (always 1!)"""

    dtype = com.CategoricalDtype()
    """The dtype (always "category")"""

    ordered = None
    """Whether or not this Categorical is ordered.

    Only ordered `Categoricals` can be sorted (according to the order
    of the levels) and have a min and max value.

    See also
    --------
    Categorical.sort
    Categorical.order
    Categorical.min
    Categorical.max
    """

    def __init__(self, values, levels=None, ordered=None, name=None, fastpath=False, compat=False):

        if fastpath:
            # fast path
            self._codes = values
            self.name = name
            self.levels = levels
            self.ordered = ordered
            return

        if name is None:
            name = getattr(values, 'name', None)

        # sanitize input
        if com.is_categorical_dtype(values):

            # we are either a Series or a Categorical
            cat = values
            if isinstance(values, com.ABCSeries):
                cat = values.values
            if levels is None:
                levels = cat.levels
            if ordered is None:
                ordered = cat.ordered
            values = values.__array__()

        elif isinstance(values, Index):
            pass

        else:

            # on numpy < 1.6 datetimelike get inferred to all i8 by _sanitize_array
            # which is fine, but since factorize does this correctly no need here
            # this is an issue because _sanitize_array also coerces np.nan to a string
            # under certain versions of numpy as well
            inferred = com._possibly_infer_to_datetimelike(values)
            if not isinstance(inferred, np.ndarray):
                from pandas.core.series import _sanitize_array
                values = _sanitize_array(values, None)

        if levels is None:
            try:
                codes, levels = factorize(values, sort=True)
                # If the underlying data structure was sortable, and the user doesn't want to
                # "forget" this order, the categorical also is sorted/ordered
                if ordered is None:
                    ordered = True
            except TypeError:
                codes, levels = factorize(values, sort=False)
                if ordered:
                    # raise, as we don't have a sortable data structure and so the usershould
                    # give us one by specifying levels
                    raise TypeError("'values' is not ordered, please explicitly specify the level "
                                    "order by passing in a level argument.")
        else:
            # there are two ways if levels are present
            # the old one, where each value is a int pointer to the levels array
            # the new one, where each value is also in the level array (or np.nan)

            # make sure that we always have the same type here, no matter what we get passed in
            levels = self._validate_levels(levels)

            # There can be two ways: the old which passed in codes and levels directly
            # and values have to be inferred and the new  one, which passes in values and levels
            # and _codes have to be inferred.

            # min and max can be higher and lower if not all levels are in the values
            if compat and (com.is_integer_dtype(values) and
                               (np.min(values) >= -1) and (np.max(values) < len(levels))):
                warn("Using 'values' as codes is deprecated.\n"
                     "'Categorical(... , compat=True)' is only there for historical reasons and "
                     "should not be used in new code!\n"
                     "See https://github.com/pydata/pandas/pull/7217", FutureWarning)
                codes = values
            else:
                codes = _get_codes_for_values(values, levels)

                # if we got levels, we can assume that the order is intended
                # if ordered is unspecified
                if ordered is None:
                    ordered = True

        self.ordered = False if ordered is None else ordered
        self._codes = codes
        self.levels = levels
        self.name = name

    def copy(self):
        """ Copy constructor. """
        return Categorical(values=self._codes.copy(),levels=self.levels,
                           name=self.name, ordered=self.ordered, fastpath=True)

    @classmethod
    def from_array(cls, data):
        """
        Make a Categorical type from a single array-like object.

        Parameters
        ----------
        data : array-like
            Can be an Index or array-like. The levels are assumed to be
            the unique values of `data`.
        """
        return Categorical(data)

    @classmethod
    def from_codes(cls, codes, levels, ordered=True, name=None):
        """
        Make a Categorical type from codes and levels arrays.

        This constructor is useful if you already have codes and levels and so do not need the
        (computation intensive) factorization step, which is usually done on the constructor.

        If your data does not follow this convention, please use the normal constructor.

        Parameters
        ----------
        codes : array-like, integers
            An integer array, where each integer points to a level in levels or -1 for NaN
        levels : index-like
            The levels for the categorical. Items need to be unique.
        ordered : boolean, optional
            Whether or not this categorical is treated as a ordered categorical. If not given,
            the resulting categorical will be ordered.
        name : str, optional
            Name for the Categorical variable.
        """
        try:
            codes = np.asarray(codes, np.int64)
        except:
            raise ValueError("codes need to be convertible to an arrays of integers")

        levels = cls._validate_levels(levels)

        if codes.max() >= len(levels) or codes.min() < -1:
            raise ValueError("codes need to be between -1 and len(levels)-1")


        return Categorical(codes, levels=levels, ordered=ordered, name=name, fastpath=True)

    _codes = None

    def _get_codes(self):
        """ Get the level codes.

        Returns
        -------
        codes : integer array view
            A non writable view of the `codes` array.
        """
        v = self._codes.view()
        v.flags.writeable = False
        return v

    def _set_codes(self, codes):
        """
        Not settable by the user directly
        """
        raise ValueError("cannot set Categorical codes directly")

    codes = property(fget=_get_codes, fset=_set_codes, doc=_codes_doc)

    _levels = None

    @classmethod
    def _validate_levels(cls, levels):
        """" Validates that we have good levels """
        levels = _ensure_index(levels)
        if not levels.is_unique:
            raise ValueError('Categorical levels must be unique')
        return levels

    def _set_levels(self, levels):
        """ Sets new levels """
        levels = self._validate_levels(levels)

        if not self._levels is None and len(levels) < len(self._levels):
            # remove all _codes which are larger
            self._codes[self._codes >= len(levels)] = -1
        self._levels = levels

    def _get_levels(self):
        """ Gets the levels """
        # levels is an Index, which is immutable -> no need to copy
        return self._levels

    levels = property(fget=_get_levels, fset=_set_levels, doc=_levels_doc)

    def reorder_levels(self, new_levels, ordered=None):
        """ Reorders levels as specified in new_levels.

        `new_levels` must include all old levels but can also include new level items. In
        contrast to assigning to `levels`, these new level items can be in arbitrary positions.

        The level reordering is done inplace.

        Raises
        ------
        ValueError
            If the new levels do not contain all old level items

        Parameters
        ----------
        new_levels : Index-like
           The levels in new order. must be of same length as the old levels
        ordered : boolean, optional
           Whether or not the categorical is treated as a ordered categorical. If not given,
           do not change the ordered information.
        """
        new_levels = self._validate_levels(new_levels)

        if len(new_levels) < len(self._levels) or len(self._levels-new_levels):
            raise ValueError('Reordered levels must include all original levels')
        values = self.__array__()
        self._codes = _get_codes_for_values(values, new_levels)
        self._levels = new_levels
        if not ordered is None:
            self.ordered = ordered

    def remove_unused_levels(self):
        """ Removes levels which are not used.

        The level removal is done inplace.
        """
        _used = sorted(np.unique(self._codes))
        new_levels = self.levels.take(_used)
        new_levels = _ensure_index(new_levels)
        self._codes = _get_codes_for_values(self.__array__(), new_levels)
        self._levels = new_levels


    __eq__ = _cat_compare_op('__eq__')
    __ne__ = _cat_compare_op('__ne__')
    __lt__ = _cat_compare_op('__lt__')
    __gt__ = _cat_compare_op('__gt__')
    __le__ = _cat_compare_op('__le__')
    __ge__ = _cat_compare_op('__ge__')

    # for Series/ndarray like compat
    @property
    def shape(self):
        """ Shape of the Categorical.

        For internal compatibility with numpy arrays.

        Returns
        -------
        shape : tuple
        """

        return tuple([len(self._codes)])

    def __array__(self, dtype=None):
        """ The numpy array interface.

        Returns
        -------
        values : numpy array
            A numpy array of the same dtype as categorical.levels.dtype
        """
        return com.take_1d(self.levels.values, self._codes)

    @property
    def T(self):
        return self

    def get_values(self):
        """ Return the values.

        For internal compatibility with pandas formatting.

        Returns
        -------
        values : numpy array
            A numpy array of the same dtype as categorical.levels.dtype or dtype string if periods
        """

        # if we are a period index, return a string repr
        if isinstance(self.levels, PeriodIndex):
            return com.take_1d(np.array(self.levels.to_native_types(), dtype=object),
                               self._codes)

        return np.array(self)

    def argsort(self, ascending=True, **kwargs):
        """ Implements ndarray.argsort.

        For internal compatibility with numpy arrays.

        Only ordered Categoricals can be argsorted!

        Returns
        -------
        argsorted : numpy array
        """
        if not self.ordered:
            raise TypeError("Categorical not ordered")
        result = np.argsort(self._codes.copy(), **kwargs)
        if not ascending:
            result = result[::-1]
        return result

    def order(self, inplace=False, ascending=True, na_position='last', **kwargs):
        """ Sorts the Category by level value returning a new Categorical by default.

        Only ordered Categoricals can be sorted!

        Categorical.sort is the equivalent but sorts the Categorical inplace.

        Parameters
        ----------
        ascending : boolean, default True
            Sort ascending. Passing False sorts descending
        inplace : boolean, default False
            Do operation in place.
        na_position : {'first', 'last'} (optional, default='last')
            'first' puts NaNs at the beginning
            'last' puts NaNs at the end

        Returns
        -------
        y : Category or None

        See Also
        --------
        Category.sort
        """
        if not self.ordered:
            raise TypeError("Categorical not ordered")
        if na_position not in ['last','first']:
            raise ValueError('invalid na_position: {!r}'.format(na_position))

        codes = np.sort(self._codes.copy())
        if not ascending:
            codes = codes[::-1]

        if inplace:
            self._codes = codes
            return
        else:
            return Categorical(values=codes,levels=self.levels, ordered=self.ordered,
                               name=self.name, fastpath=True)


    def sort(self, inplace=True, ascending=True, na_position='last', **kwargs):
        """ Sorts the Category inplace by level value.

        Only ordered Categoricals can be sorted!

        Catgorical.order is the equivalent but returns a new Categorical.

        Parameters
        ----------
        ascending : boolean, default True
            Sort ascending. Passing False sorts descending
        inplace : boolean, default False
            Do operation in place.
        na_position : {'first', 'last'} (optional, default='last')
            'first' puts NaNs at the beginning
            'last' puts NaNs at the end

        Returns
        -------
        y : Category or None

        See Also
        --------
        Category.order
        """
        return self.order(inplace=inplace, ascending=ascending, **kwargs)

    def ravel(self, order='C'):
        """ Return a flattened (numpy) array.

        For internal compatibility with numpy arrays.

        Returns
        -------
        raveled : numpy array
        """
        return np.array(self)

    def view(self):
        """Return a view of myself.

        For internal compatibility with numpy arrays.

        Returns
        -------
        view : Categorical
           Returns `self`!
        """
        return self

    def to_dense(self):
        """ Return my 'dense' repr """
        return np.asarray(self)

    def fillna(self, fill_value=None, method=None, limit=None, **kwargs):
        """ Fill NA/NaN values using the specified method.

        Parameters
        ----------
        method : {'backfill', 'bfill', 'pad', 'ffill', None}, default None
            Method to use for filling holes in reindexed Series
            pad / ffill: propagate last valid observation forward to next valid
            backfill / bfill: use NEXT valid observation to fill gap
        value : scalar
            Value to use to fill holes (e.g. 0)
        limit : int, default None
            Maximum size gap to forward or backward fill (not implemented yet!)

        Returns
        -------
        filled : Categorical with NA/NaN filled
        """

        if fill_value is None:
            fill_value = np.nan
        if limit is not None:
            raise NotImplementedError

        values = self._codes

        # pad / bfill
        if method is not None:

            values = self.to_dense().reshape(-1,len(self))
            values = com.interpolate_2d(
                values, method, 0, None, fill_value).astype(self.levels.dtype)[0]
            values = _get_codes_for_values(values, self.levels)

        else:

            if not com.isnull(fill_value) and fill_value not in self.levels:
                raise ValueError("fill value must be in levels")

            mask = self._codes==-1
            if mask.any():
                values = self._codes.copy()
                values[mask] = self.levels.get_loc(fill_value)

        return Categorical(values, levels=self.levels, ordered=self.ordered,
                           name=self.name, fastpath=True)

    def take_nd(self, indexer, allow_fill=True, fill_value=None):
        """ Take the values by the indexer, fill with the fill_value. """
        if allow_fill and fill_value is None:
            fill_value = np.nan

        values = com.take_1d(self._codes, indexer, allow_fill=allow_fill, fill_value=fill_value)
        result = Categorical(values=values, levels=self.levels, ordered=self.ordered,
                             name=self.name, fastpath=True)
        return result

    take = take_nd

    def _slice(self, slicer):
        """ Return a slice of myself. """

        # only allow 1 dimensional slicing, but can
        # in a 2-d case be passd (slice(None),....)
        if isinstance(slicer, tuple) and len(slicer) == 2:
            if not _is_null_slice(slicer[0]):
                raise AssertionError("invalid slicing for a 1-ndim categorical")
            slicer = slicer[1]

        _codes = self._codes[slicer]
        return Categorical(values=_codes,levels=self.levels, ordered=self.ordered,
                           name=self.name, fastpath=True)

    def __len__(self):
        return len(self._codes)

    def __iter__(self):
        return iter(np.array(self))

    def _tidy_repr(self, max_vals=20):
        num = max_vals // 2
        head = self[:num]._get_repr(length=False, name=False, footer=False)
        tail = self[-(max_vals - num):]._get_repr(length=False,
                                                  name=False,
                                                  footer=False)

        result = '%s\n...\n%s' % (head, tail)
        result = '%s\n%s' % (result, self._repr_footer())

        return compat.text_type(result)

    def _repr_level_info(self):
        """ Returns a string representation of the footer."""

        max_levels = (10 if get_option("display.max_levels") == 0
                    else get_option("display.max_levels"))
        level_strs = fmt.format_array(self.levels.get_values(), None)
        if len(level_strs) > max_levels:
            num = max_levels // 2
            head = level_strs[:num]
            tail = level_strs[-(max_levels - num):]
            level_strs = head + ["..."] + tail
        # Strip all leading spaces, which format_array adds for columns...
        level_strs = [x.strip() for x in level_strs]
        levheader = "Levels (%d, %s): " % (len(self.levels),
                                               self.levels.dtype)
        width, height = get_terminal_size()
        max_width = (width if get_option("display.width") == 0
                    else get_option("display.width"))
        if com.in_ipython_frontend():
            # 0 = no breaks
            max_width = 0
        levstring = ""
        start = True
        cur_col_len = len(levheader)
        sep_len, sep = (3, " < ") if self.ordered else (2, ", ")
        for val in level_strs:
            if max_width != 0 and cur_col_len + sep_len + len(val) > max_width:
                levstring += "\n" + (" "* len(levheader))
                cur_col_len = len(levheader)
            if not start:
                levstring += sep
                cur_col_len += len(val)
            levstring += val
            start = False
        # replace to simple save space by
        return levheader + "["+levstring.replace(" < ... < ", " ... ")+"]"

    def _repr_footer(self):

        namestr = "Name: %s, " % self.name if self.name is not None else ""
        return u('%sLength: %d\n%s') % (namestr,
                                       len(self), self._repr_level_info())

    def _get_repr(self, name=False, length=True, na_rep='NaN', footer=True):
        formatter = fmt.CategoricalFormatter(self, name=name,
                                             length=length, na_rep=na_rep,
                                             footer=footer)
        result = formatter.to_string()
        return compat.text_type(result)

    def __unicode__(self):
        """ Unicode representation. """
        width, height = get_terminal_size()
        max_rows = (height if get_option("display.max_rows") == 0
                    else get_option("display.max_rows"))

        if len(self._codes) > (max_rows or 1000):
            result = self._tidy_repr(min(30, max_rows) - 4)
        elif len(self._codes) > 0:
            result = self._get_repr(length=len(self) > 50,
                                    name=True)
        else:
            result = 'Categorical([], %s' % self._get_repr(name=True,
                                                           length=False,
                                                           footer=True,
                                                           ).replace("\n",", ")

        return result

    def __getitem__(self, key):
        """ Return an item. """
        if isinstance(key, (int, np.integer)):
            i = self._codes[key]
            if i == -1:
                return np.nan
            else:
                return self.levels[i]
        else:
            return Categorical(values=self._codes[key], levels=self.levels,
                               ordered=self.ordered, fastpath=True)

    def __setitem__(self, key, value):
        """ Item assignment.


        Raises
        ------
        ValueError
            If (one or more) Value is not in levels or if a assigned `Categorical` has not the
            same levels

        """

        # require identical level set
        if isinstance(value, Categorical):
            if not value.levels.equals(self.levels):
                raise ValueError("cannot set a Categorical with another, without identical levels")

        rvalue = value if com.is_list_like(value) else [value]
        to_add = Index(rvalue)-self.levels
        if len(to_add):
            raise ValueError("cannot setitem on a Categorical with a new level,"
                             " set the levels first")

        # set by position
        if isinstance(key, (int, np.integer)):
            pass

        # tuple of indexers
        elif isinstance(key, tuple):

            # only allow 1 dimensional slicing, but can
            # in a 2-d case be passd (slice(None),....)
            if len(key) == 2:
                if not _is_null_slice(key[0]):
                    raise AssertionError("invalid slicing for a 1-ndim categorical")
                key = key[1]
            elif len(key) == 1:
                key = key[0]
            else:
                raise AssertionError("invalid slicing for a 1-ndim categorical")

        else:
            key = self._codes[key]

        lindexer = self.levels.get_indexer(rvalue)
        self._codes[key] = lindexer

    #### reduction ops ####
    def _reduce(self, op, axis=0, skipna=True, numeric_only=None,
                filter_type=None, name=None, **kwds):
        """ perform the reduction type operation """
        func = getattr(self,name,None)
        if func is None:
            raise TypeError("Categorical cannot perform the operation {op}".format(op=name))
        return func(numeric_only=numeric_only, **kwds)

    def min(self, numeric_only=None, **kwargs):
        """ The minimum value of the object.

        Only ordered `Categoricals` have a minimum!

        Raises
        ------
        TypeError
            If the `Categorical` is not `ordered`.

        Returns
        -------
        min : the minimum of this `Categorical`
        """
        if not self.ordered:
            raise TypeError("Categorical not ordered")
        if numeric_only:
            good = self._codes != -1
            pointer = self._codes[good].min(**kwargs)
        else:
            pointer = self._codes.min(**kwargs)
        if pointer == -1:
            return np.nan
        else:
            return self.levels[pointer]


    def max(self, numeric_only=None, **kwargs):
        """ The maximum value of the object.

        Only ordered `Categoricals` have a maximum!

        Raises
        ------
        TypeError
            If the `Categorical` is not `ordered`.

        Returns
        -------
        max : the maximum of this `Categorical`
        """
        if not self.ordered:
            raise TypeError("Categorical not ordered")
        if numeric_only:
            good = self._codes != -1
            pointer = self._codes[good].max(**kwargs)
        else:
            pointer = self._codes.max(**kwargs)
        if pointer == -1:
            return np.nan
        else:
            return self.levels[pointer]

    def mode(self):
        """
        Returns the mode(s) of the Categorical.

        Empty if nothing occurs at least 2 times.  Always returns `Categorical` even
        if only one value.

        Returns
        -------
        modes : `Categorical` (sorted)
        """

        import pandas.hashtable as htable
        good = self._codes != -1
        result = Categorical(sorted(htable.mode_int64(com._ensure_int64(self._codes[good]))),
                             levels=self.levels,ordered=self.ordered, name=self.name,
                             fastpath=True)
        return result

    def unique(self):
        """
        Return the unique values.

        This includes all levels, even if one or more is unused.

        Returns
        -------
        unique values : array
        """
        return self.levels

    def equals(self, other):
        """
        Returns True if categorical arrays are equal.

        The name of the `Categorical` is not compared!

        Parameters
        ----------
        other : `Categorical`

        Returns
        -------
        are_equal : boolean
        """
        if not isinstance(other, Categorical):
            return False
        # TODO: should this also test if name is equal?
        return (self.levels.equals(other.levels) and self.ordered == other.ordered and
                np.array_equal(self._codes, other._codes))

    def describe(self):
        """ Describes this Categorical

        Returns
        -------
        description: `DataFrame`
            A dataframe with frequency and counts by level.
        """
        # Hack?
        from pandas.core.frame import DataFrame
        counts = DataFrame({
            'codes' : self._codes,
            'values' : self._codes }
                           ).groupby('codes').count()

        counts.index = self.levels.take(counts.index)
        counts = counts.reindex(self.levels)
        freqs = counts / float(counts.sum())

        from pandas.tools.merge import concat
        result = concat([counts,freqs],axis=1)
        result.index.name = 'levels'
        result.columns = ['counts','freqs']
        return result

##### utility routines #####

def _get_codes_for_values(values, levels):
    """"
    utility routine to turn values into codes given the specified levels
    """

    from pandas.core.algorithms import _get_data_algo, _hashtables
    if values.dtype != levels.dtype:
        values = com._ensure_object(values)
        levels = com._ensure_object(levels)
    (hash_klass, vec_klass), vals = _get_data_algo(values, _hashtables)
    t = hash_klass(len(levels))
    t.map_locations(com._values_from_object(levels))
    return com._ensure_platform_int(t.lookup(values))

