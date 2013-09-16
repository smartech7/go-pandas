from vbench.benchmark import Benchmark
from datetime import datetime

common_setup = """from pandas_vb_common import *
"""

SECTION = 'Binary ops'

#----------------------------------------------------------------------
# binary ops

#----------------------------------------------------------------------
# add

setup = common_setup + """
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
"""
frame_add = \
    Benchmark("df + df2", setup, name='frame_add',
              start_date=datetime(2012, 1, 1))

setup = common_setup + """
import pandas.computation.expressions as expr
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
expr.set_numexpr_threads(1)
"""

frame_add_st = \
    Benchmark("df + df2", setup, name='frame_add_st',cleanup="expr.set_numexpr_threads()",
              start_date=datetime(2013, 2, 26))

setup = common_setup + """
import pandas.computation.expressions as expr
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
expr.set_use_numexpr(False)
"""
frame_add_no_ne = \
    Benchmark("df + df2", setup, name='frame_add_no_ne',cleanup="expr.set_use_numexpr(True)",
              start_date=datetime(2013, 2, 26))

#----------------------------------------------------------------------
# mult

setup = common_setup + """
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
"""
frame_mult = \
    Benchmark("df * df2", setup, name='frame_mult',
              start_date=datetime(2012, 1, 1))

setup = common_setup + """
import pandas.computation.expressions as expr
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
expr.set_numexpr_threads(1)
"""
frame_mult_st = \
    Benchmark("df * df2", setup, name='frame_mult_st',cleanup="expr.set_numexpr_threads()",
              start_date=datetime(2013, 2, 26))

setup = common_setup + """
import pandas.computation.expressions as expr
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
expr.set_use_numexpr(False)
"""
frame_mult_no_ne = \
    Benchmark("df * df2", setup, name='frame_mult_no_ne',cleanup="expr.set_use_numexpr(True)",
              start_date=datetime(2013, 2, 26))

#----------------------------------------------------------------------
# multi and

setup = common_setup + """
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
"""
frame_multi_and = \
    Benchmark("df[(df>0) & (df2>0)]", setup, name='frame_multi_and',
              start_date=datetime(2012, 1, 1))

setup = common_setup + """
import pandas.computation.expressions as expr
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
expr.set_numexpr_threads(1)
"""
frame_multi_and_st = \
    Benchmark("df[(df>0) & (df2>0)]", setup, name='frame_multi_and_st',cleanup="expr.set_numexpr_threads()",
              start_date=datetime(2013, 2, 26))

setup = common_setup + """
import pandas.computation.expressions as expr
df  = DataFrame(np.random.randn(20000, 100))
df2 = DataFrame(np.random.randn(20000, 100))
expr.set_use_numexpr(False)
"""
frame_multi_and_no_ne = \
    Benchmark("df[(df>0) & (df2>0)]", setup, name='frame_multi_and_no_ne',cleanup="expr.set_use_numexpr(True)",
              start_date=datetime(2013, 2, 26))
