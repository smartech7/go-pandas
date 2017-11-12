# -*- coding: utf-8 -*-
# cython: profile=False

from cpython.datetime cimport datetime

from numpy cimport int64_t, int32_t

from np_datetime cimport pandas_datetimestruct


cdef class _TSObject:
    cdef:
        pandas_datetimestruct dts      # pandas_datetimestruct
        int64_t value               # numpy dt64
        object tzinfo


cdef convert_to_tsobject(object ts, object tz, object unit,
                         bint dayfirst, bint yearfirst)

cdef _TSObject convert_datetime_to_tsobject(datetime ts, object tz,
                                            int32_t nanos=*)

cdef void _localize_tso(_TSObject obj, object tz)

cpdef int64_t tz_convert_single(int64_t val, object tz1, object tz2)

cdef int64_t get_datetime64_nanos(object val) except? -1

cpdef int64_t pydt_to_i8(object pydt) except? -1
