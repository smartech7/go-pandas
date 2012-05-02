from datetime import datetime, timedelta

import numpy as np

from pandas import Series, TimeSeries, DataFrame, isnull, notnull

from pandas.tseries.index import date_range
from pandas.tseries.offsets import Minute, bday
from pandas.tseries.period import period_range
from pandas.tseries.resample import DatetimeIndex, TimeGrouper
import pandas.tseries.offsets as offsets

import unittest
import nose

from pandas.util.testing import assert_series_equal, assert_almost_equal
import pandas.util.testing as tm

class TestResample(unittest.TestCase):

    def setUp(self):
        dti = DatetimeIndex(start=datetime(2005,1,1),
                            end=datetime(2005,1,10), freq='Min')

        self.series = Series(np.random.rand(len(dti)), dti)

    def test_custom_grouper(self):

        dti = DatetimeIndex(freq='Min', start=datetime(2005,1,1),
                            end=datetime(2005,1,10))

        data = np.array([1]*len(dti))
        s = Series(data, index=dti)

        b = TimeGrouper(Minute(5))
        g = s.groupby(b)

        # check all cython functions work
        funcs = ['add', 'mean', 'prod', 'ohlc', 'min', 'max', 'var']
        for f in funcs:
            g._cython_agg_general(f)

        b = TimeGrouper(Minute(5), closed='right', label='right')
        g = s.groupby(b)
        # check all cython functions work
        funcs = ['add', 'mean', 'prod', 'ohlc', 'min', 'max', 'var']
        for f in funcs:
            g._cython_agg_general(f)

        self.assertEquals(g.ngroups, 2593)
        self.assert_(notnull(g.mean()).all())

        # construct expected val
        arr = [1] + [5] * 2592
        idx = dti[0:-1:5]
        idx = idx.append(DatetimeIndex([np.datetime64(dti[-1])]))
        expect = Series(arr, index=idx)

        # cython returns float for now
        result = g.agg(np.sum)
        assert_series_equal(result, expect.astype(float))

        data = np.random.rand(len(dti), 10)
        df = DataFrame(data, index=dti)
        r = df.groupby(b).agg(np.sum)

        self.assertEquals(len(r.columns), 10)
        self.assertEquals(len(r.index), 2593)

    def test_resample_basic(self):
        rng = date_range('1/1/2000 00:00:00', '1/1/2000 00:13:00', freq='min')
        s = Series(np.random.randn(14), index=rng)
        result = s.resample('5min', how='mean', closed='right', label='right')
        expected = Series([s[0], s[1:6].mean(), s[6:11].mean(), s[11:].mean()],
                          index=date_range('1/1/2000', periods=4, freq='5min'))
        assert_series_equal(result, expected)

        result = s.resample('5min', how='mean', closed='left', label='right')
        expected = Series([s[:5].mean(), s[5:10].mean(), s[10:].mean()],
                          index=date_range('1/1/2000 00:05', periods=3,
                                           freq='5min'))
        assert_series_equal(result, expected)

        s = self.series
        result = s.resample('5Min', how='last')
        grouper = TimeGrouper(Minute(5), closed='right', label='right')
        expect = s.groupby(grouper).agg(lambda x: x[-1])
        assert_series_equal(result, expect)

        # from daily
        dti = DatetimeIndex(start=datetime(2005,1,1), end=datetime(2005,1,10),
                            freq='D')

        s = Series(np.random.rand(len(dti)), dti)

        # to weekly
        result = s.resample('w-sun', how='last')

        self.assertEquals(len(result), 3)
        self.assert_((result.index.dayofweek == [6,6,6]).all())
        self.assertEquals(result.irow(0), s['1/2/2005'])
        self.assertEquals(result.irow(1), s['1/9/2005'])
        self.assertEquals(result.irow(2), s.irow(-1))

        result = s.resample('W-MON', how='last')
        self.assertEquals(len(result), 2)
        self.assert_((result.index.dayofweek == [0,0]).all())
        self.assertEquals(result.irow(0), s['1/3/2005'])
        self.assertEquals(result.irow(1), s['1/10/2005'])

        result = s.resample('W-TUE', how='last')
        self.assertEquals(len(result), 2)
        self.assert_((result.index.dayofweek == [1,1]).all())
        self.assertEquals(result.irow(0), s['1/4/2005'])
        self.assertEquals(result.irow(1), s['1/10/2005'])

        result = s.resample('W-WED', how='last')
        self.assertEquals(len(result), 2)
        self.assert_((result.index.dayofweek == [2,2]).all())
        self.assertEquals(result.irow(0), s['1/5/2005'])
        self.assertEquals(result.irow(1), s['1/10/2005'])

        result = s.resample('W-THU', how='last')
        self.assertEquals(len(result), 2)
        self.assert_((result.index.dayofweek == [3,3]).all())
        self.assertEquals(result.irow(0), s['1/6/2005'])
        self.assertEquals(result.irow(1), s['1/10/2005'])

        result = s.resample('W-FRI', how='last')
        self.assertEquals(len(result), 2)
        self.assert_((result.index.dayofweek == [4,4]).all())
        self.assertEquals(result.irow(0), s['1/7/2005'])
        self.assertEquals(result.irow(1), s['1/10/2005'])

        # to biz day
        result = s.resample('B', how='last')
        self.assertEquals(len(result), 6)
        self.assert_((result.index.dayofweek == [0,1,2,3,4,0]).all())
        self.assertEquals(result.irow(0), s['1/3/2005'])
        self.assertEquals(result.irow(1), s['1/4/2005'])
        self.assertEquals(result.irow(5), s['1/10/2005'])

    def test_resample_frame_basic(self):
        df = tm.makeTimeDataFrame()

        b = TimeGrouper('M')
        g = df.groupby(b)

        # check all cython functions work
        funcs = ['add', 'mean', 'prod', 'min', 'max', 'var']
        for f in funcs:
            g._cython_agg_general(f)

        result = df.resample('A')
        assert_series_equal(result['A'], df['A'].resample('A'))

        result = df.resample('M')
        assert_series_equal(result['A'], df['A'].resample('M'))

        df.resample('M', kind='period')
        df.resample('W-WED', kind='period')

    def test_resample_loffset(self):
        rng = date_range('1/1/2000 00:00:00', '1/1/2000 00:13:00', freq='min')
        s = Series(np.random.randn(14), index=rng)

        result = s.resample('5min', how='mean', closed='right', label='right',
                            loffset=timedelta(minutes=1))
        idx = date_range('1/1/2000', periods=4, freq='5min')
        expected = Series([s[0], s[1:6].mean(), s[6:11].mean(), s[11:].mean()],
                          index=idx + timedelta(minutes=1))
        assert_series_equal(result, expected)

        expected = s.resample('5min', how='mean', closed='right', label='right',
                              loffset='1min')
        assert_series_equal(result, expected)

        expected = s.resample('5min', how='mean', closed='right', label='right',
                              loffset=Minute(1))
        assert_series_equal(result, expected)

        self.assert_(result.index.freq == Minute(5))

                # from daily
        dti = DatetimeIndex(start=datetime(2005,1,1), end=datetime(2005,1,10),
                            freq='D')
        ser = Series(np.random.rand(len(dti)), dti)

        # to weekly
        result = ser.resample('w-sun', how='last')
        expected = ser.resample('w-sun', how='last', loffset=-bday)
        self.assertEqual(result.index[0] - bday, expected.index[0])

    def test_resample_upsample(self):
        # from daily
        dti = DatetimeIndex(start=datetime(2005,1,1), end=datetime(2005,1,10),
                            freq='D')

        s = Series(np.random.rand(len(dti)), dti)

        # to minutely, by padding
        result = s.resample('Min', fill_method='pad')
        self.assertEquals(len(result), 12961)
        self.assertEquals(result[0], s[0])
        self.assertEquals(result[-1], s[-1])

    def test_resample_ohlc(self):
        s = self.series

        grouper = TimeGrouper(Minute(5), closed='right', label='right')
        expect = s.groupby(grouper).agg(lambda x: x[-1])
        result = s.resample('5Min', how='ohlc')

        self.assertEquals(len(result), len(expect))
        self.assertEquals(len(result.columns), 4)

        xs = result.irow(-1)
        self.assertEquals(xs['open'], s[-5])
        self.assertEquals(xs['high'], s[-5:].max())
        self.assertEquals(xs['low'], s[-5:].min())
        self.assertEquals(xs['close'], s[-1])

        xs = result.irow(1)
        self.assertEquals(xs['open'], s[1])
        self.assertEquals(xs['high'], s[1:6].max())
        self.assertEquals(xs['low'], s[1:6].min())
        self.assertEquals(xs['close'], s[5])

    def test_resample_reresample(self):
        dti = DatetimeIndex(start=datetime(2005,1,1), end=datetime(2005,1,10),
                            freq='D')
        s = Series(np.random.rand(len(dti)), dti)
        bs = s.resample('B')
        result = bs.resample('8H')
        self.assertEquals(len(result), 22)
        self.assert_(isinstance(result.index.freq, offsets.DateOffset))
        self.assert_(result.index.freq == offsets.Hour(8))

    def test_resample_timestamp_to_period(self):
        ts = _simple_ts('1/1/1990', '1/1/2000')

        result = ts.resample('A-DEC', kind='period')
        expected = ts.resample('A-DEC')
        expected.index = period_range('1990', '2000', freq='a-dec')
        assert_series_equal(result, expected)

        result = ts.resample('A-JUN', kind='period')
        expected = ts.resample('A-JUN')
        expected.index = period_range('1990', '2000', freq='a-jun')
        assert_series_equal(result, expected)

        result = ts.resample('M', kind='period')
        expected = ts.resample('M')
        expected.index = period_range('1990-01', '2000-01', freq='M')
        assert_series_equal(result, expected)

        result = ts.resample('M', kind='period')
        expected = ts.resample('M')
        expected.index = period_range('1990-01', '2000-01', freq='M')
        assert_series_equal(result, expected)

    def test_ohlc_5min(self):
        def _ohlc(group):
            if isnull(group).all():
                return np.repeat(np.nan, 4)
            return [group[0], group.max(), group.min(), group[-1]]

        rng = date_range('1/1/2000 00:00:00', '1/1/2000 5:59:50',
                         freq='10s')
        ts = Series(np.random.randn(len(rng)), index=rng)

        resampled = ts.resample('5min', how='ohlc')

        self.assert_((resampled.ix['1/1/2000 00:00'] == ts[0]).all())

        exp = _ohlc(ts[1:31])
        self.assert_((resampled.ix['1/1/2000 00:05'] == exp).all())

        exp = _ohlc(ts['1/1/2000 5:55:01':])
        self.assert_((resampled.ix['1/1/2000 6:00:00'] == exp).all())

    def test_downsample_non_unique(self):
        rng = date_range('1/1/2000', '2/29/2000')
        rng2 = rng.repeat(5).values
        ts = Series(np.random.randn(len(rng2)), index=rng2)

        result = ts.resample('M', how='mean')

        expected = ts.groupby(lambda x: x.month).mean()
        self.assertEquals(len(result), 2)
        assert_almost_equal(result[0], expected[1])
        assert_almost_equal(result[1], expected[2])

    def test_asfreq_non_unique(self):
        # GH #1077
        rng = date_range('1/1/2000', '2/29/2000')
        rng2 = rng.repeat(2).values
        ts = Series(np.random.randn(len(rng2)), index=rng2)

        self.assertRaises(Exception, ts.asfreq, 'B')


def _simple_ts(start, end, freq='D'):
    rng = date_range(start, end, freq=freq)
    return Series(np.random.randn(len(rng)), index=rng)

def _simple_pts(start, end, freq='D'):
    rng = period_range(start, end, freq=freq)
    return TimeSeries(np.random.randn(len(rng)), index=rng)


from pandas.tseries.frequencies import MONTHS, DAYS
from pandas.util.compat import product

class TestResamplePeriodIndex(unittest.TestCase):

    def test_basic_downsample(self):
        ts = _simple_pts('1/1/1990', '6/30/1995', freq='M')
        result = ts.resample('a-dec')

        expected = ts.groupby(ts.index.year).mean()
        expected.index = period_range('1/1/1990', '6/30/1995',
                                      freq='a-dec')
        assert_series_equal(result, expected)

        # this is ok
        assert_series_equal(ts.resample('a-dec'), result)
        assert_series_equal(ts.resample('a'), result)

    def test_not_subperiod(self):
        # These are incompatible period rules for resampling
        ts = _simple_pts('1/1/1990', '6/30/1995', freq='w-wed')
        self.assertRaises(ValueError, ts.resample, 'a-dec')
        self.assertRaises(ValueError, ts.resample, 'q-mar')
        self.assertRaises(ValueError, ts.resample, 'M')
        self.assertRaises(ValueError, ts.resample, 'w-thu')

    def test_basic_upsample(self):
        ts = _simple_pts('1/1/1990', '6/30/1995', freq='M')
        result = ts.resample('a-dec')

        resampled = result.resample('D', fill_method='ffill', convention='end')

        expected = result.to_timestamp('D', how='end')
        expected = expected.asfreq('D', 'ffill').to_period()

        assert_series_equal(resampled, expected)

    def test_annual_upsample(self):
        targets = ['D', 'B', 'M']

        for month in MONTHS:
            ts = _simple_pts('1/1/1990', '12/31/1995', freq='A-%s' % month)

            for targ, conv, meth in product(targets, ['start', 'end'],
                                            ['ffill', 'bfill']):
                result = ts.resample(targ, fill_method=meth,
                                     convention=conv)
                expected = result.to_timestamp(targ, how=conv)
                expected = expected.asfreq(targ, meth).to_period()
                assert_series_equal(result, expected)

        df = DataFrame({'a' : ts})
        rdf = df.resample('D', fill_method='ffill')
        exp = df['a'].resample('D', fill_method='ffill')
        assert_series_equal(rdf['a'], exp)

    def test_quarterly_upsample(self):
        targets = ['D', 'B', 'M']

        for month in MONTHS:
            ts = _simple_pts('1/1/1990', '12/31/1995', freq='Q-%s' % month)

            for targ, conv in product(targets, ['start', 'end']):
                result = ts.resample(targ, fill_method='ffill',
                                     convention=conv)
                expected = result.to_timestamp(targ, how=conv)
                expected = expected.asfreq(targ, 'ffill').to_period()
                assert_series_equal(result, expected)

    def test_monthly_upsample(self):
        targets = ['D', 'B']

        ts = _simple_pts('1/1/1990', '12/31/1995', freq='M')

        for targ, conv in product(targets, ['start', 'end']):
            result = ts.resample(targ, fill_method='ffill',
                                 convention=conv)
            expected = result.to_timestamp(targ, how=conv)
            expected = expected.asfreq(targ, 'ffill').to_period()
            assert_series_equal(result, expected)

    def test_weekly_upsample(self):
        targets = ['D', 'B']

        for day in DAYS:
            ts = _simple_pts('1/1/1990', '12/31/1995', freq='W-%s' % day)

            for targ, conv in product(targets, ['start', 'end']):
                result = ts.resample(targ, fill_method='ffill',
                                     convention=conv)
                expected = result.to_timestamp(targ, how=conv)
                expected = expected.asfreq(targ, 'ffill').to_period()
                assert_series_equal(result, expected)

    def test_resample_to_timestamps(self):
        ts = _simple_pts('1/1/1990', '12/31/1995', freq='M')

        result = ts.resample('A-DEC', kind='timestamp')
        expected = ts.to_timestamp(how='end').resample('A-DEC')
        assert_series_equal(result, expected)

    def test_resample_to_quarterly(self):
        for month in MONTHS:
            ts = _simple_pts('1990', '1992', freq='A-%s' % month)
            quar_ts = ts.resample('Q-%s' % month, fill_method='ffill')

            stamps = ts.to_timestamp('D', how='end')
            qdates = period_range('1990Q4', '1992Q4', freq='Q-%s' % month)

            expected = stamps.reindex(qdates.to_timestamp('D', 'e'),
                                      method='ffill')
            expected.index = qdates

            assert_series_equal(quar_ts, expected)

class TestTimeGrouper(unittest.TestCase):

    def setUp(self):
        self.ts = Series(np.random.randn(1000),
                         index=date_range('1/1/2000', periods=1000))

    def test_apply(self):
        grouper = TimeGrouper('A', label='right', closed='right')

        grouped = self.ts.groupby(grouper)

        f = lambda x: x.order()[-3:]

        applied = grouped.apply(f)
        expected = self.ts.groupby(lambda x: x.year).apply(f)

        applied.index = applied.index.droplevel(0)
        expected.index = expected.index.droplevel(0)
        assert_series_equal(applied, expected)

    def test_count(self):
        self.ts[::3] = np.nan

        grouper = TimeGrouper('A', label='right', closed='right')
        result = self.ts.resample('A', how='count')

        expected = self.ts.groupby(lambda x: x.year).count()
        expected.index = result.index

        assert_series_equal(result, expected)

    def test_numpy_reduction(self):
        result = self.ts.resample('A', how='prod', closed='right')

        expected = self.ts.groupby(lambda x: x.year).agg(np.prod)
        expected.index = result.index

        assert_series_equal(result, expected)


if __name__ == '__main__':
    nose.runmodule(argv=[__file__,'-vvs','-x','--pdb', '--pdb-failure'],
                   exit=False)

