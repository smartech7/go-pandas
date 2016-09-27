from .pandas_vb_common import *
from pandas.core import common as com

try:
    from cStringIO import StringIO
except ImportError:
    from io import StringIO

try:
    from pandas.util.testing import test_parallel

    have_real_test_parallel = True
except ImportError:
    have_real_test_parallel = False


    def test_parallel(num_threads=1):

        def wrapper(fname):
            return fname

        return wrapper


class nogil_groupby_base(object):
    goal_time = 0.2

    def setup(self):
        self.N = 1000000
        self.ngroups = 1000
        np.random.seed(1234)
        self.df = DataFrame({'key': np.random.randint(0, self.ngroups, size=self.N), 'data': np.random.randn(self.N), })
        if (not have_real_test_parallel):
            raise NotImplementedError


class nogil_groupby_count_2(nogil_groupby_base):

    def time_nogil_groupby_count_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].count()


class nogil_groupby_last_2(nogil_groupby_base):

    def time_nogil_groupby_last_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].last()


class nogil_groupby_max_2(nogil_groupby_base):

    def time_nogil_groupby_max_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].max()


class nogil_groupby_mean_2(nogil_groupby_base):

    def time_nogil_groupby_mean_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].mean()


class nogil_groupby_min_2(nogil_groupby_base):

    def time_nogil_groupby_min_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].min()


class nogil_groupby_prod_2(nogil_groupby_base):

    def time_nogil_groupby_prod_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].prod()


class nogil_groupby_sum_2(nogil_groupby_base):

    def time_nogil_groupby_sum_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].sum()


class nogil_groupby_sum_4(nogil_groupby_base):

    def time_nogil_groupby_sum_4(self):
        self.pg4()

    def f(self):
        self.df.groupby('key')['data'].sum()

    def g4(self):
        for i in range(4):
            self.f()

    @test_parallel(num_threads=4)
    def pg4(self):
        self.f()


class nogil_groupby_sum_8(nogil_groupby_base):

    def time_nogil_groupby_sum_8(self):
        self.pg8()

    def f(self):
        self.df.groupby('key')['data'].sum()

    def g8(self):
        for i in range(8):
            self.f()

    @test_parallel(num_threads=8)
    def pg8(self):
        self.f()


class nogil_groupby_var_2(nogil_groupby_base):

    def time_nogil_groupby_var_2(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.df.groupby('key')['data'].var()


class nogil_groupby_groups(object):
    goal_time = 0.2

    def setup(self):
        np.random.seed(1234)
        self.size = 2**22
        self.ngroups = 100
        self.data = Series(np.random.randint(0, self.ngroups, size=self.size))
        if (not have_real_test_parallel):
            raise NotImplementedError

    def f(self):
        self.data.groupby(self.data).groups


class nogil_groupby_groups_2(nogil_groupby_groups):

    def time_nogil_groupby_groups(self):
        self.pg2()

    @test_parallel(num_threads=2)
    def pg2(self):
        self.f()


class nogil_groupby_groups_4(nogil_groupby_groups):

    def time_nogil_groupby_groups(self):
        self.pg4()

    @test_parallel(num_threads=4)
    def pg4(self):
        self.f()


class nogil_groupby_groups_8(nogil_groupby_groups):

    def time_nogil_groupby_groups(self):
        self.pg8()

    @test_parallel(num_threads=8)
    def pg8(self):
        self.f()


class nogil_take1d_float64(object):
    goal_time = 0.2

    def setup(self):
        self.N = 1000000
        self.ngroups = 1000
        np.random.seed(1234)
        self.df = DataFrame({'key': np.random.randint(0, self.ngroups, size=self.N), 'data': np.random.randn(self.N), })
        if (not have_real_test_parallel):
            raise NotImplementedError
        self.N = 10000000.0
        self.df = DataFrame({'int64': np.arange(self.N, dtype='int64'), 'float64': np.arange(self.N, dtype='float64'), })
        self.indexer = np.arange(100, (len(self.df) - 100))

    def time_nogil_take1d_float64(self):
        self.take_1d_pg2_int64()

    @test_parallel(num_threads=2)
    def take_1d_pg2_int64(self):
        com.take_1d(self.df.int64.values, self.indexer)

    @test_parallel(num_threads=2)
    def take_1d_pg2_float64(self):
        com.take_1d(self.df.float64.values, self.indexer)


class nogil_take1d_int64(object):
    goal_time = 0.2

    def setup(self):
        self.N = 1000000
        self.ngroups = 1000
        np.random.seed(1234)
        self.df = DataFrame({'key': np.random.randint(0, self.ngroups, size=self.N), 'data': np.random.randn(self.N), })
        if (not have_real_test_parallel):
            raise NotImplementedError
        self.N = 10000000.0
        self.df = DataFrame({'int64': np.arange(self.N, dtype='int64'), 'float64': np.arange(self.N, dtype='float64'), })
        self.indexer = np.arange(100, (len(self.df) - 100))

    def time_nogil_take1d_int64(self):
        self.take_1d_pg2_float64()

    @test_parallel(num_threads=2)
    def take_1d_pg2_int64(self):
        com.take_1d(self.df.int64.values, self.indexer)

    @test_parallel(num_threads=2)
    def take_1d_pg2_float64(self):
        com.take_1d(self.df.float64.values, self.indexer)


class nogil_kth_smallest(object):
    number = 1
    repeat = 5

    def setup(self):
        if (not have_real_test_parallel):
            raise NotImplementedError
        np.random.seed(1234)
        self.N = 10000000
        self.k = 500000
        self.a = np.random.randn(self.N)
        self.b = self.a.copy()
        self.kwargs_list = [{'arr': self.a}, {'arr': self.b}]

    def time_nogil_kth_smallest(self):
        @test_parallel(num_threads=2, kwargs_list=self.kwargs_list)
        def run(arr):
            algos.kth_smallest(arr, self.k)
        run()


class nogil_datetime_fields(object):
    goal_time = 0.2

    def setup(self):
        self.N = 100000000
        self.dti = pd.date_range('1900-01-01', periods=self.N, freq='D')
        self.period = self.dti.to_period('D')
        if (not have_real_test_parallel):
            raise NotImplementedError

    def time_datetime_field_year(self):
        @test_parallel(num_threads=2)
        def run(dti):
            dti.year
        run(self.dti)

    def time_datetime_field_day(self):
        @test_parallel(num_threads=2)
        def run(dti):
            dti.day
        run(self.dti)

    def time_datetime_field_daysinmonth(self):
        @test_parallel(num_threads=2)
        def run(dti):
            dti.days_in_month
        run(self.dti)

    def time_datetime_field_normalize(self):
        @test_parallel(num_threads=2)
        def run(dti):
            dti.normalize()
        run(self.dti)

    def time_datetime_to_period(self):
        @test_parallel(num_threads=2)
        def run(dti):
            dti.to_period('S')
        run(self.dti)

    def time_period_to_datetime(self):
        @test_parallel(num_threads=2)
        def run(period):
            period.to_timestamp()
        run(self.period)


class nogil_rolling_algos_slow(object):
    goal_time = 0.2

    def setup(self):
        self.win = 100
        np.random.seed(1234)
        self.arr = np.random.rand(100000)
        if (not have_real_test_parallel):
            raise NotImplementedError

    def time_nogil_rolling_median(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_median(arr, win)
        run(self.arr, self.win)


class nogil_rolling_algos_fast(object):
    goal_time = 0.2

    def setup(self):
        self.win = 100
        np.random.seed(1234)
        self.arr = np.random.rand(1000000)
        if (not have_real_test_parallel):
            raise NotImplementedError

    def time_nogil_rolling_mean(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_mean(arr, win)
        run(self.arr, self.win)

    def time_nogil_rolling_min(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_min(arr, win)
        run(self.arr, self.win)

    def time_nogil_rolling_max(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_max(arr, win)
        run(self.arr, self.win)

    def time_nogil_rolling_var(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_var(arr, win)
        run(self.arr, self.win)

    def time_nogil_rolling_skew(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_skew(arr, win)
        run(self.arr, self.win)

    def time_nogil_rolling_kurt(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_kurt(arr, win)
        run(self.arr, self.win)

    def time_nogil_rolling_std(self):
        @test_parallel(num_threads=2)
        def run(arr, win):
            rolling_std(arr, win)
        run(self.arr, self.win)


class nogil_read_csv(object):
    number = 1
    repeat = 5

    def setup(self):
        if (not have_real_test_parallel):
            raise NotImplementedError
        # Using the values
        self.df = DataFrame(np.random.randn(10000, 50))
        self.df.to_csv('__test__.csv')

        self.rng = date_range('1/1/2000', periods=10000)
        self.df_date_time = DataFrame(np.random.randn(10000, 50), index=self.rng)
        self.df_date_time.to_csv('__test_datetime__.csv')

        self.df_object = DataFrame('foo', index=self.df.index, columns=self.create_cols('object'))
        self.df_object.to_csv('__test_object__.csv')

    def create_cols(self, name):
        return [('%s%03d' % (name, i)) for i in range(5)]

    @test_parallel(num_threads=2)
    def pg_read_csv(self):
        read_csv('__test__.csv', sep=',', header=None, float_precision=None)

    def time_nogil_read_csv(self):
        self.pg_read_csv()

    @test_parallel(num_threads=2)
    def pg_read_csv_object(self):
        read_csv('__test_object__.csv', sep=',')

    def time_nogil_read_csv_object(self):
        self.pg_read_csv_object()

    @test_parallel(num_threads=2)
    def pg_read_csv_datetime(self):
        read_csv('__test_datetime__.csv', sep=',', header=None)

    def time_nogil_read_csv_datetime(self):
        self.pg_read_csv_datetime()
