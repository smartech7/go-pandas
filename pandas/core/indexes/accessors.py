"""
datetimelike delegation
"""

import numpy as np

from pandas.core.dtypes.generic import ABCSeries
from pandas.core.dtypes.common import (
    is_period_arraylike,
    is_datetime_arraylike, is_integer_dtype,
    is_datetime64_dtype, is_datetime64tz_dtype,
    is_timedelta64_dtype, is_categorical_dtype,
    is_list_like)

from pandas.core.accessor import PandasDelegate
from pandas.core.base import NoNewAttributesMixin, PandasObject
from pandas.core.indexes.datetimes import DatetimeIndex
from pandas._libs.tslibs.period import IncompatibleFrequency  # noqa
from pandas.core.indexes.period import PeriodIndex
from pandas.core.indexes.timedeltas import TimedeltaIndex
from pandas.core.algorithms import take_1d


class Properties(PandasDelegate, PandasObject, NoNewAttributesMixin):

    def __init__(self, data, orig):
        if not isinstance(data, ABCSeries):
            raise TypeError("cannot convert an object of type {0} to a "
                            "datetimelike index".format(type(data)))

        self.values = data
        self.orig = orig
        self.name = getattr(data, 'name', None)
        self.index = getattr(data, 'index', None)
        self._freeze()

    def _get_values(self):
        data = self.values
        if is_datetime64_dtype(data.dtype):
            return DatetimeIndex(data, copy=False, name=self.name)

        elif is_datetime64tz_dtype(data.dtype):
            return DatetimeIndex(data, copy=False, name=self.name)

        elif is_timedelta64_dtype(data.dtype):
            return TimedeltaIndex(data, copy=False, name=self.name)

        else:
            if is_period_arraylike(data):
                return PeriodIndex(data, copy=False, name=self.name)
            if is_datetime_arraylike(data):
                return DatetimeIndex(data, copy=False, name=self.name)

        raise TypeError("cannot convert an object of type {0} to a "
                        "datetimelike index".format(type(data)))

    def _delegate_property_get(self, name):
        from pandas import Series
        values = self._get_values()

        result = getattr(values, name)

        # maybe need to upcast (ints)
        if isinstance(result, np.ndarray):
            if is_integer_dtype(result):
                result = result.astype('int64')
        elif not is_list_like(result):
            return result

        result = np.asarray(result)

        # blow up if we operate on categories
        if self.orig is not None:
            result = take_1d(result, self.orig.cat.codes)
            index = self.orig.index
        else:
            index = self.index

        # return the result as a Series, which is by definition a copy
        result = Series(result, index=index, name=self.name)

        # setting this object will show a SettingWithCopyWarning/Error
        result._is_copy = ("modifications to a property of a datetimelike "
                           "object are not supported and are discarded. "
                           "Change values on the original.")

        return result

    def _delegate_property_set(self, name, value, *args, **kwargs):
        raise ValueError("modifications to a property of a datetimelike "
                         "object are not supported. Change values on the "
                         "original.")

    def _delegate_method(self, name, *args, **kwargs):
        from pandas import Series
        values = self._get_values()

        method = getattr(values, name)
        result = method(*args, **kwargs)

        if not is_list_like(result):
            return result

        result = Series(result, index=self.index, name=self.name)

        # setting this object will show a SettingWithCopyWarning/Error
        result._is_copy = ("modifications to a method of a datetimelike "
                           "object are not supported and are discarded. "
                           "Change values on the original.")

        return result


class DatetimeProperties(Properties):
    """
    Accessor object for datetimelike properties of the Series values.

    Examples
    --------
    >>> s.dt.hour
    >>> s.dt.second
    >>> s.dt.quarter

    Returns a Series indexed like the original Series.
    Raises TypeError if the Series does not contain datetimelike values.
    """

    def to_pydatetime(self):
        return self._get_values().to_pydatetime()

    @property
    def freq(self):
        return self._get_values().inferred_freq


DatetimeProperties._add_delegate_accessors(
    delegate=DatetimeIndex,
    accessors=DatetimeIndex._datetimelike_ops,
    typ='property')
DatetimeProperties._add_delegate_accessors(
    delegate=DatetimeIndex,
    accessors=DatetimeIndex._datetimelike_methods,
    typ='method')


class TimedeltaProperties(Properties):
    """
    Accessor object for datetimelike properties of the Series values.

    Examples
    --------
    >>> s.dt.hours
    >>> s.dt.seconds

    Returns a Series indexed like the original Series.
    Raises TypeError if the Series does not contain datetimelike values.
    """

    def to_pytimedelta(self):
        return self._get_values().to_pytimedelta()

    @property
    def components(self):
        """
        Return a dataframe of the components (days, hours, minutes,
        seconds, milliseconds, microseconds, nanoseconds) of the Timedeltas.

        Returns
        -------
        a DataFrame

        """
        return self._get_values().components.set_index(self.index)

    @property
    def freq(self):
        return self._get_values().inferred_freq


TimedeltaProperties._add_delegate_accessors(
    delegate=TimedeltaIndex,
    accessors=TimedeltaIndex._datetimelike_ops,
    typ='property')
TimedeltaProperties._add_delegate_accessors(
    delegate=TimedeltaIndex,
    accessors=TimedeltaIndex._datetimelike_methods,
    typ='method')


class PeriodProperties(Properties):
    """
    Accessor object for datetimelike properties of the Series values.

    Examples
    --------
    >>> s.dt.hour
    >>> s.dt.second
    >>> s.dt.quarter

    Returns a Series indexed like the original Series.
    Raises TypeError if the Series does not contain datetimelike values.
    """


PeriodProperties._add_delegate_accessors(
    delegate=PeriodIndex,
    accessors=PeriodIndex._datetimelike_ops,
    typ='property')
PeriodProperties._add_delegate_accessors(
    delegate=PeriodIndex,
    accessors=PeriodIndex._datetimelike_methods,
    typ='method')


class CombinedDatetimelikeProperties(DatetimeProperties, TimedeltaProperties):

    def __new__(cls, data):
        # CombinedDatetimelikeProperties isn't really instantiated. Instead
        # we need to choose which parent (datetime or timedelta) is
        # appropriate. Since we're checking the dtypes anyway, we'll just
        # do all the validation here.
        from pandas import Series

        if not isinstance(data, Series):
            raise TypeError("cannot convert an object of type {0} to a "
                            "datetimelike index".format(type(data)))

        orig = data if is_categorical_dtype(data) else None
        if orig is not None:
            data = Series(orig.values.categories,
                          name=orig.name,
                          copy=False)

        try:
            if is_datetime64_dtype(data.dtype):
                return DatetimeProperties(data, orig)
            elif is_datetime64tz_dtype(data.dtype):
                return DatetimeProperties(data, orig)
            elif is_timedelta64_dtype(data.dtype):
                return TimedeltaProperties(data, orig)
            else:
                if is_period_arraylike(data):
                    return PeriodProperties(data, orig)
                if is_datetime_arraylike(data):
                    return DatetimeProperties(data, orig)
        except Exception:
            pass  # we raise an attribute error anyway

        raise AttributeError("Can only use .dt accessor with datetimelike "
                             "values")
