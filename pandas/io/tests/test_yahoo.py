import unittest
import nose
from datetime import datetime

from pandas.util.py3compat import StringIO, BytesIO

import pandas as pd
import pandas.io.data as web
from pandas.util.testing import (network, assert_frame_equal,
                                 assert_series_equal,
                                 assert_almost_equal)
from numpy.testing.decorators import slow

import urllib2


class TestYahoo(unittest.TestCase):

    @slow
    @network
    def test_yahoo(self):
        # asserts that yahoo is minimally working and that it throws
        # an excecption when DataReader can't get a 200 response from
        # yahoo
        start = datetime(2010, 1, 1)
        end = datetime(2013, 01, 27)

        try:
            self.assertEquals(
                web.DataReader("F", 'yahoo', start, end)['Close'][-1],
                13.68)

            self.assertRaises(
                Exception,
                lambda: web.DataReader("NON EXISTENT TICKER", 'yahoo',
                                      start, end))
        except urllib2.URLError:
            try:
                urllib2.urlopen('http://www.google.com')
            except urllib2.URLError:
                raise nose.SkipTest
            else:
                raise


    @slow
    @network
    def test_get_quote(self):
        df = web.get_quote_yahoo(pd.Series(['GOOG', 'AAPL', 'GOOG']))
        assert_series_equal(df.ix[0], df.ix[2])


    @slow
    @network
    def test_get_components(self):

        df = web.get_components_yahoo('^DJI') #Dow Jones
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 30

        df = web.get_components_yahoo('^GDAXI') #DAX
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 30
        assert df[df.name.str.contains('adidas', case=False)].index == 'ADS.DE'

        df = web.get_components_yahoo('^NDX') #NASDAQ-100
        assert isinstance(df, pd.DataFrame)
        #assert len(df) == 100
        #Usual culprits, should be around for a while
        assert 'AAPL' in df.index
        assert 'GOOG' in df.index
        assert 'AMZN' in df.index

    @slow
    @network
    def test_get_data(self):
        import numpy as np
        #single symbol
        #http://finance.yahoo.com/q/hp?s=GOOG&a=09&b=08&c=2010&d=09&e=10&f=2010&g=d
        df = web.get_data_yahoo('GOOG')
        assert df.Volume.ix['OCT-08-2010'] == 2859200

        sl = ['AAPL', 'AMZN', 'GOOG']
        pan = web.get_data_yahoo(sl, '2012')
        ts = pan.Close.GOOG.index[pan.Close.AAPL > pan.Close.GOOG]
        # the provider results are subject to change, disabled. GH2847
        # assert result == expected
        assert ts[0].dayofyear == 96

        dfi = web.get_components_yahoo('^DJI')
        pan = web.get_data_yahoo(dfi, 'JAN-01-12', 'JAN-31-12')
        expected = [19.02, 28.23, 25.39]
        result = pan.Close.ix['01-18-12'][['GE', 'MSFT', 'INTC']].tolist()
        assert result == expected

        pan = web.get_data_yahoo(dfi, 'JAN-01-12', 'JAN-31-12',
                                 adjust_price=True)
        expected = [18.38, 27.45, 24.54]
        result = pan.Close.ix['01-18-12'][['GE', 'MSFT', 'INTC']].tolist()
        # the provider results are subject to change, disabled. GH2847
        # assert result == expected

        # sanity checking
        t= np.array(result)
        assert     np.issubdtype(t.dtype, np.floating)
        assert     t.shape == (3,)

        pan = web.get_data_yahoo(dfi, '2011', ret_index=True)
        d = [[ 1.01757469,  1.01130524,  1.02414183],
             [ 1.00292912,  1.00770812,  1.01735194],
             [ 1.00820152,  1.00462487,  1.01320257],
             [ 1.08025776,  0.99845838,  1.00113165]]

        expected = pd.DataFrame(d)
        result = pan.Ret_Index.ix['01-18-11':'01-21-11'][['GE', 'INTC', 'MSFT']]
        # the provider results are subject to change, disabled. GH2847
        # assert_almost_equal(result.values, expected.values)

        # sanity checking
        t= np.array(result)
        assert     np.issubdtype(t.dtype, np.floating)
        assert     t.shape == (4, 3)


if __name__ == '__main__':
    nose.runmodule(argv=[__file__, '-vvs', '-x', '--pdb', '--pdb-failure'],
                   exit=False)
