# -*- coding: utf-8 -*-
import operator
import warnings

import numpy as np

from pandas._libs import lib, iNaT, NaT
from pandas._libs.tslibs.timedeltas import delta_to_nanoseconds, Timedelta
from pandas._libs.tslibs.period import (
    DIFFERENT_FREQ_INDEX, IncompatibleFrequency)

from pandas.errors import NullFrequencyError, PerformanceWarning
from pandas import compat

from pandas.tseries import frequencies
from pandas.tseries.offsets import Tick

from pandas.core.dtypes.common import (
    needs_i8_conversion,
    is_list_like,
    is_bool_dtype,
    is_period_dtype,
    is_timedelta64_dtype,
    is_object_dtype)
from pandas.core.dtypes.generic import ABCSeries, ABCDataFrame, ABCIndexClass

import pandas.core.common as com
from pandas.core.algorithms import checked_add_with_arr


def _make_comparison_op(op, cls):
    # TODO: share code with indexes.base version?  Main difference is that
    # the block for MultiIndex was removed here.
    def cmp_method(self, other):
        if isinstance(other, ABCDataFrame):
            return NotImplemented

        if isinstance(other, (np.ndarray, ABCIndexClass, ABCSeries)):
            if other.ndim > 0 and len(self) != len(other):
                raise ValueError('Lengths must match to compare')

        if needs_i8_conversion(self) and needs_i8_conversion(other):
            # we may need to directly compare underlying
            # representations
            return self._evaluate_compare(other, op)

        # numpy will show a DeprecationWarning on invalid elementwise
        # comparisons, this will raise in the future
        with warnings.catch_warnings(record=True):
            with np.errstate(all='ignore'):
                result = op(self.values, np.asarray(other))

        return result

    name = '__{name}__'.format(name=op.__name__)
    # TODO: docstring?
    return compat.set_function_name(cmp_method, name, cls)


class AttributesMixin(object):

    @property
    def _attributes(self):
        # Inheriting subclass should implement _attributes as a list of strings
        from pandas.errors import AbstractMethodError
        raise AbstractMethodError(self)

    @classmethod
    def _simple_new(cls, values, **kwargs):
        from pandas.errors import AbstractMethodError
        raise AbstractMethodError(cls)

    def _get_attributes_dict(self):
        """return an attributes dict for my class"""
        return {k: getattr(self, k, None) for k in self._attributes}

    def _shallow_copy(self, values=None, **kwargs):
        if values is None:
            # Note: slightly different from Index implementation which defaults
            # to self.values
            values = self._ndarray_values

        attributes = self._get_attributes_dict()
        attributes.update(kwargs)
        if not len(values) and 'dtype' not in kwargs:
            attributes['dtype'] = self.dtype
        return self._simple_new(values, **attributes)


class DatetimeLikeArrayMixin(AttributesMixin):
    """
    Shared Base/Mixin class for DatetimeArray, TimedeltaArray, PeriodArray

    Assumes that __new__/__init__ defines:
        _data
        _freq

    and that the inheriting class has methods:
        _validate_frequency
    """

    @property
    def _box_func(self):
        """
        box function to get object from internal representation
        """
        raise com.AbstractMethodError(self)

    def _box_values(self, values):
        """
        apply box func to passed values
        """
        return lib.map_infer(values, self._box_func)

    def __iter__(self):
        return (self._box_func(v) for v in self.asi8)

    @property
    def values(self):
        """ return the underlying data as an ndarray """
        return self._data.view(np.ndarray)

    @property
    def asi8(self):
        # do not cache or you'll create a memory leak
        return self.values.view('i8')

    # ------------------------------------------------------------------
    # Array-like Methods

    def __len__(self):
        return len(self._data)

    def __getitem__(self, key):
        """
        This getitem defers to the underlying array, which by-definition can
        only handle list-likes, slices, and integer scalars
        """

        is_int = lib.is_integer(key)
        if lib.is_scalar(key) and not is_int:
            raise IndexError("only integers, slices (`:`), ellipsis (`...`), "
                             "numpy.newaxis (`None`) and integer or boolean "
                             "arrays are valid indices")

        getitem = self._data.__getitem__
        if is_int:
            val = getitem(key)
            return self._box_func(val)

        if com.is_bool_indexer(key):
            key = np.asarray(key)
            if key.all():
                key = slice(0, None, None)
            else:
                key = lib.maybe_booleans_to_slice(key.view(np.uint8))

        attribs = self._get_attributes_dict()

        is_period = is_period_dtype(self)
        if is_period:
            freq = self.freq
        else:
            freq = None
            if isinstance(key, slice):
                if self.freq is not None and key.step is not None:
                    freq = key.step * self.freq
                else:
                    freq = self.freq

        attribs['freq'] = freq

        result = getitem(key)
        if result.ndim > 1:
            # To support MPL which performs slicing with 2 dim
            # even though it only has 1 dim by definition
            if is_period:
                return self._simple_new(result, **attribs)
            return result

        return self._simple_new(result, **attribs)

    def astype(self, dtype, copy=True):
        if is_object_dtype(dtype):
            return self._box_values(self.asi8)
        return super(DatetimeLikeArrayMixin, self).astype(dtype, copy)

    # ------------------------------------------------------------------
    # Null Handling

    @property  # NB: override with cache_readonly in immutable subclasses
    def _isnan(self):
        """ return if each value is nan"""
        return (self.asi8 == iNaT)

    @property  # NB: override with cache_readonly in immutable subclasses
    def hasnans(self):
        """ return if I have any nans; enables various perf speedups """
        return self._isnan.any()

    def _maybe_mask_results(self, result, fill_value=None, convert=None):
        """
        Parameters
        ----------
        result : a ndarray
        convert : string/dtype or None

        Returns
        -------
        result : ndarray with values replace by the fill_value

        mask the result if needed, convert to the provided dtype if its not
        None

        This is an internal routine
        """

        if self.hasnans:
            if convert:
                result = result.astype(convert)
            if fill_value is None:
                fill_value = np.nan
            result[self._isnan] = fill_value
        return result

    def _nat_new(self, box=True):
        """
        Return Array/Index or ndarray filled with NaT which has the same
        length as the caller.

        Parameters
        ----------
        box : boolean, default True
            - If True returns a Array/Index as the same as caller.
            - If False returns ndarray of np.int64.
        """
        result = np.zeros(len(self), dtype=np.int64)
        result.fill(iNaT)
        if not box:
            return result

        attribs = self._get_attributes_dict()
        if not is_period_dtype(self):
            attribs['freq'] = None
        return self._simple_new(result, **attribs)

    # ------------------------------------------------------------------
    # Frequency Properties/Methods

    @property
    def freq(self):
        """Return the frequency object if it is set, otherwise None"""
        return self._freq

    @freq.setter
    def freq(self, value):
        if value is not None:
            value = frequencies.to_offset(value)
            self._validate_frequency(self, value)

        self._freq = value

    @property
    def freqstr(self):
        """
        Return the frequency object as a string if its set, otherwise None
        """
        if self.freq is None:
            return None
        return self.freq.freqstr

    @property  # NB: override with cache_readonly in immutable subclasses
    def inferred_freq(self):
        """
        Tryies to return a string representing a frequency guess,
        generated by infer_freq.  Returns None if it can't autodetect the
        frequency.
        """
        try:
            return frequencies.infer_freq(self)
        except ValueError:
            return None

    @property  # NB: override with cache_readonly in immutable subclasses
    def _resolution(self):
        return frequencies.Resolution.get_reso_from_freq(self.freqstr)

    @property  # NB: override with cache_readonly in immutable subclasses
    def resolution(self):
        """
        Returns day, hour, minute, second, millisecond or microsecond
        """
        return frequencies.Resolution.get_str(self._resolution)

    # ------------------------------------------------------------------
    # Arithmetic Methods

    def _add_datelike(self, other):
        raise TypeError("cannot add {cls} and {typ}"
                        .format(cls=type(self).__name__,
                                typ=type(other).__name__))

    def _sub_datelike(self, other):
        raise com.AbstractMethodError(self)

    def _sub_period(self, other):
        return NotImplemented

    def _add_offset(self, offset):
        raise com.AbstractMethodError(self)

    def _add_delta(self, other):
        return NotImplemented

    def _add_delta_td(self, other):
        """
        Add a delta of a timedeltalike
        return the i8 result view
        """
        inc = delta_to_nanoseconds(other)
        new_values = checked_add_with_arr(self.asi8, inc,
                                          arr_mask=self._isnan).view('i8')
        if self.hasnans:
            new_values[self._isnan] = iNaT
        return new_values.view('i8')

    def _add_delta_tdi(self, other):
        """
        Add a delta of a TimedeltaIndex
        return the i8 result view
        """
        if not len(self) == len(other):
            raise ValueError("cannot add indices of unequal length")

        self_i8 = self.asi8
        other_i8 = other.asi8
        new_values = checked_add_with_arr(self_i8, other_i8,
                                          arr_mask=self._isnan,
                                          b_mask=other._isnan)
        if self.hasnans or other.hasnans:
            mask = (self._isnan) | (other._isnan)
            new_values[mask] = iNaT
        return new_values.view('i8')

    def _add_nat(self):
        """Add pd.NaT to self"""
        if is_period_dtype(self):
            raise TypeError('Cannot add {cls} and {typ}'
                            .format(cls=type(self).__name__,
                                    typ=type(NaT).__name__))

        # GH#19124 pd.NaT is treated like a timedelta for both timedelta
        # and datetime dtypes
        return self._nat_new(box=True)

    def _sub_nat(self):
        """Subtract pd.NaT from self"""
        # GH#19124 Timedelta - datetime is not in general well-defined.
        # We make an exception for pd.NaT, which in this case quacks
        # like a timedelta.
        # For datetime64 dtypes by convention we treat NaT as a datetime, so
        # this subtraction returns a timedelta64 dtype.
        # For period dtype, timedelta64 is a close-enough return dtype.
        result = np.zeros(len(self), dtype=np.int64)
        result.fill(iNaT)
        return result.view('timedelta64[ns]')

    def _sub_period_array(self, other):
        """
        Subtract a Period Array/Index from self.  This is only valid if self
        is itself a Period Array/Index, raises otherwise.  Both objects must
        have the same frequency.

        Parameters
        ----------
        other : PeriodIndex or PeriodArray

        Returns
        -------
        result : np.ndarray[object]
            Array of DateOffset objects; nulls represented by NaT
        """
        if not is_period_dtype(self):
            raise TypeError("cannot subtract {dtype}-dtype to {cls}"
                            .format(dtype=other.dtype,
                                    cls=type(self).__name__))

        if not len(self) == len(other):
            raise ValueError("cannot subtract arrays/indices of "
                             "unequal length")
        if self.freq != other.freq:
            msg = DIFFERENT_FREQ_INDEX.format(self.freqstr, other.freqstr)
            raise IncompatibleFrequency(msg)

        new_values = checked_add_with_arr(self.asi8, -other.asi8,
                                          arr_mask=self._isnan,
                                          b_mask=other._isnan)

        new_values = np.array([self.freq * x for x in new_values])
        if self.hasnans or other.hasnans:
            mask = (self._isnan) | (other._isnan)
            new_values[mask] = NaT
        return new_values

    def _addsub_int_array(self, other, op):
        """
        Add or subtract array-like of integers equivalent to applying
        `shift` pointwise.

        Parameters
        ----------
        other : Index, ExtensionArray, np.ndarray
            integer-dtype
        op : {operator.add, operator.sub}

        Returns
        -------
        result : same class as self
        """
        assert op in [operator.add, operator.sub]
        if is_period_dtype(self):
            # easy case for PeriodIndex
            if op is operator.sub:
                other = -other
            res_values = checked_add_with_arr(self.asi8, other,
                                              arr_mask=self._isnan)
            res_values = res_values.view('i8')
            res_values[self._isnan] = iNaT
            return self._from_ordinals(res_values, freq=self.freq)

        elif self.freq is None:
            # GH#19123
            raise NullFrequencyError("Cannot shift with no freq")

        elif isinstance(self.freq, Tick):
            # easy case where we can convert to timedelta64 operation
            td = Timedelta(self.freq)
            return op(self, td * other)

        # We should only get here with DatetimeIndex; dispatch
        # to _addsub_offset_array
        assert not is_timedelta64_dtype(self)
        return op(self, np.array(other) * self.freq)

    def _addsub_offset_array(self, other, op):
        """
        Add or subtract array-like of DateOffset objects

        Parameters
        ----------
        other : Index, np.ndarray
            object-dtype containing pd.DateOffset objects
        op : {operator.add, operator.sub}

        Returns
        -------
        result : same class as self
        """
        assert op in [operator.add, operator.sub]
        if len(other) == 1:
            return op(self, other[0])

        warnings.warn("Adding/subtracting array of DateOffsets to "
                      "{cls} not vectorized"
                      .format(cls=type(self).__name__), PerformanceWarning)

        res_values = op(self.astype('O').values, np.array(other))
        kwargs = {}
        if not is_period_dtype(self):
            kwargs['freq'] = 'infer'
        return type(self)(res_values, **kwargs)

    # --------------------------------------------------------------
    # Comparison Methods

    def _evaluate_compare(self, other, op):
        """
        We have been called because a comparison between
        8 aware arrays. numpy >= 1.11 will
        now warn about NaT comparisons
        """
        # Called by comparison methods when comparing datetimelike
        # with datetimelike

        if not isinstance(other, type(self)):
            # coerce to a similar object
            if not is_list_like(other):
                # scalar
                other = [other]
            elif lib.is_scalar(lib.item_from_zerodim(other)):
                # ndarray scalar
                other = [other.item()]
            other = type(self)(other)

        # compare
        result = op(self.asi8, other.asi8)

        # technically we could support bool dtyped Index
        # for now just return the indexing array directly
        mask = (self._isnan) | (other._isnan)

        filler = iNaT
        if is_bool_dtype(result):
            filler = False

        result[mask] = filler
        return result

    # TODO: get this from ExtensionOpsMixin
    @classmethod
    def _add_comparison_methods(cls):
        """ add in comparison methods """
        # DatetimeArray and TimedeltaArray comparison methods will
        # call these as their super(...) methods
        cls.__eq__ = _make_comparison_op(operator.eq, cls)
        cls.__ne__ = _make_comparison_op(operator.ne, cls)
        cls.__lt__ = _make_comparison_op(operator.lt, cls)
        cls.__gt__ = _make_comparison_op(operator.gt, cls)
        cls.__le__ = _make_comparison_op(operator.le, cls)
        cls.__ge__ = _make_comparison_op(operator.ge, cls)


DatetimeLikeArrayMixin._add_comparison_methods()


# -------------------------------------------------------------------
# Shared Constructor Helpers

def validate_periods(periods):
    """
    If a `periods` argument is passed to the Datetime/Timedelta Array/Index
    constructor, cast it to an integer.

    Parameters
    ----------
    periods : None, float, int

    Returns
    -------
    periods : None or int

    Raises
    ------
    TypeError
        if periods is None, float, or int
    """
    if periods is not None:
        if lib.is_float(periods):
            periods = int(periods)
        elif not lib.is_integer(periods):
            raise TypeError('periods must be a number, got {periods}'
                            .format(periods=periods))
    return periods
