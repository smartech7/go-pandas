# -*- coding: utf-8 -*-
import warnings
import inspect
import re
from datetime import datetime, timedelta, date

import numpy as np

from pandas._libs import lib, tslib, tslibs, internals as libinternals
from pandas._libs.tslibs import conversion, Timedelta

from pandas import compat
from pandas.compat import range, zip

from pandas.util._validators import validate_bool_kwarg

from pandas.core.dtypes.dtypes import (
    ExtensionDtype, DatetimeTZDtype,
    PandasExtensionDtype,
    CategoricalDtype)
from pandas.core.dtypes.common import (
    _TD_DTYPE, _NS_DTYPE,
    ensure_platform_int,
    is_integer,
    is_dtype_equal,
    is_timedelta64_dtype,
    is_datetime64_dtype, is_datetimetz, is_sparse,
    is_categorical, is_categorical_dtype,
    is_integer_dtype,
    is_datetime64tz_dtype,
    is_bool_dtype,
    is_object_dtype,
    is_float_dtype,
    is_numeric_v_string_like, is_extension_type,
    is_extension_array_dtype,
    is_list_like,
    is_re,
    is_re_compilable,
    pandas_dtype)
from pandas.core.dtypes.cast import (
    maybe_downcast_to_dtype,
    maybe_upcast,
    maybe_promote,
    infer_dtype_from,
    infer_dtype_from_scalar,
    soft_convert_objects,
    maybe_convert_objects,
    astype_nansafe,
    find_common_type,
    maybe_infer_dtype_type)
from pandas.core.dtypes.missing import (
    isna, notna, array_equivalent,
    _isna_compat,
    is_null_datelike_scalar)
import pandas.core.dtypes.concat as _concat
from pandas.core.dtypes.generic import (
    ABCSeries,
    ABCDatetimeIndex,
    ABCExtensionArray,
    ABCIndexClass)

import pandas.core.common as com
import pandas.core.algorithms as algos
import pandas.core.missing as missing
from pandas.core.base import PandasObject

from pandas.core.arrays import Categorical
from pandas.core.sparse.array import SparseArray

from pandas.core.indexes.datetimes import DatetimeIndex
from pandas.core.indexes.timedeltas import TimedeltaIndex
from pandas.core.indexing import check_setitem_lengths

from pandas.io.formats.printing import pprint_thing


class Block(PandasObject):
    """
    Canonical n-dimensional unit of homogeneous dtype contained in a pandas
    data structure

    Index-ignorant; let the container take care of that
    """
    __slots__ = ['_mgr_locs', 'values', 'ndim']
    is_numeric = False
    is_float = False
    is_integer = False
    is_complex = False
    is_datetime = False
    is_datetimetz = False
    is_timedelta = False
    is_bool = False
    is_object = False
    is_categorical = False
    is_sparse = False
    is_extension = False
    _box_to_block_values = True
    _can_hold_na = False
    _can_consolidate = True
    _verify_integrity = True
    _validate_ndim = True
    _ftype = 'dense'
    _concatenator = staticmethod(np.concatenate)

    def __init__(self, values, placement, ndim=None):
        self.ndim = self._check_ndim(values, ndim)
        self.mgr_locs = placement
        self.values = values

        if (self._validate_ndim and self.ndim and
                len(self.mgr_locs) != len(self.values)):
            raise ValueError(
                'Wrong number of items passed {val}, placement implies '
                '{mgr}'.format(val=len(self.values), mgr=len(self.mgr_locs)))

    def _check_ndim(self, values, ndim):
        """ndim inference and validation.

        Infers ndim from 'values' if not provided to __init__.
        Validates that values.ndim and ndim are consistent if and only if
        the class variable '_validate_ndim' is True.

        Parameters
        ----------
        values : array-like
        ndim : int or None

        Returns
        -------
        ndim : int

        Raises
        ------
        ValueError : the number of dimensions do not match
        """
        if ndim is None:
            ndim = values.ndim

        if self._validate_ndim and values.ndim != ndim:
            msg = ("Wrong number of dimensions. values.ndim != ndim "
                   "[{} != {}]")
            raise ValueError(msg.format(values.ndim, ndim))

        return ndim

    @property
    def _holder(self):
        """The array-like that can hold the underlying values.

        None for 'Block', overridden by subclasses that don't
        use an ndarray.
        """
        return None

    @property
    def _consolidate_key(self):
        return (self._can_consolidate, self.dtype.name)

    @property
    def _is_single_block(self):
        return self.ndim == 1

    @property
    def is_view(self):
        """ return a boolean if I am possibly a view """
        return self.values.base is not None

    @property
    def is_datelike(self):
        """ return True if I am a non-datelike """
        return self.is_datetime or self.is_timedelta

    def is_categorical_astype(self, dtype):
        """
        validate that we have a astypeable to categorical,
        returns a boolean if we are a categorical
        """
        if dtype is Categorical or dtype is CategoricalDtype:
            # this is a pd.Categorical, but is not
            # a valid type for astypeing
            raise TypeError("invalid type {0} for astype".format(dtype))

        elif is_categorical_dtype(dtype):
            return True

        return False

    def external_values(self, dtype=None):
        """ return an outside world format, currently just the ndarray """
        return self.values

    def internal_values(self, dtype=None):
        """ return an internal format, currently just the ndarray
        this should be the pure internal API format
        """
        return self.values

    def formatting_values(self):
        """Return the internal values used by the DataFrame/SeriesFormatter"""
        return self.internal_values()

    def get_values(self, dtype=None):
        """
        return an internal format, currently just the ndarray
        this is often overridden to handle to_dense like operations
        """
        if is_object_dtype(dtype):
            return self.values.astype(object)
        return self.values

    def to_dense(self):
        return self.values.view()

    @property
    def _na_value(self):
        return np.nan

    @property
    def fill_value(self):
        return np.nan

    @property
    def mgr_locs(self):
        return self._mgr_locs

    @mgr_locs.setter
    def mgr_locs(self, new_mgr_locs):
        if not isinstance(new_mgr_locs, libinternals.BlockPlacement):
            new_mgr_locs = libinternals.BlockPlacement(new_mgr_locs)

        self._mgr_locs = new_mgr_locs

    @property
    def array_dtype(self):
        """ the dtype to return if I want to construct this block as an
        array
        """
        return self.dtype

    def make_block(self, values, placement=None, ndim=None):
        """
        Create a new block, with type inference propagate any values that are
        not specified
        """
        if placement is None:
            placement = self.mgr_locs
        if ndim is None:
            ndim = self.ndim

        return make_block(values, placement=placement, ndim=ndim)

    def make_block_scalar(self, values):
        """
        Create a ScalarBlock
        """
        return ScalarBlock(values)

    def make_block_same_class(self, values, placement=None, ndim=None,
                              dtype=None):
        """ Wrap given values in a block of same type as self. """
        if dtype is not None:
            # issue 19431 fastparquet is passing this
            warnings.warn("dtype argument is deprecated, will be removed "
                          "in a future release.", DeprecationWarning)
        if placement is None:
            placement = self.mgr_locs
        return make_block(values, placement=placement, ndim=ndim,
                          klass=self.__class__, dtype=dtype)

    def __unicode__(self):

        # don't want to print out all of the items here
        name = pprint_thing(self.__class__.__name__)
        if self._is_single_block:

            result = '{name}: {len} dtype: {dtype}'.format(
                name=name, len=len(self), dtype=self.dtype)

        else:

            shape = ' x '.join(pprint_thing(s) for s in self.shape)
            result = '{name}: {index}, {shape}, dtype: {dtype}'.format(
                name=name, index=pprint_thing(self.mgr_locs.indexer),
                shape=shape, dtype=self.dtype)

        return result

    def __len__(self):
        return len(self.values)

    def __getstate__(self):
        return self.mgr_locs.indexer, self.values

    def __setstate__(self, state):
        self.mgr_locs = libinternals.BlockPlacement(state[0])
        self.values = state[1]
        self.ndim = self.values.ndim

    def _slice(self, slicer):
        """ return a slice of my values """
        return self.values[slicer]

    def reshape_nd(self, labels, shape, ref_items, mgr=None):
        """
        Parameters
        ----------
        labels : list of new axis labels
        shape : new shape
        ref_items : new ref_items

        return a new block that is transformed to a nd block
        """
        return _block2d_to_blocknd(values=self.get_values().T,
                                   placement=self.mgr_locs, shape=shape,
                                   labels=labels, ref_items=ref_items)

    def getitem_block(self, slicer, new_mgr_locs=None):
        """
        Perform __getitem__-like, return result as block.

        As of now, only supports slices that preserve dimensionality.
        """
        if new_mgr_locs is None:
            if isinstance(slicer, tuple):
                axis0_slicer = slicer[0]
            else:
                axis0_slicer = slicer
            new_mgr_locs = self.mgr_locs[axis0_slicer]

        new_values = self._slice(slicer)

        if self._validate_ndim and new_values.ndim != self.ndim:
            raise ValueError("Only same dim slicing is allowed")

        return self.make_block_same_class(new_values, new_mgr_locs)

    @property
    def shape(self):
        return self.values.shape

    @property
    def dtype(self):
        return self.values.dtype

    @property
    def ftype(self):
        return "{dtype}:{ftype}".format(dtype=self.dtype, ftype=self._ftype)

    def merge(self, other):
        return _merge_blocks([self, other])

    def concat_same_type(self, to_concat, placement=None):
        """
        Concatenate list of single blocks of the same type.
        """
        values = self._concatenator([blk.values for blk in to_concat],
                                    axis=self.ndim - 1)
        return self.make_block_same_class(
            values, placement=placement or slice(0, len(values), 1))

    def iget(self, i):
        return self.values[i]

    def set(self, locs, values, check=False):
        """
        Modify Block in-place with new item value

        Returns
        -------
        None
        """
        self.values[locs] = values

    def delete(self, loc):
        """
        Delete given loc(-s) from block in-place.
        """
        self.values = np.delete(self.values, loc, 0)
        self.mgr_locs = self.mgr_locs.delete(loc)

    def apply(self, func, mgr=None, **kwargs):
        """ apply the function to my values; return a block if we are not
        one
        """
        with np.errstate(all='ignore'):
            result = func(self.values, **kwargs)
        if not isinstance(result, Block):
            result = self.make_block(values=_block_shape(result,
                                                         ndim=self.ndim))

        return result

    def fillna(self, value, limit=None, inplace=False, downcast=None,
               mgr=None):
        """ fillna on the block with the value. If we fail, then convert to
        ObjectBlock and try again
        """
        inplace = validate_bool_kwarg(inplace, 'inplace')

        if not self._can_hold_na:
            if inplace:
                return self
            else:
                return self.copy()

        mask = isna(self.values)
        if limit is not None:
            if not is_integer(limit):
                raise ValueError('Limit must be an integer')
            if limit < 1:
                raise ValueError('Limit must be greater than 0')
            if self.ndim > 2:
                raise NotImplementedError("number of dimensions for 'fillna' "
                                          "is currently limited to 2")
            mask[mask.cumsum(self.ndim - 1) > limit] = False

        # fillna, but if we cannot coerce, then try again as an ObjectBlock
        try:
            values, _, _, _ = self._try_coerce_args(self.values, value)
            blocks = self.putmask(mask, value, inplace=inplace)
            blocks = [b.make_block(values=self._try_coerce_result(b.values))
                      for b in blocks]
            return self._maybe_downcast(blocks, downcast)
        except (TypeError, ValueError):

            # we can't process the value, but nothing to do
            if not mask.any():
                return self if inplace else self.copy()

            # operate column-by-column
            def f(m, v, i):
                block = self.coerce_to_target_dtype(value)

                # slice out our block
                if i is not None:
                    block = block.getitem_block(slice(i, i + 1))
                return block.fillna(value,
                                    limit=limit,
                                    inplace=inplace,
                                    downcast=None)

            return self.split_and_operate(mask, f, inplace)

    def split_and_operate(self, mask, f, inplace):
        """
        split the block per-column, and apply the callable f
        per-column, return a new block for each. Handle
        masking which will not change a block unless needed.

        Parameters
        ----------
        mask : 2-d boolean mask
        f : callable accepting (1d-mask, 1d values, indexer)
        inplace : boolean

        Returns
        -------
        list of blocks
        """

        if mask is None:
            mask = np.ones(self.shape, dtype=bool)
        new_values = self.values

        def make_a_block(nv, ref_loc):
            if isinstance(nv, Block):
                block = nv
            elif isinstance(nv, list):
                block = nv[0]
            else:
                # Put back the dimension that was taken from it and make
                # a block out of the result.
                try:
                    nv = _block_shape(nv, ndim=self.ndim)
                except (AttributeError, NotImplementedError):
                    pass
                block = self.make_block(values=nv,
                                        placement=ref_loc)
            return block

        # ndim == 1
        if self.ndim == 1:
            if mask.any():
                nv = f(mask, new_values, None)
            else:
                nv = new_values if inplace else new_values.copy()
            block = make_a_block(nv, self.mgr_locs)
            return [block]

        # ndim > 1
        new_blocks = []
        for i, ref_loc in enumerate(self.mgr_locs):
            m = mask[i]
            v = new_values[i]

            # need a new block
            if m.any():
                nv = f(m, v, i)
            else:
                nv = v if inplace else v.copy()

            block = make_a_block(nv, [ref_loc])
            new_blocks.append(block)

        return new_blocks

    def _maybe_downcast(self, blocks, downcast=None):

        # no need to downcast our float
        # unless indicated
        if downcast is None and self.is_float:
            return blocks
        elif downcast is None and (self.is_timedelta or self.is_datetime):
            return blocks

        if not isinstance(blocks, list):
            blocks = [blocks]
        return _extend_blocks([b.downcast(downcast) for b in blocks])

    def downcast(self, dtypes=None, mgr=None):
        """ try to downcast each item to the dict of dtypes if present """

        # turn it off completely
        if dtypes is False:
            return self

        values = self.values

        # single block handling
        if self._is_single_block:

            # try to cast all non-floats here
            if dtypes is None:
                dtypes = 'infer'

            nv = maybe_downcast_to_dtype(values, dtypes)
            return self.make_block(nv)

        # ndim > 1
        if dtypes is None:
            return self

        if not (dtypes == 'infer' or isinstance(dtypes, dict)):
            raise ValueError("downcast must have a dictionary or 'infer' as "
                             "its argument")

        # operate column-by-column
        # this is expensive as it splits the blocks items-by-item
        def f(m, v, i):

            if dtypes == 'infer':
                dtype = 'infer'
            else:
                raise AssertionError("dtypes as dict is not supported yet")

            if dtype is not None:
                v = maybe_downcast_to_dtype(v, dtype)
            return v

        return self.split_and_operate(None, f, False)

    def astype(self, dtype, copy=False, errors='raise', values=None, **kwargs):
        return self._astype(dtype, copy=copy, errors=errors, values=values,
                            **kwargs)

    def _astype(self, dtype, copy=False, errors='raise', values=None,
                klass=None, mgr=None, **kwargs):
        """Coerce to the new type

        Parameters
        ----------
        dtype : str, dtype convertible
        copy : boolean, default False
            copy if indicated
        errors : str, {'raise', 'ignore'}, default 'ignore'
            - ``raise`` : allow exceptions to be raised
            - ``ignore`` : suppress exceptions. On error return original object

        Returns
        -------
        Block
        """
        errors_legal_values = ('raise', 'ignore')

        if errors not in errors_legal_values:
            invalid_arg = ("Expected value of kwarg 'errors' to be one of {}. "
                           "Supplied value is '{}'".format(
                               list(errors_legal_values), errors))
            raise ValueError(invalid_arg)

        if (inspect.isclass(dtype) and
                issubclass(dtype, (PandasExtensionDtype, ExtensionDtype))):
            msg = ("Expected an instance of {}, but got the class instead. "
                   "Try instantiating 'dtype'.".format(dtype.__name__))
            raise TypeError(msg)

        # may need to convert to categorical
        if self.is_categorical_astype(dtype):

            # deprecated 17636
            if ('categories' in kwargs or 'ordered' in kwargs):
                if isinstance(dtype, CategoricalDtype):
                    raise TypeError(
                        "Cannot specify a CategoricalDtype and also "
                        "`categories` or `ordered`. Use "
                        "`dtype=CategoricalDtype(categories, ordered)`"
                        " instead.")
                warnings.warn("specifying 'categories' or 'ordered' in "
                              ".astype() is deprecated; pass a "
                              "CategoricalDtype instead",
                              FutureWarning, stacklevel=7)

            categories = kwargs.get('categories', None)
            ordered = kwargs.get('ordered', None)
            if com._any_not_none(categories, ordered):
                dtype = CategoricalDtype(categories, ordered)

            if is_categorical_dtype(self.values):
                # GH 10696/18593: update an existing categorical efficiently
                return self.make_block(self.values.astype(dtype, copy=copy))

            return self.make_block(Categorical(self.values, dtype=dtype))

        # convert dtypes if needed
        dtype = pandas_dtype(dtype)

        # astype processing
        if is_dtype_equal(self.dtype, dtype):
            if copy:
                return self.copy()
            return self

        if klass is None:
            if dtype == np.object_:
                klass = ObjectBlock
        try:
            # force the copy here
            if values is None:

                if issubclass(dtype.type,
                              (compat.text_type, compat.string_types)):

                    # use native type formatting for datetime/tz/timedelta
                    if self.is_datelike:
                        values = self.to_native_types()

                    # astype formatting
                    else:
                        values = self.get_values()

                else:
                    values = self.get_values(dtype=dtype)

                # _astype_nansafe works fine with 1-d only
                values = astype_nansafe(values.ravel(), dtype, copy=True)

                # TODO(extension)
                # should we make this attribute?
                try:
                    values = values.reshape(self.shape)
                except AttributeError:
                    pass

            newb = make_block(values, placement=self.mgr_locs,
                              klass=klass)
        except:
            if errors == 'raise':
                raise
            newb = self.copy() if copy else self

        if newb.is_numeric and self.is_numeric:
            if newb.shape != self.shape:
                raise TypeError(
                    "cannot set astype for copy = [{copy}] for dtype "
                    "({dtype} [{itemsize}]) with smaller itemsize than "
                    "current ({newb_dtype} [{newb_size}])".format(
                        copy=copy, dtype=self.dtype.name,
                        itemsize=self.itemsize, newb_dtype=newb.dtype.name,
                        newb_size=newb.itemsize))
        return newb

    def convert(self, copy=True, **kwargs):
        """ attempt to coerce any object types to better types return a copy
        of the block (if copy = True) by definition we are not an ObjectBlock
        here!
        """

        return self.copy() if copy else self

    def _can_hold_element(self, element):
        """ require the same dtype as ourselves """
        dtype = self.values.dtype.type
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            return issubclass(tipo.type, dtype)
        return isinstance(element, dtype)

    def _try_cast_result(self, result, dtype=None):
        """ try to cast the result to our original type, we may have
        roundtripped thru object in the mean-time
        """
        if dtype is None:
            dtype = self.dtype

        if self.is_integer or self.is_bool or self.is_datetime:
            pass
        elif self.is_float and result.dtype == self.dtype:

            # protect against a bool/object showing up here
            if isinstance(dtype, compat.string_types) and dtype == 'infer':
                return result
            if not isinstance(dtype, type):
                dtype = dtype.type
            if issubclass(dtype, (np.bool_, np.object_)):
                if issubclass(dtype, np.bool_):
                    if isna(result).all():
                        return result.astype(np.bool_)
                    else:
                        result = result.astype(np.object_)
                        result[result == 1] = True
                        result[result == 0] = False
                        return result
                else:
                    return result.astype(np.object_)

            return result

        # may need to change the dtype here
        return maybe_downcast_to_dtype(result, dtype)

    def _try_coerce_args(self, values, other):
        """ provide coercion to our input arguments """

        if np.any(notna(other)) and not self._can_hold_element(other):
            # coercion issues
            # let higher levels handle
            raise TypeError("cannot convert {} to an {}".format(
                type(other).__name__,
                type(self).__name__.lower().replace('Block', '')))

        return values, False, other, False

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args """
        return result

    def _try_coerce_and_cast_result(self, result, dtype=None):
        result = self._try_coerce_result(result)
        result = self._try_cast_result(result, dtype=dtype)
        return result

    def to_native_types(self, slicer=None, na_rep='nan', quoting=None,
                        **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.get_values()

        if slicer is not None:
            values = values[:, slicer]
        mask = isna(values)

        if not self.is_object and not quoting:
            values = values.astype(str)
        else:
            values = np.array(values, dtype='object')

        values[mask] = na_rep
        return values

    # block actions ####
    def copy(self, deep=True, mgr=None):
        """ copy constructor """
        values = self.values
        if deep:
            values = values.copy()
        return self.make_block_same_class(values)

    def replace(self, to_replace, value, inplace=False, filter=None,
                regex=False, convert=True, mgr=None):
        """ replace the to_replace value with value, possible to create new
        blocks here this is just a call to putmask. regex is not used here.
        It is used in ObjectBlocks.  It is here for API
        compatibility.
        """

        inplace = validate_bool_kwarg(inplace, 'inplace')
        original_to_replace = to_replace

        # try to replace, if we raise an error, convert to ObjectBlock and
        # retry
        try:
            values, _, to_replace, _ = self._try_coerce_args(self.values,
                                                             to_replace)
            mask = missing.mask_missing(values, to_replace)
            if filter is not None:
                filtered_out = ~self.mgr_locs.isin(filter)
                mask[filtered_out.nonzero()[0]] = False

            blocks = self.putmask(mask, value, inplace=inplace)
            if convert:
                blocks = [b.convert(by_item=True, numeric=False,
                                    copy=not inplace) for b in blocks]
            return blocks
        except (TypeError, ValueError):

            # try again with a compatible block
            block = self.astype(object)
            return block.replace(
                to_replace=original_to_replace, value=value, inplace=inplace,
                filter=filter, regex=regex, convert=convert)

    def _replace_single(self, *args, **kwargs):
        """ no-op on a non-ObjectBlock """
        return self if kwargs['inplace'] else self.copy()

    def setitem(self, indexer, value, mgr=None):
        """Set the value inplace, returning a a maybe different typed block.

        Parameters
        ----------
        indexer : tuple, list-like, array-like, slice
            The subset of self.values to set
        value : object
            The value being set
        mgr : BlockPlacement, optional

        Returns
        -------
        Block

        Notes
        -----
        `indexer` is a direct slice/positional indexer. `value` must
        be a compatible shape.
        """
        # coerce None values, if appropriate
        if value is None:
            if self.is_numeric:
                value = np.nan

        # coerce if block dtype can store value
        values = self.values
        try:
            values, _, value, _ = self._try_coerce_args(values, value)
            # can keep its own dtype
            if hasattr(value, 'dtype') and is_dtype_equal(values.dtype,
                                                          value.dtype):
                dtype = self.dtype
            else:
                dtype = 'infer'

        except (TypeError, ValueError):
            # current dtype cannot store value, coerce to common dtype
            find_dtype = False

            if hasattr(value, 'dtype'):
                dtype = value.dtype
                find_dtype = True

            elif lib.is_scalar(value):
                if isna(value):
                    # NaN promotion is handled in latter path
                    dtype = False
                else:
                    dtype, _ = infer_dtype_from_scalar(value,
                                                       pandas_dtype=True)
                    find_dtype = True
            else:
                dtype = 'infer'

            if find_dtype:
                dtype = find_common_type([values.dtype, dtype])
                if not is_dtype_equal(self.dtype, dtype):
                    b = self.astype(dtype)
                    return b.setitem(indexer, value, mgr=mgr)

        # value must be storeable at this moment
        arr_value = np.array(value)

        # cast the values to a type that can hold nan (if necessary)
        if not self._can_hold_element(value):
            dtype, _ = maybe_promote(arr_value.dtype)
            values = values.astype(dtype)

        transf = (lambda x: x.T) if self.ndim == 2 else (lambda x: x)
        values = transf(values)

        # length checking
        check_setitem_lengths(indexer, value, values)

        def _is_scalar_indexer(indexer):
            # return True if we are all scalar indexers

            if arr_value.ndim == 1:
                if not isinstance(indexer, tuple):
                    indexer = tuple([indexer])
                    return any(isinstance(idx, np.ndarray) and len(idx) == 0
                               for idx in indexer)
            return False

        def _is_empty_indexer(indexer):
            # return a boolean if we have an empty indexer

            if is_list_like(indexer) and not len(indexer):
                return True
            if arr_value.ndim == 1:
                if not isinstance(indexer, tuple):
                    indexer = tuple([indexer])
                return any(isinstance(idx, np.ndarray) and len(idx) == 0
                           for idx in indexer)
            return False

        # empty indexers
        # 8669 (empty)
        if _is_empty_indexer(indexer):
            pass

        # setting a single element for each dim and with a rhs that could
        # be say a list
        # GH 6043
        elif _is_scalar_indexer(indexer):
            values[indexer] = value

        # if we are an exact match (ex-broadcasting),
        # then use the resultant dtype
        elif (len(arr_value.shape) and
              arr_value.shape[0] == values.shape[0] and
              np.prod(arr_value.shape) == np.prod(values.shape)):
            values[indexer] = value
            try:
                values = values.astype(arr_value.dtype)
            except ValueError:
                pass

        # set
        else:
            values[indexer] = value

        # coerce and try to infer the dtypes of the result
        values = self._try_coerce_and_cast_result(values, dtype)
        block = self.make_block(transf(values))
        return block

    def putmask(self, mask, new, align=True, inplace=False, axis=0,
                transpose=False, mgr=None):
        """ putmask the data to the block; it is possible that we may create a
        new dtype of block

        return the resulting block(s)

        Parameters
        ----------
        mask  : the condition to respect
        new : a ndarray/object
        align : boolean, perform alignment on other/cond, default is True
        inplace : perform inplace modification, default is False
        axis : int
        transpose : boolean
            Set to True if self is stored with axes reversed

        Returns
        -------
        a list of new blocks, the result of the putmask
        """

        new_values = self.values if inplace else self.values.copy()

        new = getattr(new, 'values', new)
        mask = getattr(mask, 'values', mask)

        # if we are passed a scalar None, convert it here
        if not is_list_like(new) and isna(new) and not self.is_object:
            new = self.fill_value

        if self._can_hold_element(new):
            _, _, new, _ = self._try_coerce_args(new_values, new)

            if transpose:
                new_values = new_values.T

            # If the default repeat behavior in np.putmask would go in the
            # wrong direction, then explicitly repeat and reshape new instead
            if getattr(new, 'ndim', 0) >= 1:
                if self.ndim - 1 == new.ndim and axis == 1:
                    new = np.repeat(
                        new, new_values.shape[-1]).reshape(self.shape)
                new = new.astype(new_values.dtype)

            # we require exact matches between the len of the
            # values we are setting (or is compat). np.putmask
            # doesn't check this and will simply truncate / pad
            # the output, but we want sane error messages
            #
            # TODO: this prob needs some better checking
            # for 2D cases
            if ((is_list_like(new) and
                 np.any(mask[mask]) and
                 getattr(new, 'ndim', 1) == 1)):

                if not (mask.shape[-1] == len(new) or
                        mask[mask].shape[-1] == len(new) or
                        len(new) == 1):
                    raise ValueError("cannot assign mismatch "
                                     "length to masked array")

            np.putmask(new_values, mask, new)

        # maybe upcast me
        elif mask.any():
            if transpose:
                mask = mask.T
                if isinstance(new, np.ndarray):
                    new = new.T
                axis = new_values.ndim - axis - 1

            # Pseudo-broadcast
            if getattr(new, 'ndim', 0) >= 1:
                if self.ndim - 1 == new.ndim:
                    new_shape = list(new.shape)
                    new_shape.insert(axis, 1)
                    new = new.reshape(tuple(new_shape))

            # operate column-by-column
            def f(m, v, i):

                if i is None:
                    # ndim==1 case.
                    n = new
                else:

                    if isinstance(new, np.ndarray):
                        n = np.squeeze(new[i % new.shape[0]])
                    else:
                        n = np.array(new)

                    # type of the new block
                    dtype, _ = maybe_promote(n.dtype)

                    # we need to explicitly astype here to make a copy
                    n = n.astype(dtype)

                nv = _putmask_smart(v, m, n)
                return nv

            new_blocks = self.split_and_operate(mask, f, inplace)
            return new_blocks

        if inplace:
            return [self]

        if transpose:
            new_values = new_values.T

        return [self.make_block(new_values)]

    def coerce_to_target_dtype(self, other):
        """
        coerce the current block to a dtype compat for other
        we will return a block, possibly object, and not raise

        we can also safely try to coerce to the same dtype
        and will receive the same block
        """

        # if we cannot then coerce to object
        dtype, _ = infer_dtype_from(other, pandas_dtype=True)

        if is_dtype_equal(self.dtype, dtype):
            return self

        if self.is_bool or is_object_dtype(dtype) or is_bool_dtype(dtype):
            # we don't upcast to bool
            return self.astype(object)

        elif ((self.is_float or self.is_complex) and
              (is_integer_dtype(dtype) or is_float_dtype(dtype))):
            # don't coerce float/complex to int
            return self

        elif (self.is_datetime or
              is_datetime64_dtype(dtype) or
              is_datetime64tz_dtype(dtype)):

            # not a datetime
            if not ((is_datetime64_dtype(dtype) or
                     is_datetime64tz_dtype(dtype)) and self.is_datetime):
                return self.astype(object)

            # don't upcast timezone with different timezone or no timezone
            mytz = getattr(self.dtype, 'tz', None)
            othertz = getattr(dtype, 'tz', None)

            if str(mytz) != str(othertz):
                return self.astype(object)

            raise AssertionError("possible recursion in "
                                 "coerce_to_target_dtype: {} {}".format(
                                     self, other))

        elif (self.is_timedelta or is_timedelta64_dtype(dtype)):

            # not a timedelta
            if not (is_timedelta64_dtype(dtype) and self.is_timedelta):
                return self.astype(object)

            raise AssertionError("possible recursion in "
                                 "coerce_to_target_dtype: {} {}".format(
                                     self, other))

        try:
            return self.astype(dtype)
        except (ValueError, TypeError):
            pass

        return self.astype(object)

    def interpolate(self, method='pad', axis=0, index=None, values=None,
                    inplace=False, limit=None, limit_direction='forward',
                    limit_area=None, fill_value=None, coerce=False,
                    downcast=None, mgr=None, **kwargs):

        inplace = validate_bool_kwarg(inplace, 'inplace')

        def check_int_bool(self, inplace):
            # Only FloatBlocks will contain NaNs.
            # timedelta subclasses IntBlock
            if (self.is_bool or self.is_integer) and not self.is_timedelta:
                if inplace:
                    return self
                else:
                    return self.copy()

        # a fill na type method
        try:
            m = missing.clean_fill_method(method)
        except:
            m = None

        if m is not None:
            r = check_int_bool(self, inplace)
            if r is not None:
                return r
            return self._interpolate_with_fill(method=m, axis=axis,
                                               inplace=inplace, limit=limit,
                                               fill_value=fill_value,
                                               coerce=coerce,
                                               downcast=downcast, mgr=mgr)
        # try an interp method
        try:
            m = missing.clean_interp_method(method, **kwargs)
        except:
            m = None

        if m is not None:
            r = check_int_bool(self, inplace)
            if r is not None:
                return r
            return self._interpolate(method=m, index=index, values=values,
                                     axis=axis, limit=limit,
                                     limit_direction=limit_direction,
                                     limit_area=limit_area,
                                     fill_value=fill_value, inplace=inplace,
                                     downcast=downcast, mgr=mgr, **kwargs)

        raise ValueError("invalid method '{0}' to interpolate.".format(method))

    def _interpolate_with_fill(self, method='pad', axis=0, inplace=False,
                               limit=None, fill_value=None, coerce=False,
                               downcast=None, mgr=None):
        """ fillna but using the interpolate machinery """

        inplace = validate_bool_kwarg(inplace, 'inplace')

        # if we are coercing, then don't force the conversion
        # if the block can't hold the type
        if coerce:
            if not self._can_hold_na:
                if inplace:
                    return [self]
                else:
                    return [self.copy()]

        values = self.values if inplace else self.values.copy()
        values, _, fill_value, _ = self._try_coerce_args(values, fill_value)
        values = missing.interpolate_2d(values, method=method, axis=axis,
                                        limit=limit, fill_value=fill_value,
                                        dtype=self.dtype)
        values = self._try_coerce_result(values)

        blocks = [self.make_block_same_class(values, ndim=self.ndim)]
        return self._maybe_downcast(blocks, downcast)

    def _interpolate(self, method=None, index=None, values=None,
                     fill_value=None, axis=0, limit=None,
                     limit_direction='forward', limit_area=None,
                     inplace=False, downcast=None, mgr=None, **kwargs):
        """ interpolate using scipy wrappers """

        inplace = validate_bool_kwarg(inplace, 'inplace')
        data = self.values if inplace else self.values.copy()

        # only deal with floats
        if not self.is_float:
            if not self.is_integer:
                return self
            data = data.astype(np.float64)

        if fill_value is None:
            fill_value = self.fill_value

        if method in ('krogh', 'piecewise_polynomial', 'pchip'):
            if not index.is_monotonic:
                raise ValueError("{0} interpolation requires that the "
                                 "index be monotonic.".format(method))
        # process 1-d slices in the axis direction

        def func(x):

            # process a 1-d slice, returning it
            # should the axis argument be handled below in apply_along_axis?
            # i.e. not an arg to missing.interpolate_1d
            return missing.interpolate_1d(index, x, method=method, limit=limit,
                                          limit_direction=limit_direction,
                                          limit_area=limit_area,
                                          fill_value=fill_value,
                                          bounds_error=False, **kwargs)

        # interp each column independently
        interp_values = np.apply_along_axis(func, axis, data)

        blocks = [self.make_block_same_class(interp_values)]
        return self._maybe_downcast(blocks, downcast)

    def take_nd(self, indexer, axis, new_mgr_locs=None, fill_tuple=None):
        """
        Take values according to indexer and return them as a block.bb

        """

        # algos.take_nd dispatches for DatetimeTZBlock, CategoricalBlock
        # so need to preserve types
        # sparse is treated like an ndarray, but needs .get_values() shaping

        values = self.values
        if self.is_sparse:
            values = self.get_values()

        if fill_tuple is None:
            fill_value = self.fill_value
            new_values = algos.take_nd(values, indexer, axis=axis,
                                       allow_fill=False)
        else:
            fill_value = fill_tuple[0]
            new_values = algos.take_nd(values, indexer, axis=axis,
                                       allow_fill=True, fill_value=fill_value)

        if new_mgr_locs is None:
            if axis == 0:
                slc = libinternals.indexer_as_slice(indexer)
                if slc is not None:
                    new_mgr_locs = self.mgr_locs[slc]
                else:
                    new_mgr_locs = self.mgr_locs[indexer]
            else:
                new_mgr_locs = self.mgr_locs

        if not is_dtype_equal(new_values.dtype, self.dtype):
            return self.make_block(new_values, new_mgr_locs)
        else:
            return self.make_block_same_class(new_values, new_mgr_locs)

    def diff(self, n, axis=1, mgr=None):
        """ return block for the diff of the values """
        new_values = algos.diff(self.values, n, axis=axis)
        return [self.make_block(values=new_values)]

    def shift(self, periods, axis=0, mgr=None):
        """ shift the block by periods, possibly upcast """

        # convert integer to float if necessary. need to do a lot more than
        # that, handle boolean etc also
        new_values, fill_value = maybe_upcast(self.values)

        # make sure array sent to np.roll is c_contiguous
        f_ordered = new_values.flags.f_contiguous
        if f_ordered:
            new_values = new_values.T
            axis = new_values.ndim - axis - 1

        if np.prod(new_values.shape):
            new_values = np.roll(new_values, ensure_platform_int(periods),
                                 axis=axis)

        axis_indexer = [slice(None)] * self.ndim
        if periods > 0:
            axis_indexer[axis] = slice(None, periods)
        else:
            axis_indexer[axis] = slice(periods, None)
        new_values[tuple(axis_indexer)] = fill_value

        # restore original order
        if f_ordered:
            new_values = new_values.T

        return [self.make_block(new_values)]

    def eval(self, func, other, errors='raise', try_cast=False, mgr=None):
        """
        evaluate the block; return result block from the result

        Parameters
        ----------
        func  : how to combine self, other
        other : a ndarray/object
        errors : str, {'raise', 'ignore'}, default 'raise'
            - ``raise`` : allow exceptions to be raised
            - ``ignore`` : suppress exceptions. On error return original object

        try_cast : try casting the results to the input type

        Returns
        -------
        a new block, the result of the func
        """
        orig_other = other
        values = self.values

        other = getattr(other, 'values', other)

        # make sure that we can broadcast
        is_transposed = False
        if hasattr(other, 'ndim') and hasattr(values, 'ndim'):
            if values.ndim != other.ndim:
                is_transposed = True
            else:
                if values.shape == other.shape[::-1]:
                    is_transposed = True
                elif values.shape[0] == other.shape[-1]:
                    is_transposed = True
                else:
                    # this is a broadcast error heree
                    raise ValueError(
                        "cannot broadcast shape [{t_shape}] with "
                        "block values [{oth_shape}]".format(
                            t_shape=values.T.shape, oth_shape=other.shape))

        transf = (lambda x: x.T) if is_transposed else (lambda x: x)

        # coerce/transpose the args if needed
        try:
            values, values_mask, other, other_mask = self._try_coerce_args(
                transf(values), other)
        except TypeError:
            block = self.coerce_to_target_dtype(orig_other)
            return block.eval(func, orig_other,
                              errors=errors,
                              try_cast=try_cast, mgr=mgr)

        # get the result, may need to transpose the other
        def get_result(other):

            # avoid numpy warning of comparisons again None
            if other is None:
                result = not func.__name__ == 'eq'

            # avoid numpy warning of elementwise comparisons to object
            elif is_numeric_v_string_like(values, other):
                result = False

            # avoid numpy warning of elementwise comparisons
            elif func.__name__ == 'eq':
                if is_list_like(other) and not isinstance(other, np.ndarray):
                    other = np.asarray(other)

                    # if we can broadcast, then ok
                    if values.shape[-1] != other.shape[-1]:
                        return False
                result = func(values, other)
            else:
                result = func(values, other)

            # mask if needed
            if isinstance(values_mask, np.ndarray) and values_mask.any():
                result = result.astype('float64', copy=False)
                result[values_mask] = np.nan
            if other_mask is True:
                result = result.astype('float64', copy=False)
                result[:] = np.nan
            elif isinstance(other_mask, np.ndarray) and other_mask.any():
                result = result.astype('float64', copy=False)
                result[other_mask.ravel()] = np.nan

            return result

        # error handler if we have an issue operating with the function
        def handle_error():

            if errors == 'raise':
                # The 'detail' variable is defined in outer scope.
                raise TypeError(
                    'Could not operate {other!r} with block values '
                    '{detail!s}'.format(other=other, detail=detail))  # noqa
            else:
                # return the values
                result = np.empty(values.shape, dtype='O')
                result.fill(np.nan)
                return result

        # get the result
        try:
            with np.errstate(all='ignore'):
                result = get_result(other)

        # if we have an invalid shape/broadcast error
        # GH4576, so raise instead of allowing to pass through
        except ValueError as detail:
            raise
        except Exception as detail:
            result = handle_error()

        # technically a broadcast error in numpy can 'work' by returning a
        # boolean False
        if not isinstance(result, np.ndarray):
            if not isinstance(result, np.ndarray):

                # differentiate between an invalid ndarray-ndarray comparison
                # and an invalid type comparison
                if isinstance(values, np.ndarray) and is_list_like(other):
                    raise ValueError(
                        'Invalid broadcasting comparison [{other!r}] with '
                        'block values'.format(other=other))

                raise TypeError('Could not compare [{other!r}] '
                                'with block values'.format(other=other))

        # transpose if needed
        result = transf(result)

        # try to cast if requested
        if try_cast:
            result = self._try_cast_result(result)

        result = _block_shape(result, ndim=self.ndim)
        return [self.make_block(result)]

    def where(self, other, cond, align=True, errors='raise',
              try_cast=False, axis=0, transpose=False, mgr=None):
        """
        evaluate the block; return result block(s) from the result

        Parameters
        ----------
        other : a ndarray/object
        cond  : the condition to respect
        align : boolean, perform alignment on other/cond
        errors : str, {'raise', 'ignore'}, default 'raise'
            - ``raise`` : allow exceptions to be raised
            - ``ignore`` : suppress exceptions. On error return original object

        axis : int
        transpose : boolean
            Set to True if self is stored with axes reversed

        Returns
        -------
        a new block(s), the result of the func
        """
        import pandas.core.computation.expressions as expressions
        assert errors in ['raise', 'ignore']

        values = self.values
        orig_other = other
        if transpose:
            values = values.T

        other = getattr(other, '_values', getattr(other, 'values', other))
        cond = getattr(cond, 'values', cond)

        # If the default broadcasting would go in the wrong direction, then
        # explicitly reshape other instead
        if getattr(other, 'ndim', 0) >= 1:
            if values.ndim - 1 == other.ndim and axis == 1:
                other = other.reshape(tuple(other.shape + (1, )))
            elif transpose and values.ndim == self.ndim - 1:
                cond = cond.T

        if not hasattr(cond, 'shape'):
            raise ValueError("where must have a condition that is ndarray "
                             "like")

        # our where function
        def func(cond, values, other):
            if cond.ravel().all():
                return values

            values, values_mask, other, other_mask = self._try_coerce_args(
                values, other)

            try:
                return self._try_coerce_result(expressions.where(
                    cond, values, other))
            except Exception as detail:
                if errors == 'raise':
                    raise TypeError(
                        'Could not operate [{other!r}] with block values '
                        '[{detail!s}]'.format(other=other, detail=detail))
                else:
                    # return the values
                    result = np.empty(values.shape, dtype='float64')
                    result.fill(np.nan)
                    return result

        # see if we can operate on the entire block, or need item-by-item
        # or if we are a single block (ndim == 1)
        try:
            result = func(cond, values, other)
        except TypeError:

            # we cannot coerce, return a compat dtype
            # we are explicitly ignoring errors
            block = self.coerce_to_target_dtype(other)
            blocks = block.where(orig_other, cond, align=align,
                                 errors=errors,
                                 try_cast=try_cast, axis=axis,
                                 transpose=transpose)
            return self._maybe_downcast(blocks, 'infer')

        if self._can_hold_na or self.ndim == 1:

            if transpose:
                result = result.T

            # try to cast if requested
            if try_cast:
                result = self._try_cast_result(result)

            return self.make_block(result)

        # might need to separate out blocks
        axis = cond.ndim - 1
        cond = cond.swapaxes(axis, 0)
        mask = np.array([cond[i].all() for i in range(cond.shape[0])],
                        dtype=bool)

        result_blocks = []
        for m in [mask, ~mask]:
            if m.any():
                r = self._try_cast_result(result.take(m.nonzero()[0],
                                                      axis=axis))
                result_blocks.append(
                    self.make_block(r.T, placement=self.mgr_locs[m]))

        return result_blocks

    def equals(self, other):
        if self.dtype != other.dtype or self.shape != other.shape:
            return False
        return array_equivalent(self.values, other.values)

    def _unstack(self, unstacker_func, new_columns):
        """Return a list of unstacked blocks of self

        Parameters
        ----------
        unstacker_func : callable
            Partially applied unstacker.
        new_columns : Index
            All columns of the unstacked BlockManager.

        Returns
        -------
        blocks : list of Block
            New blocks of unstacked values.
        mask : array_like of bool
            The mask of columns of `blocks` we should keep.
        """
        unstacker = unstacker_func(self.values.T)
        new_items = unstacker.get_new_columns()
        new_placement = new_columns.get_indexer(new_items)
        new_values, mask = unstacker.get_new_values()

        mask = mask.any(0)
        new_values = new_values.T[mask]
        new_placement = new_placement[mask]

        blocks = [make_block(new_values, placement=new_placement)]
        return blocks, mask

    def quantile(self, qs, interpolation='linear', axis=0, mgr=None):
        """
        compute the quantiles of the

        Parameters
        ----------
        qs: a scalar or list of the quantiles to be computed
        interpolation: type of interpolation, default 'linear'
        axis: axis to compute, default 0

        Returns
        -------
        tuple of (axis, block)

        """
        kw = {'interpolation': interpolation}
        values = self.get_values()
        values, _, _, _ = self._try_coerce_args(values, values)

        def _nanpercentile1D(values, mask, q, **kw):
            values = values[~mask]

            if len(values) == 0:
                if lib.is_scalar(q):
                    return self._na_value
                else:
                    return np.array([self._na_value] * len(q),
                                    dtype=values.dtype)

            return np.percentile(values, q, **kw)

        def _nanpercentile(values, q, axis, **kw):

            mask = isna(self.values)
            if not lib.is_scalar(mask) and mask.any():
                if self.ndim == 1:
                    return _nanpercentile1D(values, mask, q, **kw)
                else:
                    # for nonconsolidatable blocks mask is 1D, but values 2D
                    if mask.ndim < values.ndim:
                        mask = mask.reshape(values.shape)
                    if axis == 0:
                        values = values.T
                        mask = mask.T
                    result = [_nanpercentile1D(val, m, q, **kw) for (val, m)
                              in zip(list(values), list(mask))]
                    result = np.array(result, dtype=values.dtype, copy=False).T
                    return result
            else:
                return np.percentile(values, q, axis=axis, **kw)

        from pandas import Float64Index
        is_empty = values.shape[axis] == 0
        if is_list_like(qs):
            ax = Float64Index(qs)

            if is_empty:
                if self.ndim == 1:
                    result = self._na_value
                else:
                    # create the array of na_values
                    # 2d len(values) * len(qs)
                    result = np.repeat(np.array([self._na_value] * len(qs)),
                                       len(values)).reshape(len(values),
                                                            len(qs))
            else:

                try:
                    result = _nanpercentile(values, np.array(qs) * 100,
                                            axis=axis, **kw)
                except ValueError:

                    # older numpies don't handle an array for q
                    result = [_nanpercentile(values, q * 100,
                                             axis=axis, **kw) for q in qs]

                result = np.array(result, copy=False)
                if self.ndim > 1:
                    result = result.T

        else:

            if self.ndim == 1:
                ax = Float64Index([qs])
            else:
                ax = mgr.axes[0]

            if is_empty:
                if self.ndim == 1:
                    result = self._na_value
                else:
                    result = np.array([self._na_value] * len(self))
            else:
                result = _nanpercentile(values, qs * 100, axis=axis, **kw)

        ndim = getattr(result, 'ndim', None) or 0
        result = self._try_coerce_result(result)
        if lib.is_scalar(result):
            return ax, self.make_block_scalar(result)
        return ax, make_block(result,
                              placement=np.arange(len(result)),
                              ndim=ndim)


class ScalarBlock(Block):
    """
    a scalar compat Block
    """
    __slots__ = ['_mgr_locs', 'values', 'ndim']

    def __init__(self, values):
        self.ndim = 0
        self.mgr_locs = [0]
        self.values = values

    @property
    def dtype(self):
        return type(self.values)

    @property
    def shape(self):
        return tuple([0])

    def __len__(self):
        return 0


class NonConsolidatableMixIn(object):
    """ hold methods for the nonconsolidatable blocks """
    _can_consolidate = False
    _verify_integrity = False
    _validate_ndim = False

    def __init__(self, values, placement, ndim=None):
        """Initialize a non-consolidatable block.

        'ndim' may be inferred from 'placement'.

        This will call continue to call __init__ for the other base
        classes mixed in with this Mixin.
        """
        # Placement must be converted to BlockPlacement so that we can check
        # its length
        if not isinstance(placement, libinternals.BlockPlacement):
            placement = libinternals.BlockPlacement(placement)

        # Maybe infer ndim from placement
        if ndim is None:
            if len(placement) != 1:
                ndim = 1
            else:
                ndim = 2
        super(NonConsolidatableMixIn, self).__init__(values, placement,
                                                     ndim=ndim)

    @property
    def shape(self):
        if self.ndim == 1:
            return (len(self.values)),
        return (len(self.mgr_locs), len(self.values))

    def get_values(self, dtype=None):
        """ need to to_dense myself (and always return a ndim sized object) """
        values = self.values.to_dense()
        if values.ndim == self.ndim - 1:
            values = values.reshape((1,) + values.shape)
        return values

    def iget(self, col):

        if self.ndim == 2 and isinstance(col, tuple):
            col, loc = col
            if not com.is_null_slice(col) and col != 0:
                raise IndexError("{0} only contains one item".format(self))
            return self.values[loc]
        else:
            if col != 0:
                raise IndexError("{0} only contains one item".format(self))
            return self.values

    def should_store(self, value):
        return isinstance(value, self._holder)

    def set(self, locs, values, check=False):
        assert locs.tolist() == [0]
        self.values = values

    def putmask(self, mask, new, align=True, inplace=False, axis=0,
                transpose=False, mgr=None):
        """
        putmask the data to the block; we must be a single block and not
        generate other blocks

        return the resulting block

        Parameters
        ----------
        mask  : the condition to respect
        new : a ndarray/object
        align : boolean, perform alignment on other/cond, default is True
        inplace : perform inplace modification, default is False

        Returns
        -------
        a new block, the result of the putmask
        """
        inplace = validate_bool_kwarg(inplace, 'inplace')

        # use block's copy logic.
        # .values may be an Index which does shallow copy by default
        new_values = self.values if inplace else self.copy().values
        new_values, _, new, _ = self._try_coerce_args(new_values, new)

        if isinstance(new, np.ndarray) and len(new) == len(mask):
            new = new[mask]

        mask = _safe_reshape(mask, new_values.shape)

        new_values[mask] = new
        new_values = self._try_coerce_result(new_values)
        return [self.make_block(values=new_values)]

    def _slice(self, slicer):
        """ return a slice of my values (but densify first) """
        return self.get_values()[slicer]

    def _try_cast_result(self, result, dtype=None):
        return result

    def _unstack(self, unstacker_func, new_columns):
        """Return a list of unstacked blocks of self

        Parameters
        ----------
        unstacker_func : callable
            Partially applied unstacker.
        new_columns : Index
            All columns of the unstacked BlockManager.

        Returns
        -------
        blocks : list of Block
            New blocks of unstacked values.
        mask : array_like of bool
            The mask of columns of `blocks` we should keep.
        """
        # NonConsolidatable blocks can have a single item only, so we return
        # one block per item
        unstacker = unstacker_func(self.values.T)
        new_items = unstacker.get_new_columns()
        new_placement = new_columns.get_indexer(new_items)
        new_values, mask = unstacker.get_new_values()

        mask = mask.any(0)
        new_values = new_values.T[mask]
        new_placement = new_placement[mask]

        blocks = [self.make_block_same_class(vals, [place])
                  for vals, place in zip(new_values, new_placement)]
        return blocks, mask


class ExtensionBlock(NonConsolidatableMixIn, Block):
    """Block for holding extension types.

    Notes
    -----
    This holds all 3rd-party extension array types. It's also the immediate
    parent class for our internal extension types' blocks, CategoricalBlock.

    ExtensionArrays are limited to 1-D.
    """
    is_extension = True

    def __init__(self, values, placement, ndim=None):
        values = self._maybe_coerce_values(values)
        super(ExtensionBlock, self).__init__(values, placement, ndim)

    def _maybe_coerce_values(self, values):
        """Unbox to an extension array.

        This will unbox an ExtensionArray stored in an Index or Series.
        ExtensionArrays pass through. No dtype coercion is done.

        Parameters
        ----------
        values : Index, Series, ExtensionArray

        Returns
        -------
        ExtensionArray
        """
        if isinstance(values, (ABCIndexClass, ABCSeries)):
            values = values._values
        return values

    @property
    def _holder(self):
        # For extension blocks, the holder is values-dependent.
        return type(self.values)

    @property
    def fill_value(self):
        # Used in reindex_indexer
        return self.values.dtype.na_value

    @property
    def _can_hold_na(self):
        # The default ExtensionArray._can_hold_na is True
        return self._holder._can_hold_na

    @property
    def is_view(self):
        """Extension arrays are never treated as views."""
        return False

    def setitem(self, indexer, value, mgr=None):
        """Set the value inplace, returning a same-typed block.

        This differs from Block.setitem by not allowing setitem to change
        the dtype of the Block.

        Parameters
        ----------
        indexer : tuple, list-like, array-like, slice
            The subset of self.values to set
        value : object
            The value being set
        mgr : BlockPlacement, optional

        Returns
        -------
        Block

        Notes
        -----
        `indexer` is a direct slice/positional indexer. `value` must
        be a compatible shape.
        """
        if isinstance(indexer, tuple):
            # we are always 1-D
            indexer = indexer[0]

        check_setitem_lengths(indexer, value, self.values)
        self.values[indexer] = value
        return self

    def get_values(self, dtype=None):
        # ExtensionArrays must be iterable, so this works.
        values = np.asarray(self.values)
        if values.ndim == self.ndim - 1:
            values = values.reshape((1,) + values.shape)
        return values

    def to_dense(self):
        return np.asarray(self.values)

    def take_nd(self, indexer, axis=0, new_mgr_locs=None, fill_tuple=None):
        """
        Take values according to indexer and return them as a block.
        """
        if fill_tuple is None:
            fill_value = None
        else:
            fill_value = fill_tuple[0]

        # axis doesn't matter; we are really a single-dim object
        # but are passed the axis depending on the calling routing
        # if its REALLY axis 0, then this will be a reindex and not a take
        new_values = self.values.take(indexer, fill_value=fill_value,
                                      allow_fill=True)

        # if we are a 1-dim object, then always place at 0
        if self.ndim == 1:
            new_mgr_locs = [0]
        else:
            if new_mgr_locs is None:
                new_mgr_locs = self.mgr_locs

        return self.make_block_same_class(new_values, new_mgr_locs)

    def _can_hold_element(self, element):
        # XXX: We may need to think about pushing this onto the array.
        # We're doing the same as CategoricalBlock here.
        return True

    def _slice(self, slicer):
        """ return a slice of my values """

        # slice the category
        # return same dims as we currently have

        if isinstance(slicer, tuple) and len(slicer) == 2:
            if not com.is_null_slice(slicer[0]):
                raise AssertionError("invalid slicing for a 1-ndim "
                                     "categorical")
            slicer = slicer[1]

        return self.values[slicer]

    def formatting_values(self):
        return self.values._formatting_values()

    def concat_same_type(self, to_concat, placement=None):
        """
        Concatenate list of single blocks of the same type.
        """
        values = self._holder._concat_same_type(
            [blk.values for blk in to_concat])
        placement = placement or slice(0, len(values), 1)
        return self.make_block_same_class(values, ndim=self.ndim,
                                          placement=placement)

    def fillna(self, value, limit=None, inplace=False, downcast=None,
               mgr=None):
        values = self.values if inplace else self.values.copy()
        values = values.fillna(value=value, limit=limit)
        return [self.make_block_same_class(values=values,
                                           placement=self.mgr_locs,
                                           ndim=self.ndim)]

    def interpolate(self, method='pad', axis=0, inplace=False, limit=None,
                    fill_value=None, **kwargs):

        values = self.values if inplace else self.values.copy()
        return self.make_block_same_class(
            values=values.fillna(value=fill_value, method=method,
                                 limit=limit),
            placement=self.mgr_locs)


class NumericBlock(Block):
    __slots__ = ()
    is_numeric = True
    _can_hold_na = True


class FloatOrComplexBlock(NumericBlock):
    __slots__ = ()

    def equals(self, other):
        if self.dtype != other.dtype or self.shape != other.shape:
            return False
        left, right = self.values, other.values
        return ((left == right) | (np.isnan(left) & np.isnan(right))).all()


class FloatBlock(FloatOrComplexBlock):
    __slots__ = ()
    is_float = True

    def _can_hold_element(self, element):
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            return (issubclass(tipo.type, (np.floating, np.integer)) and
                    not issubclass(tipo.type, (np.datetime64, np.timedelta64)))
        return (
            isinstance(
                element, (float, int, np.floating, np.int_, compat.long))
            and not isinstance(element, (bool, np.bool_, datetime, timedelta,
                                         np.datetime64, np.timedelta64)))

    def to_native_types(self, slicer=None, na_rep='', float_format=None,
                        decimal='.', quoting=None, **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            values = values[:, slicer]

        # see gh-13418: no special formatting is desired at the
        # output (important for appropriate 'quoting' behaviour),
        # so do not pass it through the FloatArrayFormatter
        if float_format is None and decimal == '.':
            mask = isna(values)

            if not quoting:
                values = values.astype(str)
            else:
                values = np.array(values, dtype='object')

            values[mask] = na_rep
            return values

        from pandas.io.formats.format import FloatArrayFormatter
        formatter = FloatArrayFormatter(values, na_rep=na_rep,
                                        float_format=float_format,
                                        decimal=decimal, quoting=quoting,
                                        fixed_width=False)
        return formatter.get_result_as_array()

    def should_store(self, value):
        # when inserting a column should not coerce integers to floats
        # unnecessarily
        return (issubclass(value.dtype.type, np.floating) and
                value.dtype == self.dtype)


class ComplexBlock(FloatOrComplexBlock):
    __slots__ = ()
    is_complex = True

    def _can_hold_element(self, element):
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            return issubclass(tipo.type,
                              (np.floating, np.integer, np.complexfloating))
        return (
            isinstance(
                element,
                (float, int, complex, np.float_, np.int_, compat.long))
            and not isinstance(element, (bool, np.bool_)))

    def should_store(self, value):
        return issubclass(value.dtype.type, np.complexfloating)


class IntBlock(NumericBlock):
    __slots__ = ()
    is_integer = True
    _can_hold_na = False

    def _can_hold_element(self, element):
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            return (issubclass(tipo.type, np.integer) and
                    not issubclass(tipo.type, (np.datetime64,
                                               np.timedelta64)) and
                    self.dtype.itemsize >= tipo.itemsize)
        return is_integer(element)

    def should_store(self, value):
        return is_integer_dtype(value) and value.dtype == self.dtype


class DatetimeLikeBlockMixin(object):
    """Mixin class for DatetimeBlock and DatetimeTZBlock."""

    @property
    def _holder(self):
        return DatetimeIndex

    @property
    def _na_value(self):
        return tslibs.NaT

    @property
    def fill_value(self):
        return tslibs.iNaT

    def get_values(self, dtype=None):
        """
        return object dtype as boxed values, such as Timestamps/Timedelta
        """
        if is_object_dtype(dtype):
            return lib.map_infer(self.values.ravel(),
                                 self._box_func).reshape(self.values.shape)
        return self.values


class TimeDeltaBlock(DatetimeLikeBlockMixin, IntBlock):
    __slots__ = ()
    is_timedelta = True
    _can_hold_na = True
    is_numeric = False

    def __init__(self, values, placement, ndim=None):
        if values.dtype != _TD_DTYPE:
            values = conversion.ensure_timedelta64ns(values)

        super(TimeDeltaBlock, self).__init__(values,
                                             placement=placement, ndim=ndim)

    @property
    def _holder(self):
        return TimedeltaIndex

    @property
    def _box_func(self):
        return lambda x: Timedelta(x, unit='ns')

    def _can_hold_element(self, element):
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            return issubclass(tipo.type, np.timedelta64)
        return is_integer(element) or isinstance(
            element, (timedelta, np.timedelta64))

    def fillna(self, value, **kwargs):

        # allow filling with integers to be
        # interpreted as seconds
        if is_integer(value) and not isinstance(value, np.timedelta64):
            value = Timedelta(value, unit='s')
        return super(TimeDeltaBlock, self).fillna(value, **kwargs)

    def _try_coerce_args(self, values, other):
        """
        Coerce values and other to int64, with null values converted to
        iNaT. values is always ndarray-like, other may not be

        Parameters
        ----------
        values : ndarray-like
        other : ndarray-like or scalar

        Returns
        -------
        base-type values, values mask, base-type other, other mask
        """

        values_mask = isna(values)
        values = values.view('i8')
        other_mask = False

        if isinstance(other, bool):
            raise TypeError
        elif is_null_datelike_scalar(other):
            other = tslibs.iNaT
            other_mask = True
        elif isinstance(other, Timedelta):
            other_mask = isna(other)
            other = other.value
        elif isinstance(other, timedelta):
            other = Timedelta(other).value
        elif isinstance(other, np.timedelta64):
            other_mask = isna(other)
            other = Timedelta(other).value
        elif hasattr(other, 'dtype') and is_timedelta64_dtype(other):
            other_mask = isna(other)
            other = other.astype('i8', copy=False).view('i8')
        else:
            # coercion issues
            # let higher levels handle
            raise TypeError

        return values, values_mask, other, other_mask

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args / try_operate """
        if isinstance(result, np.ndarray):
            mask = isna(result)
            if result.dtype.kind in ['i', 'f', 'O']:
                result = result.astype('m8[ns]')
            result[mask] = tslibs.iNaT
        elif isinstance(result, (np.integer, np.float)):
            result = self._box_func(result)
        return result

    def should_store(self, value):
        return issubclass(value.dtype.type, np.timedelta64)

    def to_native_types(self, slicer=None, na_rep=None, quoting=None,
                        **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            values = values[:, slicer]
        mask = isna(values)

        rvalues = np.empty(values.shape, dtype=object)
        if na_rep is None:
            na_rep = 'NaT'
        rvalues[mask] = na_rep
        imask = (~mask).ravel()

        # FIXME:
        # should use the formats.format.Timedelta64Formatter here
        # to figure what format to pass to the Timedelta
        # e.g. to not show the decimals say
        rvalues.flat[imask] = np.array([Timedelta(val)._repr_base(format='all')
                                        for val in values.ravel()[imask]],
                                       dtype=object)
        return rvalues


class BoolBlock(NumericBlock):
    __slots__ = ()
    is_bool = True
    _can_hold_na = False

    def _can_hold_element(self, element):
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            return issubclass(tipo.type, np.bool_)
        return isinstance(element, (bool, np.bool_))

    def should_store(self, value):
        return issubclass(value.dtype.type, np.bool_)

    def replace(self, to_replace, value, inplace=False, filter=None,
                regex=False, convert=True, mgr=None):
        inplace = validate_bool_kwarg(inplace, 'inplace')
        to_replace_values = np.atleast_1d(to_replace)
        if not np.can_cast(to_replace_values, bool):
            return self
        return super(BoolBlock, self).replace(to_replace, value,
                                              inplace=inplace, filter=filter,
                                              regex=regex, convert=convert,
                                              mgr=mgr)


class ObjectBlock(Block):
    __slots__ = ()
    is_object = True
    _can_hold_na = True

    def __init__(self, values, placement=None, ndim=2):
        if issubclass(values.dtype.type, compat.string_types):
            values = np.array(values, dtype=object)

        super(ObjectBlock, self).__init__(values, ndim=ndim,
                                          placement=placement)

    @property
    def is_bool(self):
        """ we can be a bool if we have only bool values but are of type
        object
        """
        return lib.is_bool_array(self.values.ravel())

    # TODO: Refactor when convert_objects is removed since there will be 1 path
    def convert(self, *args, **kwargs):
        """ attempt to coerce any object types to better types return a copy of
        the block (if copy = True) by definition we ARE an ObjectBlock!!!!!

        can return multiple blocks!
        """

        if args:
            raise NotImplementedError
        by_item = True if 'by_item' not in kwargs else kwargs['by_item']

        new_inputs = ['coerce', 'datetime', 'numeric', 'timedelta']
        new_style = False
        for kw in new_inputs:
            new_style |= kw in kwargs

        if new_style:
            fn = soft_convert_objects
            fn_inputs = new_inputs
        else:
            fn = maybe_convert_objects
            fn_inputs = ['convert_dates', 'convert_numeric',
                         'convert_timedeltas']
        fn_inputs += ['copy']

        fn_kwargs = {}
        for key in fn_inputs:
            if key in kwargs:
                fn_kwargs[key] = kwargs[key]

        # operate column-by-column
        def f(m, v, i):
            shape = v.shape
            values = fn(v.ravel(), **fn_kwargs)
            try:
                values = values.reshape(shape)
                values = _block_shape(values, ndim=self.ndim)
            except (AttributeError, NotImplementedError):
                pass

            return values

        if by_item and not self._is_single_block:
            blocks = self.split_and_operate(None, f, False)
        else:
            values = f(None, self.values.ravel(), None)
            blocks = [make_block(values, ndim=self.ndim,
                                 placement=self.mgr_locs)]

        return blocks

    def set(self, locs, values, check=False):
        """
        Modify Block in-place with new item value

        Returns
        -------
        None
        """

        # GH6026
        if check:
            try:
                if (self.values[locs] == values).all():
                    return
            except:
                pass
        try:
            self.values[locs] = values
        except (ValueError):

            # broadcasting error
            # see GH6171
            new_shape = list(values.shape)
            new_shape[0] = len(self.items)
            self.values = np.empty(tuple(new_shape), dtype=self.dtype)
            self.values.fill(np.nan)
            self.values[locs] = values

    def _maybe_downcast(self, blocks, downcast=None):

        if downcast is not None:
            return blocks

        # split and convert the blocks
        return _extend_blocks([b.convert(datetime=True, numeric=False)
                               for b in blocks])

    def _can_hold_element(self, element):
        return True

    def _try_coerce_args(self, values, other):
        """ provide coercion to our input arguments """

        if isinstance(other, ABCDatetimeIndex):
            # to store DatetimeTZBlock as object
            other = other.astype(object).values

        return values, False, other, False

    def should_store(self, value):
        return not (issubclass(value.dtype.type,
                               (np.integer, np.floating, np.complexfloating,
                                np.datetime64, np.bool_)) or
                    # TODO(ExtensionArray): remove is_extension_type
                    # when all extension arrays have been ported.
                    is_extension_type(value) or
                    is_extension_array_dtype(value))

    def replace(self, to_replace, value, inplace=False, filter=None,
                regex=False, convert=True, mgr=None):
        to_rep_is_list = is_list_like(to_replace)
        value_is_list = is_list_like(value)
        both_lists = to_rep_is_list and value_is_list
        either_list = to_rep_is_list or value_is_list

        result_blocks = []
        blocks = [self]

        if not either_list and is_re(to_replace):
            return self._replace_single(to_replace, value, inplace=inplace,
                                        filter=filter, regex=True,
                                        convert=convert, mgr=mgr)
        elif not (either_list or regex):
            return super(ObjectBlock, self).replace(to_replace, value,
                                                    inplace=inplace,
                                                    filter=filter, regex=regex,
                                                    convert=convert, mgr=mgr)
        elif both_lists:
            for to_rep, v in zip(to_replace, value):
                result_blocks = []
                for b in blocks:
                    result = b._replace_single(to_rep, v, inplace=inplace,
                                               filter=filter, regex=regex,
                                               convert=convert, mgr=mgr)
                    result_blocks = _extend_blocks(result, result_blocks)
                blocks = result_blocks
            return result_blocks

        elif to_rep_is_list and regex:
            for to_rep in to_replace:
                result_blocks = []
                for b in blocks:
                    result = b._replace_single(to_rep, value, inplace=inplace,
                                               filter=filter, regex=regex,
                                               convert=convert, mgr=mgr)
                    result_blocks = _extend_blocks(result, result_blocks)
                blocks = result_blocks
            return result_blocks

        return self._replace_single(to_replace, value, inplace=inplace,
                                    filter=filter, convert=convert,
                                    regex=regex, mgr=mgr)

    def _replace_single(self, to_replace, value, inplace=False, filter=None,
                        regex=False, convert=True, mgr=None):

        inplace = validate_bool_kwarg(inplace, 'inplace')

        # to_replace is regex compilable
        to_rep_re = regex and is_re_compilable(to_replace)

        # regex is regex compilable
        regex_re = is_re_compilable(regex)

        # only one will survive
        if to_rep_re and regex_re:
            raise AssertionError('only one of to_replace and regex can be '
                                 'regex compilable')

        # if regex was passed as something that can be a regex (rather than a
        # boolean)
        if regex_re:
            to_replace = regex

        regex = regex_re or to_rep_re

        # try to get the pattern attribute (compiled re) or it's a string
        try:
            pattern = to_replace.pattern
        except AttributeError:
            pattern = to_replace

        # if the pattern is not empty and to_replace is either a string or a
        # regex
        if regex and pattern:
            rx = re.compile(to_replace)
        else:
            # if the thing to replace is not a string or compiled regex call
            # the superclass method -> to_replace is some kind of object
            return super(ObjectBlock, self).replace(to_replace, value,
                                                    inplace=inplace,
                                                    filter=filter, regex=regex,
                                                    mgr=mgr)

        new_values = self.values if inplace else self.values.copy()

        # deal with replacing values with objects (strings) that match but
        # whose replacement is not a string (numeric, nan, object)
        if isna(value) or not isinstance(value, compat.string_types):

            def re_replacer(s):
                try:
                    return value if rx.search(s) is not None else s
                except TypeError:
                    return s
        else:
            # value is guaranteed to be a string here, s can be either a string
            # or null if it's null it gets returned
            def re_replacer(s):
                try:
                    return rx.sub(value, s)
                except TypeError:
                    return s

        f = np.vectorize(re_replacer, otypes=[self.dtype])

        if filter is None:
            filt = slice(None)
        else:
            filt = self.mgr_locs.isin(filter).nonzero()[0]

        new_values[filt] = f(new_values[filt])

        # convert
        block = self.make_block(new_values)
        if convert:
            block = block.convert(by_item=True, numeric=False)

        return block


class CategoricalBlock(ExtensionBlock):
    __slots__ = ()
    is_categorical = True
    _verify_integrity = True
    _can_hold_na = True
    _concatenator = staticmethod(_concat._concat_categorical)

    def __init__(self, values, placement, ndim=None):
        from pandas.core.arrays.categorical import _maybe_to_categorical

        # coerce to categorical if we can
        super(CategoricalBlock, self).__init__(_maybe_to_categorical(values),
                                               placement=placement,
                                               ndim=ndim)

    @property
    def _holder(self):
        return Categorical

    @property
    def array_dtype(self):
        """ the dtype to return if I want to construct this block as an
        array
        """
        return np.object_

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args """

        # GH12564: CategoricalBlock is 1-dim only
        # while returned results could be any dim
        if ((not is_categorical_dtype(result)) and
                isinstance(result, np.ndarray)):
            result = _block_shape(result, ndim=self.ndim)

        return result

    def shift(self, periods, axis=0, mgr=None):
        return self.make_block_same_class(values=self.values.shift(periods),
                                          placement=self.mgr_locs)

    def to_dense(self):
        # Categorical.get_values returns a DatetimeIndex for datetime
        # categories, so we can't simply use `np.asarray(self.values)` like
        # other types.
        return self.values.get_values()

    def to_native_types(self, slicer=None, na_rep='', quoting=None, **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            # Categorical is always one dimension
            values = values[slicer]
        mask = isna(values)
        values = np.array(values, dtype='object')
        values[mask] = na_rep

        # we are expected to return a 2-d ndarray
        return values.reshape(1, len(values))

    def concat_same_type(self, to_concat, placement=None):
        """
        Concatenate list of single blocks of the same type.

        Note that this CategoricalBlock._concat_same_type *may* not
        return a CategoricalBlock. When the categories in `to_concat`
        differ, this will return an object ndarray.

        If / when we decide we don't like that behavior:

        1. Change Categorical._concat_same_type to use union_categoricals
        2. Delete this method.
        """
        values = self._concatenator([blk.values for blk in to_concat],
                                    axis=self.ndim - 1)
        # not using self.make_block_same_class as values can be object dtype
        return make_block(
            values, placement=placement or slice(0, len(values), 1),
            ndim=self.ndim)


class DatetimeBlock(DatetimeLikeBlockMixin, Block):
    __slots__ = ()
    is_datetime = True
    _can_hold_na = True

    def __init__(self, values, placement, ndim=None):
        values = self._maybe_coerce_values(values)
        super(DatetimeBlock, self).__init__(values,
                                            placement=placement, ndim=ndim)

    def _maybe_coerce_values(self, values):
        """Input validation for values passed to __init__. Ensure that
        we have datetime64ns, coercing if necessary.

        Parameters
        ----------
        values : array-like
            Must be convertible to datetime64

        Returns
        -------
        values : ndarray[datetime64ns]

        Overridden by DatetimeTZBlock.
        """
        if values.dtype != _NS_DTYPE:
            values = conversion.ensure_datetime64ns(values)
        return values

    def _astype(self, dtype, mgr=None, **kwargs):
        """
        these automatically copy, so copy=True has no effect
        raise on an except if raise == True
        """

        # if we are passed a datetime64[ns, tz]
        if is_datetime64tz_dtype(dtype):
            dtype = DatetimeTZDtype(dtype)

            values = self.values
            if getattr(values, 'tz', None) is None:
                values = DatetimeIndex(values).tz_localize('UTC')
            values = values.tz_convert(dtype.tz)
            return self.make_block(values)

        # delegate
        return super(DatetimeBlock, self)._astype(dtype=dtype, **kwargs)

    def _can_hold_element(self, element):
        tipo = maybe_infer_dtype_type(element)
        if tipo is not None:
            # TODO: this still uses asarray, instead of dtype.type
            element = np.array(element)
            return element.dtype == _NS_DTYPE or element.dtype == np.int64
        return (is_integer(element) or isinstance(element, datetime) or
                isna(element))

    def _try_coerce_args(self, values, other):
        """
        Coerce values and other to dtype 'i8'. NaN and NaT convert to
        the smallest i8, and will correctly round-trip to NaT if converted
        back in _try_coerce_result. values is always ndarray-like, other
        may not be

        Parameters
        ----------
        values : ndarray-like
        other : ndarray-like or scalar

        Returns
        -------
        base-type values, values mask, base-type other, other mask
        """

        values_mask = isna(values)
        values = values.view('i8')
        other_mask = False

        if isinstance(other, bool):
            raise TypeError
        elif is_null_datelike_scalar(other):
            other = tslibs.iNaT
            other_mask = True
        elif isinstance(other, (datetime, np.datetime64, date)):
            other = self._box_func(other)
            if getattr(other, 'tz') is not None:
                raise TypeError("cannot coerce a Timestamp with a tz on a "
                                "naive Block")
            other_mask = isna(other)
            other = other.asm8.view('i8')
        elif hasattr(other, 'dtype') and is_datetime64_dtype(other):
            other_mask = isna(other)
            other = other.astype('i8', copy=False).view('i8')
        else:
            # coercion issues
            # let higher levels handle
            raise TypeError

        return values, values_mask, other, other_mask

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args """
        if isinstance(result, np.ndarray):
            if result.dtype.kind in ['i', 'f', 'O']:
                try:
                    result = result.astype('M8[ns]')
                except ValueError:
                    pass
        elif isinstance(result, (np.integer, np.float, np.datetime64)):
            result = self._box_func(result)
        return result

    @property
    def _box_func(self):
        return tslibs.Timestamp

    def to_native_types(self, slicer=None, na_rep=None, date_format=None,
                        quoting=None, **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            values = values[..., slicer]

        from pandas.io.formats.format import _get_format_datetime64_from_values
        format = _get_format_datetime64_from_values(values, date_format)

        result = tslib.format_array_from_datetime(
            values.view('i8').ravel(), tz=getattr(self.values, 'tz', None),
            format=format, na_rep=na_rep).reshape(values.shape)
        return np.atleast_2d(result)

    def should_store(self, value):
        return (issubclass(value.dtype.type, np.datetime64) and
                not is_datetimetz(value))

    def set(self, locs, values, check=False):
        """
        Modify Block in-place with new item value

        Returns
        -------
        None
        """
        if values.dtype != _NS_DTYPE:
            # Workaround for numpy 1.6 bug
            values = conversion.ensure_datetime64ns(values)

        self.values[locs] = values


class DatetimeTZBlock(NonConsolidatableMixIn, DatetimeBlock):
    """ implement a datetime64 block with a tz attribute """
    __slots__ = ()
    _concatenator = staticmethod(_concat._concat_datetime)
    is_datetimetz = True

    def __init__(self, values, placement, ndim=2, dtype=None):
        # XXX: This will end up calling _maybe_coerce_values twice
        # when dtype is not None. It's relatively cheap (just an isinstance)
        # but it'd nice to avoid.
        #
        # If we can remove dtype from __init__, and push that conversion
        # push onto the callers, then we can remove this entire __init__
        # and just use DatetimeBlock's.
        if dtype is not None:
            values = self._maybe_coerce_values(values, dtype=dtype)
        super(DatetimeTZBlock, self).__init__(values, placement=placement,
                                              ndim=ndim)

    def _maybe_coerce_values(self, values, dtype=None):
        """Input validation for values passed to __init__. Ensure that
        we have datetime64TZ, coercing if necessary.

        Parametetrs
        -----------
        values : array-like
            Must be convertible to datetime64
        dtype : string or DatetimeTZDtype, optional
            Does a shallow copy to this tz

        Returns
        -------
        values : ndarray[datetime64ns]
        """
        if not isinstance(values, self._holder):
            values = self._holder(values)

        if dtype is not None:
            if isinstance(dtype, compat.string_types):
                dtype = DatetimeTZDtype.construct_from_string(dtype)
            values = values._shallow_copy(tz=dtype.tz)

        if values.tz is None:
            raise ValueError("cannot create a DatetimeTZBlock without a tz")

        return values

    @property
    def is_view(self):
        """ return a boolean if I am possibly a view """
        # check the ndarray values of the DatetimeIndex values
        return self.values.values.base is not None

    def copy(self, deep=True, mgr=None):
        """ copy constructor """
        values = self.values
        if deep:
            values = values.copy(deep=True)
        return self.make_block_same_class(values)

    def external_values(self):
        """ we internally represent the data as a DatetimeIndex, but for
        external compat with ndarray, export as a ndarray of Timestamps
        """
        return self.values.astype('datetime64[ns]').values

    def get_values(self, dtype=None):
        # return object dtype as Timestamps with the zones
        if is_object_dtype(dtype):
            return lib.map_infer(
                self.values.ravel(), self._box_func).reshape(self.values.shape)
        return self.values

    def _slice(self, slicer):
        """ return a slice of my values """
        if isinstance(slicer, tuple):
            col, loc = slicer
            if not com.is_null_slice(col) and col != 0:
                raise IndexError("{0} only contains one item".format(self))
            return self.values[loc]
        return self.values[slicer]

    def _try_coerce_args(self, values, other):
        """
        localize and return i8 for the values

        Parameters
        ----------
        values : ndarray-like
        other : ndarray-like or scalar

        Returns
        -------
        base-type values, values mask, base-type other, other mask
        """
        values_mask = _block_shape(isna(values), ndim=self.ndim)
        # asi8 is a view, needs copy
        values = _block_shape(values.asi8, ndim=self.ndim)
        other_mask = False

        if isinstance(other, ABCSeries):
            other = self._holder(other)
            other_mask = isna(other)

        if isinstance(other, bool):
            raise TypeError
        elif (is_null_datelike_scalar(other) or
              (lib.is_scalar(other) and isna(other))):
            other = tslibs.iNaT
            other_mask = True
        elif isinstance(other, self._holder):
            if other.tz != self.values.tz:
                raise ValueError("incompatible or non tz-aware value")
            other_mask = _block_shape(isna(other), ndim=self.ndim)
            other = _block_shape(other.asi8, ndim=self.ndim)
        elif isinstance(other, (np.datetime64, datetime, date)):
            other = tslibs.Timestamp(other)
            tz = getattr(other, 'tz', None)

            # test we can have an equal time zone
            if tz is None or str(tz) != str(self.values.tz):
                raise ValueError("incompatible or non tz-aware value")
            other_mask = isna(other)
            other = other.value
        else:
            raise TypeError

        return values, values_mask, other, other_mask

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args """
        if isinstance(result, np.ndarray):
            if result.dtype.kind in ['i', 'f', 'O']:
                result = result.astype('M8[ns]')
        elif isinstance(result, (np.integer, np.float, np.datetime64)):
            result = tslibs.Timestamp(result, tz=self.values.tz)
        if isinstance(result, np.ndarray):
            # allow passing of > 1dim if its trivial
            if result.ndim > 1:
                result = result.reshape(np.prod(result.shape))
            result = self.values._shallow_copy(result)

        return result

    @property
    def _box_func(self):
        return lambda x: tslibs.Timestamp(x, tz=self.dtype.tz)

    def shift(self, periods, axis=0, mgr=None):
        """ shift the block by periods """

        # think about moving this to the DatetimeIndex. This is a non-freq
        # (number of periods) shift ###

        N = len(self)
        indexer = np.zeros(N, dtype=int)
        if periods > 0:
            indexer[periods:] = np.arange(N - periods)
        else:
            indexer[:periods] = np.arange(-periods, N)

        new_values = self.values.asi8.take(indexer)

        if periods > 0:
            new_values[:periods] = tslibs.iNaT
        else:
            new_values[periods:] = tslibs.iNaT

        new_values = self.values._shallow_copy(new_values)
        return [self.make_block_same_class(new_values,
                                           placement=self.mgr_locs)]

    def diff(self, n, axis=0, mgr=None):
        """1st discrete difference

        Parameters
        ----------
        n : int, number of periods to diff
        axis : int, axis to diff upon. default 0
        mgr : default None

        Return
        ------
        A list with a new TimeDeltaBlock.

        Note
        ----
        The arguments here are mimicking shift so they are called correctly
        by apply.
        """
        if axis == 0:
            # Cannot currently calculate diff across multiple blocks since this
            # function is invoked via apply
            raise NotImplementedError
        new_values = (self.values - self.shift(n, axis=axis)[0].values).asi8

        # Reshape the new_values like how algos.diff does for timedelta data
        new_values = new_values.reshape(1, len(new_values))
        new_values = new_values.astype('timedelta64[ns]')
        return [TimeDeltaBlock(new_values, placement=self.mgr_locs.indexer)]

    def concat_same_type(self, to_concat, placement=None):
        """
        Concatenate list of single blocks of the same type.
        """
        values = self._concatenator([blk.values for blk in to_concat],
                                    axis=self.ndim - 1)
        # not using self.make_block_same_class as values can be non-tz dtype
        return make_block(
            values, placement=placement or slice(0, len(values), 1))


class SparseBlock(NonConsolidatableMixIn, Block):
    """ implement as a list of sparse arrays of the same dtype """
    __slots__ = ()
    is_sparse = True
    is_numeric = True
    _box_to_block_values = False
    _can_hold_na = True
    _ftype = 'sparse'
    _concatenator = staticmethod(_concat._concat_sparse)

    def __init__(self, values, placement, ndim=None):
        # Ensure that we have the underlying SparseArray here...
        if isinstance(values, ABCSeries):
            values = values.values
        assert isinstance(values, SparseArray)
        super(SparseBlock, self).__init__(values, placement, ndim=ndim)

    @property
    def _holder(self):
        return SparseArray

    @property
    def shape(self):
        return (len(self.mgr_locs), self.sp_index.length)

    @property
    def fill_value(self):
        # return np.nan
        return self.values.fill_value

    @fill_value.setter
    def fill_value(self, v):
        self.values.fill_value = v

    def to_dense(self):
        return self.values.to_dense().view()

    @property
    def sp_values(self):
        return self.values.sp_values

    @sp_values.setter
    def sp_values(self, v):
        # reset the sparse values
        self.values = SparseArray(v, sparse_index=self.sp_index,
                                  kind=self.kind, dtype=v.dtype,
                                  fill_value=self.values.fill_value,
                                  copy=False)

    @property
    def sp_index(self):
        return self.values.sp_index

    @property
    def kind(self):
        return self.values.kind

    def _astype(self, dtype, copy=False, errors='raise', values=None,
                klass=None, mgr=None, **kwargs):
        if values is None:
            values = self.values
        values = values.astype(dtype, copy=copy)
        return self.make_block_same_class(values=values,
                                          placement=self.mgr_locs)

    def __len__(self):
        try:
            return self.sp_index.length
        except:
            return 0

    def copy(self, deep=True, mgr=None):
        return self.make_block_same_class(values=self.values,
                                          sparse_index=self.sp_index,
                                          kind=self.kind, copy=deep,
                                          placement=self.mgr_locs)

    def make_block_same_class(self, values, placement, sparse_index=None,
                              kind=None, dtype=None, fill_value=None,
                              copy=False, ndim=None):
        """ return a new block """
        if dtype is None:
            dtype = values.dtype
        if fill_value is None and not isinstance(values, SparseArray):
            fill_value = self.values.fill_value

        # if not isinstance(values, SparseArray) and values.ndim != self.ndim:
        #     raise ValueError("ndim mismatch")

        if values.ndim == 2:
            nitems = values.shape[0]

            if nitems == 0:
                # kludgy, but SparseBlocks cannot handle slices, where the
                # output is 0-item, so let's convert it to a dense block: it
                # won't take space since there's 0 items, plus it will preserve
                # the dtype.
                return self.make_block(np.empty(values.shape, dtype=dtype),
                                       placement)
            elif nitems > 1:
                raise ValueError("Only 1-item 2d sparse blocks are supported")
            else:
                values = values.reshape(values.shape[1])

        new_values = SparseArray(values, sparse_index=sparse_index,
                                 kind=kind or self.kind, dtype=dtype,
                                 fill_value=fill_value, copy=copy)
        return self.make_block(new_values,
                               placement=placement)

    def interpolate(self, method='pad', axis=0, inplace=False, limit=None,
                    fill_value=None, **kwargs):

        values = missing.interpolate_2d(self.values.to_dense(), method, axis,
                                        limit, fill_value)
        return self.make_block_same_class(values=values,
                                          placement=self.mgr_locs)

    def fillna(self, value, limit=None, inplace=False, downcast=None,
               mgr=None):
        # we may need to upcast our fill to match our dtype
        if limit is not None:
            raise NotImplementedError("specifying a limit for 'fillna' has "
                                      "not been implemented yet")
        values = self.values if inplace else self.values.copy()
        values = values.fillna(value, downcast=downcast)
        return [self.make_block_same_class(values=values,
                                           placement=self.mgr_locs)]

    def shift(self, periods, axis=0, mgr=None):
        """ shift the block by periods """
        N = len(self.values.T)
        indexer = np.zeros(N, dtype=int)
        if periods > 0:
            indexer[periods:] = np.arange(N - periods)
        else:
            indexer[:periods] = np.arange(-periods, N)
        new_values = self.values.to_dense().take(indexer)
        # convert integer to float if necessary. need to do a lot more than
        # that, handle boolean etc also
        new_values, fill_value = maybe_upcast(new_values)
        if periods > 0:
            new_values[:periods] = fill_value
        else:
            new_values[periods:] = fill_value
        return [self.make_block_same_class(new_values,
                                           placement=self.mgr_locs)]

    def sparse_reindex(self, new_index):
        """ sparse reindex and return a new block
            current reindex only works for float64 dtype! """
        values = self.values
        values = values.sp_index.to_int_index().reindex(
            values.sp_values.astype('float64'), values.fill_value, new_index)
        return self.make_block_same_class(values, sparse_index=new_index,
                                          placement=self.mgr_locs)


# -----------------------------------------------------------------
# Constructor Helpers

def get_block_type(values, dtype=None):
    """
    Find the appropriate Block subclass to use for the given values and dtype.

    Parameters
    ----------
    values : ndarray-like
    dtype : numpy or pandas dtype

    Returns
    -------
    cls : class, subclass of Block
    """
    dtype = dtype or values.dtype
    vtype = dtype.type

    if is_sparse(values):
        cls = SparseBlock
    elif issubclass(vtype, np.floating):
        cls = FloatBlock
    elif issubclass(vtype, np.timedelta64):
        assert issubclass(vtype, np.integer)
        cls = TimeDeltaBlock
    elif issubclass(vtype, np.complexfloating):
        cls = ComplexBlock
    elif is_categorical(values):
        cls = CategoricalBlock
    elif is_extension_array_dtype(values):
        cls = ExtensionBlock
    elif issubclass(vtype, np.datetime64):
        assert not is_datetimetz(values)
        cls = DatetimeBlock
    elif is_datetimetz(values):
        cls = DatetimeTZBlock
    elif issubclass(vtype, np.integer):
        cls = IntBlock
    elif dtype == np.bool_:
        cls = BoolBlock
    else:
        cls = ObjectBlock
    return cls


def make_block(values, placement, klass=None, ndim=None, dtype=None,
               fastpath=None):
    if fastpath is not None:
        # GH#19265 pyarrow is passing this
        warnings.warn("fastpath argument is deprecated, will be removed "
                      "in a future release.", DeprecationWarning)
    if klass is None:
        dtype = dtype or values.dtype
        klass = get_block_type(values, dtype)

    elif klass is DatetimeTZBlock and not is_datetimetz(values):
        return klass(values, ndim=ndim,
                     placement=placement, dtype=dtype)

    return klass(values, ndim=ndim, placement=placement)


# -----------------------------------------------------------------

def _extend_blocks(result, blocks=None):
    """ return a new extended blocks, givin the result """
    from pandas.core.internals import BlockManager
    if blocks is None:
        blocks = []
    if isinstance(result, list):
        for r in result:
            if isinstance(r, list):
                blocks.extend(r)
            else:
                blocks.append(r)
    elif isinstance(result, BlockManager):
        blocks.extend(result.blocks)
    else:
        blocks.append(result)
    return blocks


def _block_shape(values, ndim=1, shape=None):
    """ guarantee the shape of the values to be at least 1 d """
    if values.ndim < ndim:
        if shape is None:
            shape = values.shape
        values = values.reshape(tuple((1, ) + shape))
    return values


def _merge_blocks(blocks, dtype=None, _can_consolidate=True):

    if len(blocks) == 1:
        return blocks[0]

    if _can_consolidate:

        if dtype is None:
            if len({b.dtype for b in blocks}) != 1:
                raise AssertionError("_merge_blocks are invalid!")
            dtype = blocks[0].dtype

        # FIXME: optimization potential in case all mgrs contain slices and
        # combination of those slices is a slice, too.
        new_mgr_locs = np.concatenate([b.mgr_locs.as_array for b in blocks])
        new_values = _vstack([b.values for b in blocks], dtype)

        argsort = np.argsort(new_mgr_locs)
        new_values = new_values[argsort]
        new_mgr_locs = new_mgr_locs[argsort]

        return make_block(new_values, placement=new_mgr_locs)

    # no merge
    return blocks


def _vstack(to_stack, dtype):

    # work around NumPy 1.6 bug
    if dtype == _NS_DTYPE or dtype == _TD_DTYPE:
        new_values = np.vstack([x.view('i8') for x in to_stack])
        return new_values.view(dtype)

    else:
        return np.vstack(to_stack)


def _block2d_to_blocknd(values, placement, shape, labels, ref_items):
    """ pivot to the labels shape """
    panel_shape = (len(placement),) + shape

    # TODO: lexsort depth needs to be 2!!

    # Create observation selection vector using major and minor
    # labels, for converting to panel format.
    selector = _factor_indexer(shape[1:], labels)
    mask = np.zeros(np.prod(shape), dtype=bool)
    mask.put(selector, True)

    if mask.all():
        pvalues = np.empty(panel_shape, dtype=values.dtype)
    else:
        dtype, fill_value = maybe_promote(values.dtype)
        pvalues = np.empty(panel_shape, dtype=dtype)
        pvalues.fill(fill_value)

    for i in range(len(placement)):
        pvalues[i].flat[mask] = values[:, i]

    return make_block(pvalues, placement=placement)


def _safe_reshape(arr, new_shape):
    """
    If possible, reshape `arr` to have shape `new_shape`,
    with a couple of exceptions (see gh-13012):

    1) If `arr` is a ExtensionArray or Index, `arr` will be
       returned as is.
    2) If `arr` is a Series, the `_values` attribute will
       be reshaped and returned.

    Parameters
    ----------
    arr : array-like, object to be reshaped
    new_shape : int or tuple of ints, the new shape
    """
    if isinstance(arr, ABCSeries):
        arr = arr._values
    if not isinstance(arr, ABCExtensionArray):
        arr = arr.reshape(new_shape)
    return arr


def _factor_indexer(shape, labels):
    """
    given a tuple of shape and a list of Categorical labels, return the
    expanded label indexer
    """
    mult = np.array(shape)[::-1].cumprod()[::-1]
    return ensure_platform_int(
        np.sum(np.array(labels).T * np.append(mult, [1]), axis=1).T)


def _putmask_smart(v, m, n):
    """
    Return a new ndarray, try to preserve dtype if possible.

    Parameters
    ----------
    v : `values`, updated in-place (array like)
    m : `mask`, applies to both sides (array like)
    n : `new values` either scalar or an array like aligned with `values`

    Returns
    -------
    values : ndarray with updated values
        this *may* be a copy of the original

    See Also
    --------
    ndarray.putmask
    """

    # we cannot use np.asarray() here as we cannot have conversions
    # that numpy does when numeric are mixed with strings

    # n should be the length of the mask or a scalar here
    if not is_list_like(n):
        n = np.repeat(n, len(m))
    elif isinstance(n, np.ndarray) and n.ndim == 0:  # numpy scalar
        n = np.repeat(np.array(n, ndmin=1), len(m))

    # see if we are only masking values that if putted
    # will work in the current dtype
    try:
        nn = n[m]

        # make sure that we have a nullable type
        # if we have nulls
        if not _isna_compat(v, nn[0]):
            raise ValueError

        # we ignore ComplexWarning here
        with warnings.catch_warnings(record=True):
            nn_at = nn.astype(v.dtype)

        # avoid invalid dtype comparisons
        # between numbers & strings

        # only compare integers/floats
        # don't compare integers to datetimelikes
        if (not is_numeric_v_string_like(nn, nn_at) and
            (is_float_dtype(nn.dtype) or
             is_integer_dtype(nn.dtype) and
             is_float_dtype(nn_at.dtype) or
             is_integer_dtype(nn_at.dtype))):

            comp = (nn == nn_at)
            if is_list_like(comp) and comp.all():
                nv = v.copy()
                nv[m] = nn_at
                return nv
    except (ValueError, IndexError, TypeError):
        pass

    n = np.asarray(n)

    def _putmask_preserve(nv, n):
        try:
            nv[m] = n[m]
        except (IndexError, ValueError):
            nv[m] = n
        return nv

    # preserves dtype if possible
    if v.dtype.kind == n.dtype.kind:
        return _putmask_preserve(v, n)

    # change the dtype if needed
    dtype, _ = maybe_promote(n.dtype)

    if is_extension_type(v.dtype) and is_object_dtype(dtype):
        v = v.get_values(dtype)
    else:
        v = v.astype(dtype)

    return _putmask_preserve(v, n)
