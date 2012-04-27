import numpy as np

from pandas.core.groupby import BinGrouper
from pandas.tseries.frequencies import to_offset
from pandas.tseries.index import DatetimeIndex, date_range
from pandas.tseries.offsets import DateOffset
from pandas.tseries.period import PeriodIndex, period_range
from pandas.util.decorators import cache_readonly
import pandas.core.common as com

from pandas._tseries import Timestamp
import pandas._tseries as lib

class TimeGrouper(BinGrouper):
    """
    Custom groupby class for time-interval grouping

    Parameters
    ----------
    rule : pandas offset string or object for identifying bin edges
    closed : closed end of interval; left (default) or right
    label : interval boundary to use for labeling; left (default) or right
    begin : optional, timestamp-like
    end : optional, timestamp-like
    nperiods : optional, integer

    Notes
    -----
    Use begin, end, nperiods to generate intervals that cannot be derived
    directly from the associated object
    """

    axis = None
    bins = None
    binlabels = None
    begin = None
    end = None
    nperiods = None
    binner = None

    _filter_empty_groups = False

    def __init__(self, offset='Min', closed='left', label='left',
                 begin=None, end=None, nperiods=None, axis=None,
                 kind=None):
        self.freq = offset
        self.closed = closed
        self.label = label
        self.begin = begin
        self.end = end
        self.nperiods = None
        self.kind = kind

        if axis is not None:
            self.set_axis(axis)

    def set_axis(self, axis):
        """
        Injects the axisect we'll act on, which we use to initialize grouper
        """
        if id(self.axis) == id(axis):
            return

        if not isinstance(axis, (DatetimeIndex, PeriodIndex)):
            raise ValueError('Only valid with DatetimeIndex or PeriodIndex')

        self.axis = axis

        if len(self.axis) < 1:
            # TODO: Should we be a bit more careful here?
            self.bins = []
            self.binlabels = []
            return

        if isinstance(self.axis, DatetimeIndex):
            self.binner, self.bins, self.binlabels = self._group_timestamps()
        elif isinstance(self.axis, PeriodIndex):
            self.binner, self.bins, self.binlabels = self._group_periods()
        else:
            raise ValueError('Invalid index: %s' % type(self.axis))

    def _group_timestamps(self):
        if self.kind is None or self.kind == 'timestamp':
            binner = self._generate_time_binner()

            # a little hack
            trimmed = False
            if len(binner) > 2 and binner[-2] == self.axis[-1]:
                binner = binner[:-1]
                trimmed = True

            # general version, knowing nothing about relative frequencies
            bins = lib.generate_bins_dt64(self.axis.asi8, binner.asi8,
                                          self.closed)

            if self.label == 'right':
                labels = binner[1:]
            elif not trimmed:
                labels = binner[:-1]
            else:
                labels = binner

            return binner, bins, labels
        elif self.kind == 'period':
            index = PeriodIndex(start=self.axis[0], end=self.axis[-1],
                                freq=self.freq)

            end_stamps = (index + 1).asfreq('D', 's').to_timestamp()
            bins = self.axis.searchsorted(end_stamps, side='left')

            return index, bins, index

    def _group_periods(self):
        if self.kind is None or self.kind == 'period':
            # Start vs. end of period
            memb = self.axis.asfreq(self.freq)

            if len(memb) > 1:
                rng = np.arange(memb.values[0], memb.values[-1] + 1)
                bins = memb.searchsorted(rng, side='right')
            else:
                bins = np.array([], dtype=np.int32)

            index = period_range(memb[0], memb[-1], freq=self.freq)
            return index, bins, index
        else:
            # Convert to timestamps
            pass

    def _generate_time_binner(self):
        offset = self.freq
        if isinstance(offset, basestring):
            offset = to_offset(offset)

        if not isinstance(offset, DateOffset):
            raise ValueError("Rule not a recognized offset")

        first, last = _get_range_edges(self.axis, self.begin, self.end,
                                       offset, closed=self.closed)
        binner = DatetimeIndex(freq=offset, start=first, end=last,
                               periods=self.nperiods)

        return binner

    @property
    def downsamples(self):
        return len(self.binlabels) < len(self.axis)

    @property
    def names(self):
        return [self.axis.name]

    @property
    def levels(self):
        return [self.binlabels]

    @cache_readonly
    def ngroups(self):
        return len(self.binlabels)

    @cache_readonly
    def result_index(self):
        return self.binlabels


def _get_range_edges(axis, begin, end, offset, closed='left'):
    if begin is None:
        if closed == 'left':
            first = Timestamp(offset.rollback(axis[0]))
        else:
            first = Timestamp(axis[0] - offset)
    else:
        first = Timestamp(offset.rollback(begin))

    if end is None:
        last = Timestamp(axis[-1] + offset)
        # last = Timestamp(offset.rollforward(axis[-1]))
    else:
        last = Timestamp(offset.rollforward(end))

    return first, last

def asfreq(obj, freq, method=None, how=None):
    """
    Utility frequency conversion method for Series/DataFrame
    """
    if isinstance(obj.index, PeriodIndex):
        if method is not None:
            raise NotImplementedError

        if how is None:
            how = 'E'

        new_index = obj.index.asfreq(freq, how=how)
        new_obj = obj.copy()
        new_obj.index = new_index
        return new_obj
    else:
        if len(obj.index) == 0:
            return obj.copy()
        dti = date_range(obj.index[0], obj.index[-1], freq=freq)
        return obj.reindex(dti, method=method)

def values_at_time(obj, time, tz=None, asof=False):
    """
    Select values at particular time of day (e.g. 9:30AM)

    Parameters
    ----------
    time : datetime.time or string
    tz : string or pytz.timezone
        Time zone for time. Corresponding timestamps would be converted to
        time zone of the TimeSeries

    Returns
    -------
    values_at_time : TimeSeries
    """
    from dateutil.parser import parse

    if asof:
        raise NotImplementedError
    if tz:
        raise NotImplementedError

    if not isinstance(obj.index, DatetimeIndex):
        raise NotImplementedError

    if isinstance(time, basestring):
        time = parse(time).time()

    # TODO: time object with tzinfo?

    mus = _time_to_microsecond(time)
    indexer = lib.values_at_time(obj.index.asi8, mus)
    indexer = com._ensure_platform_int(indexer)
    return obj.take(indexer)

def _time_to_microsecond(time):
    seconds = time.hour * 60 * 60 + 60 * time.minute + time.second
    return 1000000 * seconds + time.microsecond
