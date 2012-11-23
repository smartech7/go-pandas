from vbench.benchmark import Benchmark
from datetime import datetime

common_setup = """from pandas_vb_common import *
"""

#----------------------------------------------------------------------
# Series constructors

setup = common_setup + """
data = np.random.randn(100)
index = Index(np.arange(100))
"""

series_constructor_ndarray = \
    Benchmark("Series(data, index=index)", setup=setup,
              name='series_constructor_ndarray')

setup = common_setup + """
arr = np.random.randn(100, 100)
"""

frame_constructor_ndarray = \
    Benchmark("DataFrame(arr)", setup=setup,
              name='frame_constructor_ndarray')
