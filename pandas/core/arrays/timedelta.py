# -*- coding: utf-8 -*-
from datetime import timedelta

import numpy as np

from pandas._libs import tslibs, lib
from pandas._libs.tslibs import Timedelta, NaT
from pandas._libs.tslibs.fields import get_timedelta_field
from pandas._libs.tslibs.timedeltas import array_to_timedelta64

from pandas import compat

from pandas.core.dtypes.common import (
    _TD_DTYPE, _ensure_int64, is_timedelta64_dtype)
from pandas.core.dtypes.generic import ABCSeries
from pandas.core.dtypes.missing import isna

import pandas.core.common as com

from pandas.tseries.offsets import Tick, DateOffset
from pandas.tseries.frequencies import to_offset

from .datetimelike import DatetimeLikeArrayMixin


def _is_convertible_to_td(key):
    return isinstance(key, (Tick, timedelta,
                            np.timedelta64, compat.string_types))


def _field_accessor(name, alias, docstring=None):
    def f(self):
        values = self.asi8
        result = get_timedelta_field(values, alias)
        if self.hasnans:
            result = self._maybe_mask_results(result, convert='float64')

        return result

    f.__name__ = name
    f.__doc__ = docstring
    return property(f)


class TimedeltaArrayMixin(DatetimeLikeArrayMixin):
    @property
    def _box_func(self):
        return lambda x: Timedelta(x, unit='ns')

    @property
    def dtype(self):
        return _TD_DTYPE

    # ----------------------------------------------------------------
    # Constructors
    _attributes = ["freq"]

    @classmethod
    def _simple_new(cls, values, freq=None, **kwargs):
        values = np.array(values, copy=False)
        if values.dtype == np.object_:
            values = array_to_timedelta64(values)
        if values.dtype != _TD_DTYPE:
            if is_timedelta64_dtype(values):
                # non-nano unit
                values = values.astype(_TD_DTYPE)
            else:
                values = _ensure_int64(values).view(_TD_DTYPE)

        result = object.__new__(cls)
        result._data = values
        result._freq = freq
        return result

    def __new__(cls, values, freq=None, start=None, end=None, periods=None,
                closed=None):
        if (freq is not None and not isinstance(freq, DateOffset) and
                freq != 'infer'):
            freq = to_offset(freq)

        if periods is not None:
            if lib.is_float(periods):
                periods = int(periods)
            elif not lib.is_integer(periods):
                raise TypeError('`periods` must be a number, got {periods}'
                                .format(periods=periods))

        if values is None:
            if freq is None and com._any_none(periods, start, end):
                raise ValueError('Must provide freq argument if no data is '
                                 'supplied')
            else:
                return cls._generate(start, end, periods, freq,
                                     closed=closed)

        result = cls._simple_new(values, freq=freq)
        if freq == 'infer':
            inferred = result.inferred_freq
            if inferred:
                result._freq = to_offset(inferred)

        return result

    @classmethod
    def _generate(cls, start, end, periods, freq, closed=None, **kwargs):
        # **kwargs are for compat with TimedeltaIndex, which includes `name`
        if com._count_not_none(start, end, periods, freq) != 3:
            raise ValueError('Of the four parameters: start, end, periods, '
                             'and freq, exactly three must be specified')

        if start is not None:
            start = Timedelta(start)

        if end is not None:
            end = Timedelta(end)

        left_closed = False
        right_closed = False

        if start is None and end is None:
            if closed is not None:
                raise ValueError("Closed has to be None if not both of start"
                                 "and end are defined")

        if closed is None:
            left_closed = True
            right_closed = True
        elif closed == "left":
            left_closed = True
        elif closed == "right":
            right_closed = True
        else:
            raise ValueError("Closed has to be either 'left', 'right' or None")

        if freq is not None:
            index = _generate_regular_range(start, end, periods, freq)
            index = cls._simple_new(index, freq=freq, **kwargs)
        else:
            index = np.linspace(start.value, end.value, periods).astype('i8')
            # TODO: shouldn't we pass `name` here?  (via **kwargs)
            index = cls._simple_new(index, freq=freq)

        if not left_closed:
            index = index[1:]
        if not right_closed:
            index = index[:-1]

        return index

    # ----------------------------------------------------------------
    # Arithmetic Methods

    def _add_offset(self, other):
        assert not isinstance(other, Tick)
        raise TypeError("cannot add the type {typ} to a {cls}"
                        .format(typ=type(other).__name__,
                                cls=type(self).__name__))

    def _sub_datelike(self, other):
        assert other is not NaT
        raise TypeError("cannot subtract a datelike from a {cls}"
                        .format(cls=type(self).__name__))

    def _add_delta(self, delta):
        """
        Add a timedelta-like, Tick, or TimedeltaIndex-like object
        to self.

        Parameters
        ----------
        delta : timedelta, np.timedelta64, Tick, TimedeltaArray, TimedeltaIndex

        Returns
        -------
        result : same type as self

        Notes
        -----
        The result's name is set outside of _add_delta by the calling
        method (__add__ or __sub__)
        """
        if isinstance(delta, (Tick, timedelta, np.timedelta64)):
            new_values = self._add_delta_td(delta)
        elif isinstance(delta, TimedeltaArrayMixin):
            new_values = self._add_delta_tdi(delta)
        elif is_timedelta64_dtype(delta):
            # ndarray[timedelta64] --> wrap in TimedeltaArray/Index
            delta = type(self)(delta)
            new_values = self._add_delta_tdi(delta)
        else:
            raise TypeError("cannot add the type {0} to a TimedeltaIndex"
                            .format(type(delta)))

        return type(self)(new_values, freq='infer')

    def _evaluate_with_timedelta_like(self, other, op):
        if isinstance(other, ABCSeries):
            # GH#19042
            return NotImplemented

        opstr = '__{opname}__'.format(opname=op.__name__).replace('__r', '__')
        # allow division by a timedelta
        if opstr in ['__div__', '__truediv__', '__floordiv__']:
            if _is_convertible_to_td(other):
                other = Timedelta(other)
                if isna(other):
                    raise NotImplementedError(
                        "division by pd.NaT not implemented")

                i8 = self.asi8
                left, right = i8, other.value

                if opstr in ['__floordiv__']:
                    result = op(left, right)
                else:
                    result = op(left, np.float64(right))
                result = self._maybe_mask_results(result, convert='float64')
                return result

        return NotImplemented

    # ----------------------------------------------------------------
    # Conversion Methods - Vectorized analogues of Timedelta methods

    def total_seconds(self):
        """
        Return total duration of each element expressed in seconds.

        This method is available directly on TimedeltaArray, TimedeltaIndex
        and on Series containing timedelta values under the ``.dt`` namespace.

        Returns
        -------
        seconds : [ndarray, Float64Index, Series]
            When the calling object is a TimedeltaArray, the return type
            is ndarray.  When the calling object is a TimedeltaIndex,
            the return type is a Float64Index. When the calling object
            is a Series, the return type is Series of type `float64` whose
            index is the same as the original.

        See Also
        --------
        datetime.timedelta.total_seconds : Standard library version
            of this method.
        TimedeltaIndex.components : Return a DataFrame with components of
            each Timedelta.

        Examples
        --------
        **Series**

        >>> s = pd.Series(pd.to_timedelta(np.arange(5), unit='d'))
        >>> s
        0   0 days
        1   1 days
        2   2 days
        3   3 days
        4   4 days
        dtype: timedelta64[ns]

        >>> s.dt.total_seconds()
        0         0.0
        1     86400.0
        2    172800.0
        3    259200.0
        4    345600.0
        dtype: float64

        **TimedeltaIndex**

        >>> idx = pd.to_timedelta(np.arange(5), unit='d')
        >>> idx
        TimedeltaIndex(['0 days', '1 days', '2 days', '3 days', '4 days'],
                       dtype='timedelta64[ns]', freq=None)

        >>> idx.total_seconds()
        Float64Index([0.0, 86400.0, 172800.0, 259200.00000000003, 345600.0],
                     dtype='float64')
        """
        return self._maybe_mask_results(1e-9 * self.asi8)

    def to_pytimedelta(self):
        """
        Return Timedelta Array/Index as object ndarray of datetime.timedelta
        objects

        Returns
        -------
        datetimes : ndarray
        """
        return tslibs.ints_to_pytimedelta(self.asi8)

    days = _field_accessor("days", "days",
                           " Number of days for each element. ")
    seconds = _field_accessor("seconds", "seconds",
                              " Number of seconds (>= 0 and less than 1 day) "
                              "for each element. ")
    microseconds = _field_accessor("microseconds", "microseconds",
                                   "\nNumber of microseconds (>= 0 and less "
                                   "than 1 second) for each\nelement. ")
    nanoseconds = _field_accessor("nanoseconds", "nanoseconds",
                                  "\nNumber of nanoseconds (>= 0 and less "
                                  "than 1 microsecond) for each\nelement.\n")

    @property
    def components(self):
        """
        Return a dataframe of the components (days, hours, minutes,
        seconds, milliseconds, microseconds, nanoseconds) of the Timedeltas.

        Returns
        -------
        a DataFrame
        """
        from pandas import DataFrame

        columns = ['days', 'hours', 'minutes', 'seconds',
                   'milliseconds', 'microseconds', 'nanoseconds']
        hasnans = self.hasnans
        if hasnans:
            def f(x):
                if isna(x):
                    return [np.nan] * len(columns)
                return x.components
        else:
            def f(x):
                return x.components

        result = DataFrame([f(x) for x in self], columns=columns)
        if not hasnans:
            result = result.astype('int64')
        return result


# ---------------------------------------------------------------------
# Constructor Helpers

def _generate_regular_range(start, end, periods, offset):
    stride = offset.nanos
    if periods is None:
        b = Timedelta(start).value
        e = Timedelta(end).value
        e += stride - e % stride
    elif start is not None:
        b = Timedelta(start).value
        e = b + periods * stride
    elif end is not None:
        e = Timedelta(end).value + stride
        b = e - periods * stride
    else:
        raise ValueError("at least 'start' or 'end' should be specified "
                         "if a 'period' is given.")

    data = np.arange(b, e, stride, dtype=np.int64)
    return data
