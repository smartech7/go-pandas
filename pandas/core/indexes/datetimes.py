# pylint: disable=E1101
from __future__ import division
import operator
import warnings
from datetime import time, datetime

import numpy as np
from pytz import utc

from pandas.core.base import _shared_docs

from pandas.core.dtypes.common import (
    _INT64_DTYPE,
    _NS_DTYPE,
    is_datetime64_dtype,
    is_datetimetz,
    is_dtype_equal,
    is_integer,
    is_float,
    is_integer_dtype,
    is_datetime64_ns_dtype,
    is_period_dtype,
    is_bool_dtype,
    is_string_like,
    is_list_like,
    is_scalar,
    pandas_dtype,
    ensure_int64)
from pandas.core.dtypes.generic import ABCSeries
from pandas.core.dtypes.dtypes import DatetimeTZDtype
from pandas.core.dtypes.missing import isna

import pandas.core.dtypes.concat as _concat
from pandas.core.arrays.datetimes import DatetimeArrayMixin, _to_m8
from pandas.core.arrays import datetimelike as dtl

from pandas.core.indexes.base import Index, _index_shared_docs
from pandas.core.indexes.numeric import Int64Index, Float64Index
import pandas.compat as compat
from pandas.tseries.frequencies import to_offset, get_period_alias, Resolution
from pandas.core.indexes.datetimelike import (
    DatelikeOps, TimelikeOps, DatetimeIndexOpsMixin)
from pandas.tseries.offsets import (
    DateOffset, generate_range, Tick, CDay, prefix_mapping)

from pandas.core.tools.timedeltas import to_timedelta
from pandas.util._decorators import (
    Appender, cache_readonly, deprecate_kwarg, Substitution)
import pandas.core.common as com
import pandas.tseries.offsets as offsets
import pandas.core.tools.datetimes as tools

from pandas._libs import (lib, index as libindex, tslibs, tslib as libts,
                          join as libjoin, Timestamp)
from pandas._libs.tslibs import (timezones, conversion, fields, parsing,
                                 ccalendar)

# -------- some conversion wrapper functions


def _wrap_field_accessor(name):
    fget = getattr(DatetimeArrayMixin, name).fget

    def f(self):
        result = fget(self)
        if is_bool_dtype(result):
            return result
        return Index(result, name=self.name)

    f.__name__ = name
    f.__doc__ = fget.__doc__
    return property(f)


def _wrap_in_index(name):
    meth = getattr(DatetimeArrayMixin, name)

    def func(self, *args, **kwargs):
        result = meth(self, *args, **kwargs)
        return Index(result, name=self.name)

    func.__doc__ = meth.__doc__
    func.__name__ = name
    return func


def _dt_index_cmp(opname, cls):
    """
    Wrap comparison operations to convert datetime-like to datetime64
    """
    def wrapper(self, other):
        result = getattr(DatetimeArrayMixin, opname)(self, other)
        if is_bool_dtype(result):
            return result
        return Index(result)

    return compat.set_function_name(wrapper, opname, cls)


_midnight = time(0, 0)


def _new_DatetimeIndex(cls, d):
    """ This is called upon unpickling, rather than the default which doesn't
    have arguments and breaks __new__ """

    # data are already in UTC
    # so need to localize
    tz = d.pop('tz', None)

    result = cls.__new__(cls, verify_integrity=False, **d)
    if tz is not None:
        result = result.tz_localize('UTC').tz_convert(tz)
    return result


class DatetimeIndex(DatetimeArrayMixin, DatelikeOps, TimelikeOps,
                    DatetimeIndexOpsMixin, Int64Index):
    """
    Immutable ndarray of datetime64 data, represented internally as int64, and
    which can be boxed to Timestamp objects that are subclasses of datetime and
    carry metadata such as frequency information.

    Parameters
    ----------
    data  : array-like (1-dimensional), optional
        Optional datetime-like data to construct index with
    copy  : bool
        Make a copy of input ndarray
    freq : string or pandas offset object, optional
        One of pandas date offset strings or corresponding objects. The string
        'infer' can be passed in order to set the frequency of the index as the
        inferred frequency upon creation

    start : starting value, datetime-like, optional
        If data is None, start is used as the start point in generating regular
        timestamp data.
    periods  : int, optional, > 0
        Number of periods to generate, if generating index. Takes precedence
        over end argument
    end   : end time, datetime-like, optional
        If periods is none, generated index will extend to first conforming
        time on or just past end argument
    closed : string or None, default None
        Make the interval closed with respect to the given frequency to
        the 'left', 'right', or both sides (None)
    tz : pytz.timezone or dateutil.tz.tzfile
    ambiguous : 'infer', bool-ndarray, 'NaT', default 'raise'
        - 'infer' will attempt to infer fall dst-transition hours based on
          order
        - bool-ndarray where True signifies a DST time, False signifies a
          non-DST time (note that this flag is only applicable for ambiguous
          times)
        - 'NaT' will return NaT where there are ambiguous times
        - 'raise' will raise an AmbiguousTimeError if there are ambiguous times
    name : object
        Name to be stored in the index
    dayfirst : bool, default False
        If True, parse dates in `data` with the day first order
    yearfirst : bool, default False
        If True parse dates in `data` with the year first order

    Attributes
    ----------
    year
    month
    day
    hour
    minute
    second
    microsecond
    nanosecond
    date
    time
    dayofyear
    weekofyear
    week
    dayofweek
    weekday
    quarter
    tz
    freq
    freqstr
    is_month_start
    is_month_end
    is_quarter_start
    is_quarter_end
    is_year_start
    is_year_end
    is_leap_year
    inferred_freq

    Methods
    -------
    normalize
    strftime
    snap
    tz_convert
    tz_localize
    round
    floor
    ceil
    to_period
    to_perioddelta
    to_pydatetime
    to_series
    to_frame
    month_name
    day_name

    Notes
    -----
    To learn more about the frequency strings, please see `this link
    <http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases>`__.

    See Also
    ---------
    Index : The base pandas Index type
    TimedeltaIndex : Index of timedelta64 data
    PeriodIndex : Index of Period data
    pandas.to_datetime : Convert argument to datetime
    """
    _resolution = cache_readonly(DatetimeArrayMixin._resolution.fget)

    _typ = 'datetimeindex'
    _join_precedence = 10

    def _join_i8_wrapper(joinf, **kwargs):
        return DatetimeIndexOpsMixin._join_i8_wrapper(joinf, dtype='M8[ns]',
                                                      **kwargs)

    _inner_indexer = _join_i8_wrapper(libjoin.inner_join_indexer_int64)
    _outer_indexer = _join_i8_wrapper(libjoin.outer_join_indexer_int64)
    _left_indexer = _join_i8_wrapper(libjoin.left_join_indexer_int64)
    _left_indexer_unique = _join_i8_wrapper(
        libjoin.left_join_indexer_unique_int64, with_indexers=False)

    @classmethod
    def _add_comparison_methods(cls):
        """ add in comparison methods """
        cls.__eq__ = _dt_index_cmp('__eq__', cls)
        cls.__ne__ = _dt_index_cmp('__ne__', cls)
        cls.__lt__ = _dt_index_cmp('__lt__', cls)
        cls.__gt__ = _dt_index_cmp('__gt__', cls)
        cls.__le__ = _dt_index_cmp('__le__', cls)
        cls.__ge__ = _dt_index_cmp('__ge__', cls)

    _engine_type = libindex.DatetimeEngine

    tz = None
    _freq = None
    _comparables = ['name', 'freqstr', 'tz']
    _attributes = ['name', 'freq', 'tz']

    # define my properties & methods for delegation
    _bool_ops = ['is_month_start', 'is_month_end',
                 'is_quarter_start', 'is_quarter_end', 'is_year_start',
                 'is_year_end', 'is_leap_year']
    _object_ops = ['weekday_name', 'freq', 'tz']
    _field_ops = ['year', 'month', 'day', 'hour', 'minute', 'second',
                  'weekofyear', 'week', 'weekday', 'dayofweek',
                  'dayofyear', 'quarter', 'days_in_month',
                  'daysinmonth', 'microsecond',
                  'nanosecond']
    _other_ops = ['date', 'time']
    _datetimelike_ops = _field_ops + _object_ops + _bool_ops + _other_ops
    _datetimelike_methods = ['to_period', 'tz_localize',
                             'tz_convert',
                             'normalize', 'strftime', 'round', 'floor',
                             'ceil', 'month_name', 'day_name']

    _is_numeric_dtype = False
    _infer_as_myclass = True
    _timezone = cache_readonly(DatetimeArrayMixin._timezone.fget)
    is_normalized = cache_readonly(DatetimeArrayMixin.is_normalized.fget)

    def __new__(cls, data=None,
                freq=None, start=None, end=None, periods=None, tz=None,
                normalize=False, closed=None, ambiguous='raise',
                dayfirst=False, yearfirst=False, dtype=None,
                copy=False, name=None, verify_integrity=True):

        # This allows to later ensure that the 'copy' parameter is honored:
        if isinstance(data, Index):
            ref_to_data = data._data
        else:
            ref_to_data = data

        if name is None and hasattr(data, 'name'):
            name = data.name

        freq_infer = False
        if not isinstance(freq, DateOffset):

            # if a passed freq is None, don't infer automatically
            if freq != 'infer':
                freq = to_offset(freq)
            else:
                freq_infer = True
                freq = None

        periods = dtl.validate_periods(periods)

        # if dtype has an embedded tz, capture it
        if dtype is not None:
            try:
                dtype = DatetimeTZDtype.construct_from_string(dtype)
                dtz = getattr(dtype, 'tz', None)
                if dtz is not None:
                    if tz is not None and str(tz) != str(dtz):
                        raise ValueError("cannot supply both a tz and a dtype"
                                         " with a tz")
                    tz = dtz
            except TypeError:
                pass

        if data is None:
            if freq is None and com._any_none(periods, start, end):
                msg = 'Must provide freq argument if no data is supplied'
                raise ValueError(msg)
            else:
                return cls._generate_range(start, end, periods, name, freq,
                                           tz=tz, normalize=normalize,
                                           closed=closed, ambiguous=ambiguous)

        if not isinstance(data, (np.ndarray, Index, ABCSeries)):
            if is_scalar(data):
                raise ValueError('DatetimeIndex() must be called with a '
                                 'collection of some kind, %s was passed'
                                 % repr(data))
            # other iterable of some kind
            if not isinstance(data, (list, tuple)):
                data = list(data)
            data = np.asarray(data, dtype='O')
        elif isinstance(data, ABCSeries):
            data = data._values

        # data must be Index or np.ndarray here
        if not (is_datetime64_dtype(data) or is_datetimetz(data) or
                is_integer_dtype(data) or lib.infer_dtype(data) == 'integer'):
            data = tools.to_datetime(data, dayfirst=dayfirst,
                                     yearfirst=yearfirst)

        if isinstance(data, DatetimeIndex):
            if tz is None:
                tz = data.tz
            elif data.tz is None:
                data = data.tz_localize(tz, ambiguous=ambiguous)
            else:
                # the tz's must match
                if str(tz) != str(data.tz):
                    msg = ('data is already tz-aware {0}, unable to '
                           'set specified tz: {1}')
                    raise TypeError(msg.format(data.tz, tz))

            subarr = data.values

            if freq is None:
                freq = data.freq
                verify_integrity = False
        elif issubclass(data.dtype.type, np.datetime64):
            if data.dtype != _NS_DTYPE:
                data = conversion.ensure_datetime64ns(data)
            if tz is not None:
                # Convert tz-naive to UTC
                tz = timezones.maybe_get_tz(tz)
                data = conversion.tz_localize_to_utc(data.view('i8'), tz,
                                                     ambiguous=ambiguous)
            subarr = data.view(_NS_DTYPE)
        else:
            # must be integer dtype otherwise
            # assume this data are epoch timestamps
            if data.dtype != _INT64_DTYPE:
                data = data.astype(np.int64, copy=False)
            subarr = data.view(_NS_DTYPE)

        subarr = cls._simple_new(subarr, name=name, freq=freq, tz=tz)
        if dtype is not None:
            if not is_dtype_equal(subarr.dtype, dtype):
                # dtype must be coerced to DatetimeTZDtype above
                if subarr.tz is not None:
                    raise ValueError("cannot localize from non-UTC data")

        if verify_integrity and len(subarr) > 0:
            if freq is not None and not freq_infer:
                cls._validate_frequency(subarr, freq, ambiguous=ambiguous)

        if freq_infer:
            inferred = subarr.inferred_freq
            if inferred:
                subarr.freq = to_offset(inferred)

        return subarr._deepcopy_if_needed(ref_to_data, copy)

    @classmethod
    def _generate_range(cls, start, end, periods, name, freq, tz=None,
                        normalize=False, ambiguous='raise', closed=None):
        if com._count_not_none(start, end, periods, freq) != 3:
            raise ValueError('Of the four parameters: start, end, periods, '
                             'and freq, exactly three must be specified')

        _normalized = True

        if start is not None:
            start = Timestamp(start)

        if end is not None:
            end = Timestamp(end)

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

        try:
            inferred_tz = timezones.infer_tzinfo(start, end)
        except Exception:
            raise TypeError('Start and end cannot both be tz-aware with '
                            'different timezones')

        inferred_tz = timezones.maybe_get_tz(inferred_tz)
        tz = timezones.maybe_get_tz(tz)

        if tz is not None and inferred_tz is not None:
            if not timezones.tz_compare(inferred_tz, tz):
                raise AssertionError("Inferred time zone not equal to passed "
                                     "time zone")

        elif inferred_tz is not None:
            tz = inferred_tz

        if start is not None:
            if normalize:
                start = tslibs.normalize_date(start)
                _normalized = True
            else:
                _normalized = _normalized and start.time() == _midnight

        if end is not None:
            if normalize:
                end = tslibs.normalize_date(end)
                _normalized = True
            else:
                _normalized = _normalized and end.time() == _midnight

        if hasattr(freq, 'delta') and freq != offsets.Day():
            if inferred_tz is None and tz is not None:
                # naive dates
                if start is not None and start.tz is None:
                    start = start.tz_localize(tz, ambiguous=False)

                if end is not None and end.tz is None:
                    end = end.tz_localize(tz, ambiguous=False)

            if start and end:
                if start.tz is None and end.tz is not None:
                    start = start.tz_localize(end.tz, ambiguous=False)

                if end.tz is None and start.tz is not None:
                    end = end.tz_localize(start.tz, ambiguous=False)

            if _use_cached_range(freq, _normalized, start, end):
                index = cls._cached_range(start, end, periods=periods,
                                          freq=freq, name=name)
            else:
                index = _generate_regular_range(cls, start, end, periods, freq)

        else:

            if tz is not None:
                # naive dates
                if start is not None and start.tz is not None:
                    start = start.replace(tzinfo=None)

                if end is not None and end.tz is not None:
                    end = end.replace(tzinfo=None)

            if start and end:
                if start.tz is None and end.tz is not None:
                    end = end.replace(tzinfo=None)

                if end.tz is None and start.tz is not None:
                    start = start.replace(tzinfo=None)

            if freq is not None:
                if _use_cached_range(freq, _normalized, start, end):
                    index = cls._cached_range(start, end, periods=periods,
                                              freq=freq, name=name)
                else:
                    index = _generate_regular_range(cls, start, end,
                                                    periods, freq)

                if tz is not None and getattr(index, 'tz', None) is None:
                    arr = conversion.tz_localize_to_utc(ensure_int64(index),
                                                        tz,
                                                        ambiguous=ambiguous)

                    index = cls(arr)

                    # index is localized datetime64 array -> have to convert
                    # start/end as well to compare
                    if start is not None:
                        start = start.tz_localize(tz).asm8
                    if end is not None:
                        end = end.tz_localize(tz).asm8
            else:
                # Create a linearly spaced date_range in local time
                start = start.tz_localize(tz)
                end = end.tz_localize(tz)
                index = tools.to_datetime(np.linspace(start.value,
                                                      end.value, periods),
                                          utc=True)
                index = index.tz_convert(tz)

        if not left_closed and len(index) and index[0] == start:
            index = index[1:]
        if not right_closed and len(index) and index[-1] == end:
            index = index[:-1]

        index = cls._simple_new(index.values, name=name, freq=freq, tz=tz)

        return index

    def _convert_for_op(self, value):
        """ Convert value to be insertable to ndarray """
        if self._has_same_tz(value):
            return _to_m8(value)
        raise ValueError('Passed item and index have different timezone')

    def _local_timestamps(self):
        if self.is_monotonic:
            return conversion.tz_convert(self.asi8, utc, self.tz)
        else:
            return DatetimeArrayMixin._local_timestamps(self)

    @classmethod
    def _simple_new(cls, values, name=None, freq=None, tz=None,
                    dtype=None, **kwargs):
        """
        we require the we have a dtype compat for the values
        if we are passed a non-dtype compat, then coerce using the constructor
        """

        if getattr(values, 'dtype', None) is None:
            # empty, but with dtype compat
            if values is None:
                values = np.empty(0, dtype=_NS_DTYPE)
                return cls(values, name=name, freq=freq, tz=tz,
                           dtype=dtype, **kwargs)
            values = np.array(values, copy=False)

        if not is_datetime64_dtype(values):
            values = ensure_int64(values).view(_NS_DTYPE)

        values = getattr(values, 'values', values)

        assert isinstance(values, np.ndarray), "values is not an np.ndarray"
        assert is_datetime64_dtype(values)

        result = super(DatetimeIndex, cls)._simple_new(values, freq, tz,
                                                       **kwargs)
        result.name = name
        result._reset_identity()
        return result

    @property
    def _values(self):
        # tz-naive -> ndarray
        # tz-aware -> DatetimeIndex
        if self.tz is not None:
            return self
        else:
            return self.values

    @property
    def tz(self):
        # GH 18595
        return self._tz

    @tz.setter
    def tz(self, value):
        # GH 3746: Prevent localizing or converting the index by setting tz
        raise AttributeError("Cannot directly set timezone. Use tz_localize() "
                             "or tz_convert() as appropriate")

    @property
    def size(self):
        # TODO: Remove this when we have a DatetimeTZArray
        # Necessary to avoid recursion error since DTI._values is a DTI
        # for TZ-aware
        return self._ndarray_values.size

    @property
    def shape(self):
        # TODO: Remove this when we have a DatetimeTZArray
        # Necessary to avoid recursion error since DTI._values is a DTI
        # for TZ-aware
        return self._ndarray_values.shape

    @property
    def nbytes(self):
        # TODO: Remove this when we have a DatetimeTZArray
        # Necessary to avoid recursion error since DTI._values is a DTI
        # for TZ-aware
        return self._ndarray_values.nbytes

    @classmethod
    def _cached_range(cls, start=None, end=None, periods=None, freq=None,
                      name=None):
        if start is None and end is None:
            # I somewhat believe this should never be raised externally
            raise TypeError('Must specify either start or end.')
        if start is not None:
            start = Timestamp(start)
        if end is not None:
            end = Timestamp(end)
        if (start is None or end is None) and periods is None:
            raise TypeError(
                'Must either specify period or provide both start and end.')

        if freq is None:
            # This can't happen with external-facing code
            raise TypeError('Must provide freq.')

        drc = _daterange_cache
        if freq not in _daterange_cache:
            xdr = generate_range(offset=freq, start=_CACHE_START,
                                 end=_CACHE_END)

            arr = tools.to_datetime(list(xdr), box=False)

            cachedRange = DatetimeIndex._simple_new(arr)
            cachedRange.freq = freq
            cachedRange = cachedRange.tz_localize(None)
            cachedRange.name = None
            drc[freq] = cachedRange
        else:
            cachedRange = drc[freq]

        if start is None:
            if not isinstance(end, Timestamp):
                raise AssertionError('end must be an instance of Timestamp')

            end = freq.rollback(end)

            endLoc = cachedRange.get_loc(end) + 1
            startLoc = endLoc - periods
        elif end is None:
            if not isinstance(start, Timestamp):
                raise AssertionError('start must be an instance of Timestamp')

            start = freq.rollforward(start)

            startLoc = cachedRange.get_loc(start)
            endLoc = startLoc + periods
        else:
            if not freq.onOffset(start):
                start = freq.rollforward(start)

            if not freq.onOffset(end):
                end = freq.rollback(end)

            startLoc = cachedRange.get_loc(start)
            endLoc = cachedRange.get_loc(end) + 1

        indexSlice = cachedRange[startLoc:endLoc]
        indexSlice.name = name
        indexSlice.freq = freq

        return indexSlice

    def _mpl_repr(self):
        # how to represent ourselves to matplotlib
        return libts.ints_to_pydatetime(self.asi8, self.tz)

    @cache_readonly
    def _is_dates_only(self):
        """Return a boolean if we are only dates (and don't have a timezone)"""
        from pandas.io.formats.format import _is_dates_only
        return _is_dates_only(self.values) and self.tz is None

    @property
    def _formatter_func(self):
        from pandas.io.formats.format import _get_format_datetime64
        formatter = _get_format_datetime64(is_dates_only=self._is_dates_only)
        return lambda x: "'%s'" % formatter(x, tz=self.tz)

    def __reduce__(self):

        # we use a special reudce here because we need
        # to simply set the .tz (and not reinterpret it)

        d = dict(data=self._data)
        d.update(self._get_attributes_dict())
        return _new_DatetimeIndex, (self.__class__, d), None

    def __setstate__(self, state):
        """Necessary for making this object picklable"""
        if isinstance(state, dict):
            super(DatetimeIndex, self).__setstate__(state)

        elif isinstance(state, tuple):

            # < 0.15 compat
            if len(state) == 2:
                nd_state, own_state = state
                data = np.empty(nd_state[1], dtype=nd_state[2])
                np.ndarray.__setstate__(data, nd_state)

                self.name = own_state[0]
                self._freq = own_state[1]
                self._tz = timezones.tz_standardize(own_state[2])

                # provide numpy < 1.7 compat
                if nd_state[2] == 'M8[us]':
                    new_state = np.ndarray.__reduce__(data.astype('M8[ns]'))
                    np.ndarray.__setstate__(data, new_state[2])

            else:  # pragma: no cover
                data = np.empty(state)
                np.ndarray.__setstate__(data, state)

            self._data = data
            self._reset_identity()

        else:
            raise Exception("invalid pickle state")
    _unpickle_compat = __setstate__

    def _maybe_update_attributes(self, attrs):
        """ Update Index attributes (e.g. freq) depending on op """
        freq = attrs.get('freq', None)
        if freq is not None:
            # no need to infer if freq is None
            attrs['freq'] = 'infer'
        return attrs

    def _format_native_types(self, na_rep='NaT', date_format=None, **kwargs):
        from pandas.io.formats.format import _get_format_datetime64_from_values
        format = _get_format_datetime64_from_values(self, date_format)

        return libts.format_array_from_datetime(self.asi8,
                                                tz=self.tz,
                                                format=format,
                                                na_rep=na_rep)

    @Appender(_index_shared_docs['astype'])
    def astype(self, dtype, copy=True):
        dtype = pandas_dtype(dtype)
        if (is_datetime64_ns_dtype(dtype) and
                not is_dtype_equal(dtype, self.dtype)):
            # GH 18951: datetime64_ns dtype but not equal means different tz
            new_tz = getattr(dtype, 'tz', None)
            if getattr(self.dtype, 'tz', None) is None:
                return self.tz_localize(new_tz)
            return self.tz_convert(new_tz)
        elif is_period_dtype(dtype):
            return self.to_period(freq=dtype.freq)
        return super(DatetimeIndex, self).astype(dtype, copy=copy)

    def _get_time_micros(self):
        values = self.asi8
        if self.tz is not None and self.tz is not utc:
            values = self._local_timestamps()
        return fields.get_time_micros(values)

    def to_series(self, keep_tz=False, index=None, name=None):
        """
        Create a Series with both index and values equal to the index keys
        useful with map for returning an indexer based on an index

        Parameters
        ----------
        keep_tz : optional, defaults False.
            return the data keeping the timezone.

            If keep_tz is True:

              If the timezone is not set, the resulting
              Series will have a datetime64[ns] dtype.

              Otherwise the Series will have an datetime64[ns, tz] dtype; the
              tz will be preserved.

            If keep_tz is False:

              Series will have a datetime64[ns] dtype. TZ aware
              objects will have the tz removed.
        index : Index, optional
            index of resulting Series. If None, defaults to original index
        name : string, optional
            name of resulting Series. If None, defaults to name of original
            index

        Returns
        -------
        Series
        """
        from pandas import Series

        if index is None:
            index = self._shallow_copy()
        if name is None:
            name = self.name

        return Series(self._to_embed(keep_tz), index=index, name=name)

    def _to_embed(self, keep_tz=False, dtype=None):
        """
        return an array repr of this object, potentially casting to object

        This is for internal compat
        """
        if dtype is not None:
            return self.astype(dtype)._to_embed(keep_tz=keep_tz)

        if keep_tz and self.tz is not None:

            # preserve the tz & copy
            return self.copy(deep=True)

        return self.values.copy()

    def to_period(self, freq=None):
        """
        Cast to PeriodIndex at a particular frequency.

        Converts DatetimeIndex to PeriodIndex.

        Parameters
        ----------
        freq : string or Offset, optional
            One of pandas' :ref:`offset strings <timeseries.offset_aliases>`
            or an Offset object. Will be inferred by default.

        Returns
        -------
        PeriodIndex

        Raises
        ------
        ValueError
            When converting a DatetimeIndex with non-regular values, so that a
            frequency cannot be inferred.

        Examples
        --------
        >>> df = pd.DataFrame({"y": [1,2,3]},
        ...                   index=pd.to_datetime(["2000-03-31 00:00:00",
        ...                                         "2000-05-31 00:00:00",
        ...                                         "2000-08-31 00:00:00"]))
        >>> df.index.to_period("M")
        PeriodIndex(['2000-03', '2000-05', '2000-08'],
                    dtype='period[M]', freq='M')

        Infer the daily frequency

        >>> idx = pd.date_range("2017-01-01", periods=2)
        >>> idx.to_period()
        PeriodIndex(['2017-01-01', '2017-01-02'],
                    dtype='period[D]', freq='D')

        See also
        --------
        pandas.PeriodIndex: Immutable ndarray holding ordinal values
        pandas.DatetimeIndex.to_pydatetime: Return DatetimeIndex as object
        """
        from pandas.core.indexes.period import PeriodIndex

        if freq is None:
            freq = self.freqstr or self.inferred_freq

            if freq is None:
                msg = ("You must pass a freq argument as "
                       "current index has none.")
                raise ValueError(msg)

            freq = get_period_alias(freq)

        return PeriodIndex(self.values, name=self.name, freq=freq, tz=self.tz)

    def snap(self, freq='S'):
        """
        Snap time stamps to nearest occurring frequency

        """
        # Superdumb, punting on any optimizing
        freq = to_offset(freq)

        snapped = np.empty(len(self), dtype=_NS_DTYPE)

        for i, v in enumerate(self):
            s = v
            if not freq.onOffset(s):
                t0 = freq.rollback(s)
                t1 = freq.rollforward(s)
                if abs(s - t0) < abs(t1 - s):
                    s = t0
                else:
                    s = t1
            snapped[i] = s

        # we know it conforms; skip check
        return DatetimeIndex(snapped, freq=freq, verify_integrity=False)

    def unique(self, level=None):
        # Override here since IndexOpsMixin.unique uses self._values.unique
        # For DatetimeIndex with TZ, that's a DatetimeIndex -> recursion error
        # So we extract the tz-naive DatetimeIndex, unique that, and wrap the
        # result with out TZ.
        if self.tz is not None:
            naive = type(self)(self._ndarray_values, copy=False)
        else:
            naive = self
        result = super(DatetimeIndex, naive).unique(level=level)
        return self._simple_new(result.values, name=self.name, tz=self.tz,
                                freq=self.freq)

    def union(self, other):
        """
        Specialized union for DatetimeIndex objects. If combine
        overlapping ranges with the same DateOffset, will be much
        faster than Index.union

        Parameters
        ----------
        other : DatetimeIndex or array-like

        Returns
        -------
        y : Index or DatetimeIndex
        """
        self._assert_can_do_setop(other)
        if not isinstance(other, DatetimeIndex):
            try:
                other = DatetimeIndex(other)
            except TypeError:
                pass

        this, other = self._maybe_utc_convert(other)

        if this._can_fast_union(other):
            return this._fast_union(other)
        else:
            result = Index.union(this, other)
            if isinstance(result, DatetimeIndex):
                result._tz = timezones.tz_standardize(this.tz)
                if (result.freq is None and
                        (this.freq is not None or other.freq is not None)):
                    result.freq = to_offset(result.inferred_freq)
            return result

    def to_perioddelta(self, freq):
        """
        Calculate TimedeltaIndex of difference between index
        values and index converted to periodIndex at specified
        freq. Used for vectorized offsets

        Parameters
        ----------
        freq: Period frequency

        Returns
        -------
        y: TimedeltaIndex
        """
        return to_timedelta(self.asi8 - self.to_period(freq)
                            .to_timestamp().asi8)

    def union_many(self, others):
        """
        A bit of a hack to accelerate unioning a collection of indexes
        """
        this = self

        for other in others:
            if not isinstance(this, DatetimeIndex):
                this = Index.union(this, other)
                continue

            if not isinstance(other, DatetimeIndex):
                try:
                    other = DatetimeIndex(other)
                except TypeError:
                    pass

            this, other = this._maybe_utc_convert(other)

            if this._can_fast_union(other):
                this = this._fast_union(other)
            else:
                tz = this.tz
                this = Index.union(this, other)
                if isinstance(this, DatetimeIndex):
                    this._tz = timezones.tz_standardize(tz)

        if this.freq is None:
            this.freq = to_offset(this.inferred_freq)
        return this

    def join(self, other, how='left', level=None, return_indexers=False,
             sort=False):
        """
        See Index.join
        """
        if (not isinstance(other, DatetimeIndex) and len(other) > 0 and
            other.inferred_type not in ('floating', 'integer', 'mixed-integer',
                                        'mixed-integer-float', 'mixed')):
            try:
                other = DatetimeIndex(other)
            except (TypeError, ValueError):
                pass

        this, other = self._maybe_utc_convert(other)
        return Index.join(this, other, how=how, level=level,
                          return_indexers=return_indexers, sort=sort)

    def _maybe_utc_convert(self, other):
        this = self
        if isinstance(other, DatetimeIndex):
            if self.tz is not None:
                if other.tz is None:
                    raise TypeError('Cannot join tz-naive with tz-aware '
                                    'DatetimeIndex')
            elif other.tz is not None:
                raise TypeError('Cannot join tz-naive with tz-aware '
                                'DatetimeIndex')

            if not timezones.tz_compare(self.tz, other.tz):
                this = self.tz_convert('UTC')
                other = other.tz_convert('UTC')
        return this, other

    def _wrap_joined_index(self, joined, other):
        name = self.name if self.name == other.name else None
        if (isinstance(other, DatetimeIndex) and
                self.freq == other.freq and
                self._can_fast_union(other)):
            joined = self._shallow_copy(joined)
            joined.name = name
            return joined
        else:
            tz = getattr(other, 'tz', None)
            return self._simple_new(joined, name, tz=tz)

    def _can_fast_union(self, other):
        if not isinstance(other, DatetimeIndex):
            return False

        freq = self.freq

        if freq is None or freq != other.freq:
            return False

        if not self.is_monotonic or not other.is_monotonic:
            return False

        if len(self) == 0 or len(other) == 0:
            return True

        # to make our life easier, "sort" the two ranges
        if self[0] <= other[0]:
            left, right = self, other
        else:
            left, right = other, self

        right_start = right[0]
        left_end = left[-1]

        # Only need to "adjoin", not overlap
        try:
            return (right_start == left_end + freq) or right_start in left
        except (ValueError):

            # if we are comparing a freq that does not propagate timezones
            # this will raise
            return False

    def _fast_union(self, other):
        if len(other) == 0:
            return self.view(type(self))

        if len(self) == 0:
            return other.view(type(self))

        # to make our life easier, "sort" the two ranges
        if self[0] <= other[0]:
            left, right = self, other
        else:
            left, right = other, self

        left_start, left_end = left[0], left[-1]
        right_end = right[-1]

        if not self.freq._should_cache():
            # concatenate dates
            if left_end < right_end:
                loc = right.searchsorted(left_end, side='right')
                right_chunk = right.values[loc:]
                dates = _concat._concat_compat((left.values, right_chunk))
                return self._shallow_copy(dates)
            else:
                return left
        else:
            return type(self)(start=left_start,
                              end=max(left_end, right_end),
                              freq=left.freq)

    def _wrap_union_result(self, other, result):
        name = self.name if self.name == other.name else None
        if not timezones.tz_compare(self.tz, other.tz):
            raise ValueError('Passed item and index have different timezone')
        return self._simple_new(result, name=name, freq=None, tz=self.tz)

    def intersection(self, other):
        """
        Specialized intersection for DatetimeIndex objects. May be much faster
        than Index.intersection

        Parameters
        ----------
        other : DatetimeIndex or array-like

        Returns
        -------
        y : Index or DatetimeIndex
        """
        self._assert_can_do_setop(other)
        if not isinstance(other, DatetimeIndex):
            try:
                other = DatetimeIndex(other)
            except (TypeError, ValueError):
                pass
            result = Index.intersection(self, other)
            if isinstance(result, DatetimeIndex):
                if result.freq is None:
                    result.freq = to_offset(result.inferred_freq)
            return result

        elif (other.freq is None or self.freq is None or
              other.freq != self.freq or
              not other.freq.isAnchored() or
              (not self.is_monotonic or not other.is_monotonic)):
            result = Index.intersection(self, other)
            result = self._shallow_copy(result._values, name=result.name,
                                        tz=result.tz, freq=None)
            if result.freq is None:
                result.freq = to_offset(result.inferred_freq)
            return result

        if len(self) == 0:
            return self
        if len(other) == 0:
            return other
        # to make our life easier, "sort" the two ranges
        if self[0] <= other[0]:
            left, right = self, other
        else:
            left, right = other, self

        end = min(left[-1], right[-1])
        start = right[0]

        if end < start:
            return type(self)(data=[])
        else:
            lslice = slice(*left.slice_locs(start, end))
            left_chunk = left.values[lslice]
            return self._shallow_copy(left_chunk)

    def _parsed_string_to_bounds(self, reso, parsed):
        """
        Calculate datetime bounds for parsed time string and its resolution.

        Parameters
        ----------
        reso : Resolution
            Resolution provided by parsed string.
        parsed : datetime
            Datetime from parsed string.

        Returns
        -------
        lower, upper: pd.Timestamp

        """
        if reso == 'year':
            return (Timestamp(datetime(parsed.year, 1, 1), tz=self.tz),
                    Timestamp(datetime(parsed.year, 12, 31, 23,
                                       59, 59, 999999), tz=self.tz))
        elif reso == 'month':
            d = ccalendar.get_days_in_month(parsed.year, parsed.month)
            return (Timestamp(datetime(parsed.year, parsed.month, 1),
                              tz=self.tz),
                    Timestamp(datetime(parsed.year, parsed.month, d, 23,
                                       59, 59, 999999), tz=self.tz))
        elif reso == 'quarter':
            qe = (((parsed.month - 1) + 2) % 12) + 1  # two months ahead
            d = ccalendar.get_days_in_month(parsed.year, qe)  # at end of month
            return (Timestamp(datetime(parsed.year, parsed.month, 1),
                              tz=self.tz),
                    Timestamp(datetime(parsed.year, qe, d, 23, 59,
                                       59, 999999), tz=self.tz))
        elif reso == 'day':
            st = datetime(parsed.year, parsed.month, parsed.day)
            return (Timestamp(st, tz=self.tz),
                    Timestamp(Timestamp(st + offsets.Day(),
                                        tz=self.tz).value - 1))
        elif reso == 'hour':
            st = datetime(parsed.year, parsed.month, parsed.day,
                          hour=parsed.hour)
            return (Timestamp(st, tz=self.tz),
                    Timestamp(Timestamp(st + offsets.Hour(),
                                        tz=self.tz).value - 1))
        elif reso == 'minute':
            st = datetime(parsed.year, parsed.month, parsed.day,
                          hour=parsed.hour, minute=parsed.minute)
            return (Timestamp(st, tz=self.tz),
                    Timestamp(Timestamp(st + offsets.Minute(),
                                        tz=self.tz).value - 1))
        elif reso == 'second':
            st = datetime(parsed.year, parsed.month, parsed.day,
                          hour=parsed.hour, minute=parsed.minute,
                          second=parsed.second)
            return (Timestamp(st, tz=self.tz),
                    Timestamp(Timestamp(st + offsets.Second(),
                                        tz=self.tz).value - 1))
        elif reso == 'microsecond':
            st = datetime(parsed.year, parsed.month, parsed.day,
                          parsed.hour, parsed.minute, parsed.second,
                          parsed.microsecond)
            return (Timestamp(st, tz=self.tz), Timestamp(st, tz=self.tz))
        else:
            raise KeyError

    def _partial_date_slice(self, reso, parsed, use_lhs=True, use_rhs=True):
        is_monotonic = self.is_monotonic
        if (is_monotonic and reso in ['day', 'hour', 'minute', 'second'] and
                self._resolution >= Resolution.get_reso(reso)):
            # These resolution/monotonicity validations came from GH3931,
            # GH3452 and GH2369.

            # See also GH14826
            raise KeyError

        if reso == 'microsecond':
            # _partial_date_slice doesn't allow microsecond resolution, but
            # _parsed_string_to_bounds allows it.
            raise KeyError

        t1, t2 = self._parsed_string_to_bounds(reso, parsed)
        stamps = self.asi8

        if is_monotonic:

            # we are out of range
            if (len(stamps) and ((use_lhs and t1.value < stamps[0] and
                                  t2.value < stamps[0]) or
                                 ((use_rhs and t1.value > stamps[-1] and
                                   t2.value > stamps[-1])))):
                raise KeyError

            # a monotonic (sorted) series can be sliced
            left = stamps.searchsorted(
                t1.value, side='left') if use_lhs else None
            right = stamps.searchsorted(
                t2.value, side='right') if use_rhs else None

            return slice(left, right)

        lhs_mask = (stamps >= t1.value) if use_lhs else True
        rhs_mask = (stamps <= t2.value) if use_rhs else True

        # try to find a the dates
        return (lhs_mask & rhs_mask).nonzero()[0]

    def _maybe_promote(self, other):
        if other.inferred_type == 'date':
            other = DatetimeIndex(other)
        return self, other

    def get_value(self, series, key):
        """
        Fast lookup of value from 1-dimensional ndarray. Only use this if you
        know what you're doing
        """

        if isinstance(key, datetime):

            # needed to localize naive datetimes
            if self.tz is not None:
                key = Timestamp(key, tz=self.tz)

            return self.get_value_maybe_box(series, key)

        if isinstance(key, time):
            locs = self.indexer_at_time(key)
            return series.take(locs)

        try:
            return com._maybe_box(self, Index.get_value(self, series, key),
                                  series, key)
        except KeyError:
            try:
                loc = self._get_string_slice(key)
                return series[loc]
            except (TypeError, ValueError, KeyError):
                pass

            try:
                return self.get_value_maybe_box(series, key)
            except (TypeError, ValueError, KeyError):
                raise KeyError(key)

    def get_value_maybe_box(self, series, key):
        # needed to localize naive datetimes
        if self.tz is not None:
            key = Timestamp(key, tz=self.tz)
        elif not isinstance(key, Timestamp):
            key = Timestamp(key)
        values = self._engine.get_value(com._values_from_object(series),
                                        key, tz=self.tz)
        return com._maybe_box(self, values, series, key)

    def get_loc(self, key, method=None, tolerance=None):
        """
        Get integer location for requested label

        Returns
        -------
        loc : int
        """

        if tolerance is not None:
            # try converting tolerance now, so errors don't get swallowed by
            # the try/except clauses below
            tolerance = self._convert_tolerance(tolerance, np.asarray(key))

        if isinstance(key, datetime):
            # needed to localize naive datetimes
            key = Timestamp(key, tz=self.tz)
            return Index.get_loc(self, key, method, tolerance)

        if isinstance(key, time):
            if method is not None:
                raise NotImplementedError('cannot yet lookup inexact labels '
                                          'when key is a time object')
            return self.indexer_at_time(key)

        try:
            return Index.get_loc(self, key, method, tolerance)
        except (KeyError, ValueError, TypeError):
            try:
                return self._get_string_slice(key)
            except (TypeError, KeyError, ValueError):
                pass

            try:
                stamp = Timestamp(key, tz=self.tz)
                return Index.get_loc(self, stamp, method, tolerance)
            except KeyError:
                raise KeyError(key)
            except ValueError as e:
                # list-like tolerance size must match target index size
                if 'list-like' in str(e):
                    raise e
                raise KeyError(key)

    def _maybe_cast_slice_bound(self, label, side, kind):
        """
        If label is a string, cast it to datetime according to resolution.

        Parameters
        ----------
        label : object
        side : {'left', 'right'}
        kind : {'ix', 'loc', 'getitem'}

        Returns
        -------
        label :  object

        Notes
        -----
        Value of `side` parameter should be validated in caller.

        """
        assert kind in ['ix', 'loc', 'getitem', None]

        if is_float(label) or isinstance(label, time) or is_integer(label):
            self._invalid_indexer('slice', label)

        if isinstance(label, compat.string_types):
            freq = getattr(self, 'freqstr',
                           getattr(self, 'inferred_freq', None))
            _, parsed, reso = parsing.parse_time_string(label, freq)
            lower, upper = self._parsed_string_to_bounds(reso, parsed)
            # lower, upper form the half-open interval:
            #   [parsed, parsed + 1 freq)
            # because label may be passed to searchsorted
            # the bounds need swapped if index is reverse sorted and has a
            # length > 1 (is_monotonic_decreasing gives True for empty
            # and length 1 index)
            if self._is_strictly_monotonic_decreasing and len(self) > 1:
                return upper if side == 'left' else lower
            return lower if side == 'left' else upper
        else:
            return label

    def _get_string_slice(self, key, use_lhs=True, use_rhs=True):
        freq = getattr(self, 'freqstr',
                       getattr(self, 'inferred_freq', None))
        _, parsed, reso = parsing.parse_time_string(key, freq)
        loc = self._partial_date_slice(reso, parsed, use_lhs=use_lhs,
                                       use_rhs=use_rhs)
        return loc

    def slice_indexer(self, start=None, end=None, step=None, kind=None):
        """
        Return indexer for specified label slice.
        Index.slice_indexer, customized to handle time slicing.

        In addition to functionality provided by Index.slice_indexer, does the
        following:

        - if both `start` and `end` are instances of `datetime.time`, it
          invokes `indexer_between_time`
        - if `start` and `end` are both either string or None perform
          value-based selection in non-monotonic cases.

        """
        # For historical reasons DatetimeIndex supports slices between two
        # instances of datetime.time as if it were applying a slice mask to
        # an array of (self.hour, self.minute, self.seconds, self.microsecond).
        if isinstance(start, time) and isinstance(end, time):
            if step is not None and step != 1:
                raise ValueError('Must have step size of 1 with time slices')
            return self.indexer_between_time(start, end)

        if isinstance(start, time) or isinstance(end, time):
            raise KeyError('Cannot mix time and non-time slice keys')

        try:
            return Index.slice_indexer(self, start, end, step, kind=kind)
        except KeyError:
            # For historical reasons DatetimeIndex by default supports
            # value-based partial (aka string) slices on non-monotonic arrays,
            # let's try that.
            if ((start is None or isinstance(start, compat.string_types)) and
                    (end is None or isinstance(end, compat.string_types))):
                mask = True
                if start is not None:
                    start_casted = self._maybe_cast_slice_bound(
                        start, 'left', kind)
                    mask = start_casted <= self

                if end is not None:
                    end_casted = self._maybe_cast_slice_bound(
                        end, 'right', kind)
                    mask = (self <= end_casted) & mask

                indexer = mask.nonzero()[0][::step]
                if len(indexer) == len(self):
                    return slice(None)
                else:
                    return indexer
            else:
                raise

    year = _wrap_field_accessor('year')
    month = _wrap_field_accessor('month')
    day = _wrap_field_accessor('day')
    hour = _wrap_field_accessor('hour')
    minute = _wrap_field_accessor('minute')
    second = _wrap_field_accessor('second')
    microsecond = _wrap_field_accessor('microsecond')
    nanosecond = _wrap_field_accessor('nanosecond')
    weekofyear = _wrap_field_accessor('weekofyear')
    week = weekofyear
    dayofweek = _wrap_field_accessor('dayofweek')
    weekday = dayofweek

    weekday_name = _wrap_field_accessor('weekday_name')

    dayofyear = _wrap_field_accessor('dayofyear')
    quarter = _wrap_field_accessor('quarter')
    days_in_month = _wrap_field_accessor('days_in_month')
    daysinmonth = days_in_month
    is_month_start = _wrap_field_accessor('is_month_start')
    is_month_end = _wrap_field_accessor('is_month_end')
    is_quarter_start = _wrap_field_accessor('is_quarter_start')
    is_quarter_end = _wrap_field_accessor('is_quarter_end')
    is_year_start = _wrap_field_accessor('is_year_start')
    is_year_end = _wrap_field_accessor('is_year_end')
    is_leap_year = _wrap_field_accessor('is_leap_year')

    @Appender(DatetimeArrayMixin.normalize.__doc__)
    def normalize(self):
        result = DatetimeArrayMixin.normalize(self)
        result.name = self.name
        return result

    @Substitution(klass='DatetimeIndex')
    @Appender(_shared_docs['searchsorted'])
    @deprecate_kwarg(old_arg_name='key', new_arg_name='value')
    def searchsorted(self, value, side='left', sorter=None):
        if isinstance(value, (np.ndarray, Index)):
            value = np.array(value, dtype=_NS_DTYPE, copy=False)
        else:
            value = _to_m8(value, tz=self.tz)

        return self.values.searchsorted(value, side=side)

    def is_type_compatible(self, typ):
        return typ == self.inferred_type or typ == 'datetime'

    @property
    def inferred_type(self):
        # b/c datetime is represented as microseconds since the epoch, make
        # sure we can't have ambiguous indexing
        return 'datetime64'

    @property
    def is_all_dates(self):
        return True

    def insert(self, loc, item):
        """
        Make new Index inserting new item at location

        Parameters
        ----------
        loc : int
        item : object
            if not either a Python datetime or a numpy integer-like, returned
            Index dtype will be object rather than datetime.

        Returns
        -------
        new_index : Index
        """
        if is_scalar(item) and isna(item):
            # GH 18295
            item = self._na_value

        freq = None

        if isinstance(item, (datetime, np.datetime64)):
            self._assert_can_do_op(item)
            if not self._has_same_tz(item) and not isna(item):
                raise ValueError(
                    'Passed item and index have different timezone')
            # check freq can be preserved on edge cases
            if self.size and self.freq is not None:
                if ((loc == 0 or loc == -len(self)) and
                        item + self.freq == self[0]):
                    freq = self.freq
                elif (loc == len(self)) and item - self.freq == self[-1]:
                    freq = self.freq
            item = _to_m8(item, tz=self.tz)

        try:
            new_dates = np.concatenate((self[:loc].asi8, [item.view(np.int64)],
                                        self[loc:].asi8))
            return DatetimeIndex(new_dates, name=self.name, freq=freq,
                                 tz=self.tz)
        except (AttributeError, TypeError):

            # fall back to object index
            if isinstance(item, compat.string_types):
                return self.astype(object).insert(loc, item)
            raise TypeError(
                "cannot insert DatetimeIndex with incompatible label")

    def delete(self, loc):
        """
        Make a new DatetimeIndex with passed location(s) deleted.

        Parameters
        ----------
        loc: int, slice or array of ints
            Indicate which sub-arrays to remove.

        Returns
        -------
        new_index : DatetimeIndex
        """
        new_dates = np.delete(self.asi8, loc)

        freq = None
        if is_integer(loc):
            if loc in (0, -len(self), -1, len(self) - 1):
                freq = self.freq
        else:
            if is_list_like(loc):
                loc = lib.maybe_indices_to_slice(
                    ensure_int64(np.array(loc)), len(self))
            if isinstance(loc, slice) and loc.step in (1, None):
                if (loc.start in (0, None) or loc.stop in (len(self), None)):
                    freq = self.freq

        return DatetimeIndex(new_dates, name=self.name, freq=freq, tz=self.tz)

    def indexer_at_time(self, time, asof=False):
        """
        Returns index locations of index values at particular time of day
        (e.g. 9:30AM).

        Parameters
        ----------
        time : datetime.time or string
            datetime.time or string in appropriate format ("%H:%M", "%H%M",
            "%I:%M%p", "%I%M%p", "%H:%M:%S", "%H%M%S", "%I:%M:%S%p",
            "%I%M%S%p").

        Returns
        -------
        values_at_time : array of integers

        See Also
        --------
        indexer_between_time, DataFrame.at_time
        """
        from dateutil.parser import parse

        if asof:
            raise NotImplementedError("'asof' argument is not supported")

        if isinstance(time, compat.string_types):
            time = parse(time).time()

        if time.tzinfo:
            # TODO
            raise NotImplementedError("argument 'time' with timezone info is "
                                      "not supported")

        time_micros = self._get_time_micros()
        micros = _time_to_micros(time)
        return (micros == time_micros).nonzero()[0]

    def indexer_between_time(self, start_time, end_time, include_start=True,
                             include_end=True):
        """
        Return index locations of values between particular times of day
        (e.g., 9:00-9:30AM).

        Parameters
        ----------
        start_time, end_time : datetime.time, str
            datetime.time or string in appropriate format ("%H:%M", "%H%M",
            "%I:%M%p", "%I%M%p", "%H:%M:%S", "%H%M%S", "%I:%M:%S%p",
            "%I%M%S%p").
        include_start : boolean, default True
        include_end : boolean, default True

        Returns
        -------
        values_between_time : array of integers

        See Also
        --------
        indexer_at_time, DataFrame.between_time
        """
        start_time = tools.to_time(start_time)
        end_time = tools.to_time(end_time)
        time_micros = self._get_time_micros()
        start_micros = _time_to_micros(start_time)
        end_micros = _time_to_micros(end_time)

        if include_start and include_end:
            lop = rop = operator.le
        elif include_start:
            lop = operator.le
            rop = operator.lt
        elif include_end:
            lop = operator.lt
            rop = operator.le
        else:
            lop = rop = operator.lt

        if start_time <= end_time:
            join_op = operator.and_
        else:
            join_op = operator.or_

        mask = join_op(lop(start_micros, time_micros),
                       rop(time_micros, end_micros))

        return mask.nonzero()[0]

    def to_julian_date(self):
        """
        Convert DatetimeIndex to Float64Index of Julian Dates.
        0 Julian date is noon January 1, 4713 BC.
        http://en.wikipedia.org/wiki/Julian_day
        """
        result = DatetimeArrayMixin.to_julian_date(self)
        return Float64Index(result)

    month_name = _wrap_in_index("month_name")
    day_name = _wrap_in_index("day_name")


DatetimeIndex._add_comparison_methods()
DatetimeIndex._add_numeric_methods_disabled()
DatetimeIndex._add_logical_methods_disabled()
DatetimeIndex._add_datetimelike_methods()


def _generate_regular_range(cls, start, end, periods, freq):
    if isinstance(freq, Tick):
        stride = freq.nanos
        if periods is None:
            b = Timestamp(start).value
            # cannot just use e = Timestamp(end) + 1 because arange breaks when
            # stride is too large, see GH10887
            e = (b + (Timestamp(end).value - b) // stride * stride +
                 stride // 2 + 1)
            # end.tz == start.tz by this point due to _generate implementation
            tz = start.tz
        elif start is not None:
            b = Timestamp(start).value
            e = b + np.int64(periods) * stride
            tz = start.tz
        elif end is not None:
            e = Timestamp(end).value + stride
            b = e - np.int64(periods) * stride
            tz = end.tz
        else:
            raise ValueError("at least 'start' or 'end' should be specified "
                             "if a 'period' is given.")

        data = np.arange(b, e, stride, dtype=np.int64)
        # TODO: Do we need to use _simple_new here?  just return data.view?
        data = cls._simple_new(data.view(_NS_DTYPE), None, tz=tz)
    else:
        if isinstance(start, Timestamp):
            start = start.to_pydatetime()

        if isinstance(end, Timestamp):
            end = end.to_pydatetime()

        xdr = generate_range(start=start, end=end,
                             periods=periods, offset=freq)

        dates = list(xdr)
        # utc = len(dates) > 0 and dates[0].tzinfo is not None
        data = tools.to_datetime(dates)

    return data


def date_range(start=None, end=None, periods=None, freq=None, tz=None,
               normalize=False, name=None, closed=None, **kwargs):
    """
    Return a fixed frequency DatetimeIndex.

    Parameters
    ----------
    start : str or datetime-like, optional
        Left bound for generating dates.
    end : str or datetime-like, optional
        Right bound for generating dates.
    periods : integer, optional
        Number of periods to generate.
    freq : str or DateOffset, default 'D' (calendar daily)
        Frequency strings can have multiples, e.g. '5H'. See
        :ref:`here <timeseries.offset_aliases>` for a list of
        frequency aliases.
    tz : str or tzinfo, optional
        Time zone name for returning localized DatetimeIndex, for example
        'Asia/Hong_Kong'. By default, the resulting DatetimeIndex is
        timezone-naive.
    normalize : bool, default False
        Normalize start/end dates to midnight before generating date range.
    name : str, default None
        Name of the resulting DatetimeIndex.
    closed : {None, 'left', 'right'}, optional
        Make the interval closed with respect to the given frequency to
        the 'left', 'right', or both sides (None, the default).
    **kwargs
        For compatibility. Has no effect on the result.

    Returns
    -------
    rng : DatetimeIndex

    See Also
    --------
    pandas.DatetimeIndex : An immutable container for datetimes.
    pandas.timedelta_range : Return a fixed frequency TimedeltaIndex.
    pandas.period_range : Return a fixed frequency PeriodIndex.
    pandas.interval_range : Return a fixed frequency IntervalIndex.

    Notes
    -----
    Of the four parameters ``start``, ``end``, ``periods``, and ``freq``,
    exactly three must be specified. If ``freq`` is omitted, the resulting
    ``DatetimeIndex`` will have ``periods`` linearly spaced elements between
    ``start`` and ``end`` (closed on both sides).

    To learn more about the frequency strings, please see `this link
    <http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases>`__.

    Examples
    --------
    **Specifying the values**

    The next four examples generate the same `DatetimeIndex`, but vary
    the combination of `start`, `end` and `periods`.

    Specify `start` and `end`, with the default daily frequency.

    >>> pd.date_range(start='1/1/2018', end='1/08/2018')
    DatetimeIndex(['2018-01-01', '2018-01-02', '2018-01-03', '2018-01-04',
                   '2018-01-05', '2018-01-06', '2018-01-07', '2018-01-08'],
                  dtype='datetime64[ns]', freq='D')

    Specify `start` and `periods`, the number of periods (days).

    >>> pd.date_range(start='1/1/2018', periods=8)
    DatetimeIndex(['2018-01-01', '2018-01-02', '2018-01-03', '2018-01-04',
                   '2018-01-05', '2018-01-06', '2018-01-07', '2018-01-08'],
                  dtype='datetime64[ns]', freq='D')

    Specify `end` and `periods`, the number of periods (days).

    >>> pd.date_range(end='1/1/2018', periods=8)
    DatetimeIndex(['2017-12-25', '2017-12-26', '2017-12-27', '2017-12-28',
                   '2017-12-29', '2017-12-30', '2017-12-31', '2018-01-01'],
                  dtype='datetime64[ns]', freq='D')

    Specify `start`, `end`, and `periods`; the frequency is generated
    automatically (linearly spaced).

    >>> pd.date_range(start='2018-04-24', end='2018-04-27', periods=3)
    DatetimeIndex(['2018-04-24 00:00:00', '2018-04-25 12:00:00',
                   '2018-04-27 00:00:00'], freq=None)

    **Other Parameters**

    Changed the `freq` (frequency) to ``'M'`` (month end frequency).

    >>> pd.date_range(start='1/1/2018', periods=5, freq='M')
    DatetimeIndex(['2018-01-31', '2018-02-28', '2018-03-31', '2018-04-30',
                   '2018-05-31'],
                  dtype='datetime64[ns]', freq='M')

    Multiples are allowed

    >>> pd.date_range(start='1/1/2018', periods=5, freq='3M')
    DatetimeIndex(['2018-01-31', '2018-04-30', '2018-07-31', '2018-10-31',
                   '2019-01-31'],
                  dtype='datetime64[ns]', freq='3M')

    `freq` can also be specified as an Offset object.

    >>> pd.date_range(start='1/1/2018', periods=5, freq=pd.offsets.MonthEnd(3))
    DatetimeIndex(['2018-01-31', '2018-04-30', '2018-07-31', '2018-10-31',
                   '2019-01-31'],
                  dtype='datetime64[ns]', freq='3M')

    Specify `tz` to set the timezone.

    >>> pd.date_range(start='1/1/2018', periods=5, tz='Asia/Tokyo')
    DatetimeIndex(['2018-01-01 00:00:00+09:00', '2018-01-02 00:00:00+09:00',
                   '2018-01-03 00:00:00+09:00', '2018-01-04 00:00:00+09:00',
                   '2018-01-05 00:00:00+09:00'],
                  dtype='datetime64[ns, Asia/Tokyo]', freq='D')

    `closed` controls whether to include `start` and `end` that are on the
    boundary. The default includes boundary points on either end.

    >>> pd.date_range(start='2017-01-01', end='2017-01-04', closed=None)
    DatetimeIndex(['2017-01-01', '2017-01-02', '2017-01-03', '2017-01-04'],
                  dtype='datetime64[ns]', freq='D')

    Use ``closed='left'`` to exclude `end` if it falls on the boundary.

    >>> pd.date_range(start='2017-01-01', end='2017-01-04', closed='left')
    DatetimeIndex(['2017-01-01', '2017-01-02', '2017-01-03'],
                  dtype='datetime64[ns]', freq='D')

    Use ``closed='right'`` to exclude `start` if it falls on the boundary.

    >>> pd.date_range(start='2017-01-01', end='2017-01-04', closed='right')
    DatetimeIndex(['2017-01-02', '2017-01-03', '2017-01-04'],
                  dtype='datetime64[ns]', freq='D')
    """

    if freq is None and com._any_none(periods, start, end):
        freq = 'D'

    return DatetimeIndex(start=start, end=end, periods=periods,
                         freq=freq, tz=tz, normalize=normalize, name=name,
                         closed=closed, **kwargs)


def bdate_range(start=None, end=None, periods=None, freq='B', tz=None,
                normalize=True, name=None, weekmask=None, holidays=None,
                closed=None, **kwargs):
    """
    Return a fixed frequency DatetimeIndex, with business day as the default
    frequency

    Parameters
    ----------
    start : string or datetime-like, default None
        Left bound for generating dates
    end : string or datetime-like, default None
        Right bound for generating dates
    periods : integer, default None
        Number of periods to generate
    freq : string or DateOffset, default 'B' (business daily)
        Frequency strings can have multiples, e.g. '5H'
    tz : string or None
        Time zone name for returning localized DatetimeIndex, for example
        Asia/Beijing
    normalize : bool, default False
        Normalize start/end dates to midnight before generating date range
    name : string, default None
        Name of the resulting DatetimeIndex
    weekmask : string or None, default None
        Weekmask of valid business days, passed to ``numpy.busdaycalendar``,
        only used when custom frequency strings are passed.  The default
        value None is equivalent to 'Mon Tue Wed Thu Fri'

        .. versionadded:: 0.21.0

    holidays : list-like or None, default None
        Dates to exclude from the set of valid business days, passed to
        ``numpy.busdaycalendar``, only used when custom frequency strings
        are passed

        .. versionadded:: 0.21.0

    closed : string, default None
        Make the interval closed with respect to the given frequency to
        the 'left', 'right', or both sides (None)

    Notes
    -----
    Of the four parameters: ``start``, ``end``, ``periods``, and ``freq``,
    exactly three must be specified.  Specifying ``freq`` is a requirement
    for ``bdate_range``.  Use ``date_range`` if specifying ``freq`` is not
    desired.

    To learn more about the frequency strings, please see `this link
    <http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases>`__.

    Returns
    -------
    rng : DatetimeIndex
    """
    if freq is None:
        msg = 'freq must be specified for bdate_range; use date_range instead'
        raise TypeError(msg)

    if is_string_like(freq) and freq.startswith('C'):
        try:
            weekmask = weekmask or 'Mon Tue Wed Thu Fri'
            freq = prefix_mapping[freq](holidays=holidays, weekmask=weekmask)
        except (KeyError, TypeError):
            msg = 'invalid custom frequency string: {freq}'.format(freq=freq)
            raise ValueError(msg)
    elif holidays or weekmask:
        msg = ('a custom frequency string is required when holidays or '
               'weekmask are passed, got frequency {freq}').format(freq=freq)
        raise ValueError(msg)

    return DatetimeIndex(start=start, end=end, periods=periods,
                         freq=freq, tz=tz, normalize=normalize, name=name,
                         closed=closed, **kwargs)


def cdate_range(start=None, end=None, periods=None, freq='C', tz=None,
                normalize=True, name=None, closed=None, **kwargs):
    """
    Return a fixed frequency DatetimeIndex, with CustomBusinessDay as the
    default frequency

    .. deprecated:: 0.21.0

    Parameters
    ----------
    start : string or datetime-like, default None
        Left bound for generating dates
    end : string or datetime-like, default None
        Right bound for generating dates
    periods : integer, default None
        Number of periods to generate
    freq : string or DateOffset, default 'C' (CustomBusinessDay)
        Frequency strings can have multiples, e.g. '5H'
    tz : string, default None
        Time zone name for returning localized DatetimeIndex, for example
        Asia/Beijing
    normalize : bool, default False
        Normalize start/end dates to midnight before generating date range
    name : string, default None
        Name of the resulting DatetimeIndex
    weekmask : string, Default 'Mon Tue Wed Thu Fri'
        weekmask of valid business days, passed to ``numpy.busdaycalendar``
    holidays : list
        list/array of dates to exclude from the set of valid business days,
        passed to ``numpy.busdaycalendar``
    closed : string, default None
        Make the interval closed with respect to the given frequency to
        the 'left', 'right', or both sides (None)

    Notes
    -----
    Of the three parameters: ``start``, ``end``, and ``periods``, exactly two
    must be specified.

    To learn more about the frequency strings, please see `this link
    <http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset-aliases>`__.

    Returns
    -------
    rng : DatetimeIndex
    """
    warnings.warn("cdate_range is deprecated and will be removed in a future "
                  "version, instead use pd.bdate_range(..., freq='{freq}')"
                  .format(freq=freq), FutureWarning, stacklevel=2)

    if freq == 'C':
        holidays = kwargs.pop('holidays', [])
        weekmask = kwargs.pop('weekmask', 'Mon Tue Wed Thu Fri')
        freq = CDay(holidays=holidays, weekmask=weekmask)
    return DatetimeIndex(start=start, end=end, periods=periods, freq=freq,
                         tz=tz, normalize=normalize, name=name,
                         closed=closed, **kwargs)


_CACHE_START = Timestamp(datetime(1950, 1, 1))
_CACHE_END = Timestamp(datetime(2030, 1, 1))

_daterange_cache = {}


def _naive_in_cache_range(start, end):
    if start is None or end is None:
        return False
    else:
        if start.tzinfo is not None or end.tzinfo is not None:
            return False
        return _in_range(start, end, _CACHE_START, _CACHE_END)


def _in_range(start, end, rng_start, rng_end):
    return start > rng_start and end < rng_end


def _use_cached_range(freq, _normalized, start, end):
    return (freq._should_cache() and
            not (freq._normalize_cache and not _normalized) and
            _naive_in_cache_range(start, end))


def _time_to_micros(time):
    seconds = time.hour * 60 * 60 + 60 * time.minute + time.second
    return 1000000 * seconds + time.microsecond
