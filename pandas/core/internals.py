import itertools
import re
from datetime import datetime
import copy
from collections import defaultdict

import numpy as np
from pandas.core.base import PandasObject

from pandas.core.common import (_possibly_downcast_to_dtype, isnull, _NS_DTYPE,
                                _TD_DTYPE, is_series, is_sparse_series)
from pandas.core.index import (Index, MultiIndex, _ensure_index,
                               _handle_legacy_indexes)
from pandas.core.indexing import _check_slice_bounds, _maybe_convert_indices
import pandas.core.common as com
from pandas.sparse.array import _maybe_to_sparse, SparseArray
import pandas.lib as lib
import pandas.tslib as tslib
import pandas.core.expressions as expressions
from pandas.util.decorators import cache_readonly

from pandas.tslib import Timestamp
from pandas import compat
from pandas.compat import range, lrange, lmap, callable, map, zip
from pandas.util import rwproperty


class Block(PandasObject):

    """
    Canonical n-dimensional unit of homogeneous dtype contained in a pandas
    data structure

    Index-ignorant; let the container take care of that
    """
    __slots__ = ['items', 'ref_items', '_ref_locs', 'values', 'ndim']
    is_numeric = False
    is_bool = False
    is_object = False
    is_sparse = False
    _can_hold_na = False
    _downcast_dtype = None
    _can_consolidate = True
    _verify_integrity = True
    _ftype = 'dense'

    def __init__(self, values, items, ref_items, ndim=None, fastpath=False, placement=None):

        if ndim is None:
            ndim = values.ndim

        if values.ndim != ndim:
            raise ValueError('Wrong number of dimensions')

        if len(items) != len(values):
            raise ValueError('Wrong number of items passed %d, indices imply %d'
                             % (len(items), len(values)))

        self.set_ref_locs(placement)
        self.values = values
        self.ndim = ndim

        if fastpath:
            self.items = items
            self.ref_items = ref_items
        else:
            self.items = _ensure_index(items)
            self.ref_items = _ensure_index(ref_items)

    def _gi(self, arg):
        return self.values[arg]

    @property
    def _consolidate_key(self):
        return (self._can_consolidate, self.dtype.name)

    @property
    def _is_single_block(self):
        return self.ndim == 1

    @property
    def fill_value(self):
        return np.nan

    @property
    def ref_locs(self):
        if self._ref_locs is None:
            # we have a single block, maybe have duplicates
            # but indexer is easy
            # also if we are not really reindexing, just numbering
            if self._is_single_block or self.ref_items.equals(self.items):
                indexer = np.arange(len(self.items))
            else:

                indexer = self.ref_items.get_indexer(self.items)
                indexer = com._ensure_platform_int(indexer)
                if (indexer == -1).any():
                    raise AssertionError('Some block items were not in block '
                                         'ref_items')

            self._ref_locs = indexer
        return self._ref_locs

    def reset_ref_locs(self):
        """ reset the block ref_locs """
        self._ref_locs = np.empty(len(self.items), dtype='int64')

    def set_ref_locs(self, placement):
        """ explicity set the ref_locs indexer, only necessary for duplicate indicies """
        if placement is None:
            self._ref_locs = None
        else:
            self._ref_locs = np.array(placement, dtype='int64', copy=True)

    def set_ref_items(self, ref_items, maybe_rename=True):
        """
        If maybe_rename=True, need to set the items for this guy
        """
        if not isinstance(ref_items, Index):
            raise AssertionError('block ref_items must be an Index')
        if maybe_rename == 'clear':
            self._ref_locs = None
        elif maybe_rename:
            self.items = ref_items.take(self.ref_locs)
        self.ref_items = ref_items

    def __unicode__(self):

        # don't want to print out all of the items here
        name = com.pprint_thing(self.__class__.__name__)
        if self._is_single_block:

            result = '%s: %s dtype: %s' % (
                name, len(self), self.dtype)

        else:

            shape = ' x '.join([com.pprint_thing(s) for s in self.shape])
            result = '%s: %s, %s, dtype: %s' % (
                name, com.pprint_thing(self.items), shape, self.dtype)

        return result

    def __contains__(self, item):
        return item in self.items

    def __len__(self):
        return len(self.values)

    def __getstate__(self):
        # should not pickle generally (want to share ref_items), but here for
        # completeness
        return (self.items, self.ref_items, self.values)

    def __setstate__(self, state):
        items, ref_items, values = state
        self.items = _ensure_index(items)
        self.ref_items = _ensure_index(ref_items)
        self.values = values
        self.ndim = values.ndim

    def _slice(self, slicer):
        """ return a slice of my values """
        return self.values[slicer]

    @property
    def shape(self):
        return self.values.shape

    @property
    def itemsize(self):
        return self.values.itemsize

    @property
    def dtype(self):
        return self.values.dtype

    def copy(self, deep=True, ref_items=None):
        values = self.values
        if deep:
            values = values.copy()
        if ref_items is None:
            ref_items = self.ref_items
        return make_block(
            values, self.items, ref_items, ndim=self.ndim, klass=self.__class__,
            fastpath=True, placement=self._ref_locs)

    @property
    def ftype(self):
        return "%s:%s" % (self.dtype, self._ftype)

    def merge(self, other):
        if not self.ref_items.equals(other.ref_items):
            raise AssertionError('Merge operands must have same ref_items')

        # Not sure whether to allow this or not
        # if not union_ref.equals(other.ref_items):
        #     union_ref = self.ref_items + other.ref_items
        return _merge_blocks([self, other], self.ref_items)

    def reindex_axis(self, indexer, method=None, axis=1, fill_value=None, limit=None, mask_info=None):
        """
        Reindex using pre-computed indexer information
        """
        if axis < 1:
            raise AssertionError('axis must be at least 1, got %d' % axis)
        if fill_value is None:
            fill_value = self.fill_value
        new_values = com.take_nd(self.values, indexer, axis,
                                 fill_value=fill_value, mask_info=mask_info)
        return make_block(
            new_values, self.items, self.ref_items, ndim=self.ndim, fastpath=True,
            placement=self._ref_locs)

    def reindex_items_from(self, new_ref_items, copy=True):
        """
        Reindex to only those items contained in the input set of items

        E.g. if you have ['a', 'b'], and the input items is ['b', 'c', 'd'],
        then the resulting items will be ['b']

        Returns
        -------
        reindexed : Block
        """
        new_ref_items, indexer = self.items.reindex(new_ref_items)

        if indexer is None:
            new_items = new_ref_items
            new_values = self.values.copy() if copy else self.values
        else:
            masked_idx = indexer[indexer != -1]
            new_values = com.take_nd(self.values, masked_idx, axis=0,
                                     allow_fill=False)
            new_items = self.items.take(masked_idx)
        return make_block(new_values, new_items, new_ref_items, ndim=self.ndim, fastpath=True)

    def get(self, item):
        loc = self.items.get_loc(item)
        return self.values[loc]

    def iget(self, i):
        return self.values[i]

    def set(self, item, value):
        """
        Modify Block in-place with new item value

        Returns
        -------
        None
        """
        loc = self.items.get_loc(item)
        self.values[loc] = value

    def delete(self, item):
        """
        Returns
        -------
        y : Block (new object)
        """
        loc = self.items.get_loc(item)
        new_items = self.items.delete(loc)
        new_values = np.delete(self.values, loc, 0)
        return make_block(new_values, new_items, self.ref_items, ndim=self.ndim, klass=self.__class__, fastpath=True)

    def split_block_at(self, item):
        """
        Split block into zero or more blocks around columns with given label,
        for "deleting" a column without having to copy data by returning views
        on the original array.

        Returns
        -------
        generator of Block
        """
        loc = self.items.get_loc(item)

        if type(loc) == slice or type(loc) == int:
            mask = [True] * len(self)
            mask[loc] = False
        else:  # already a mask, inverted
            mask = -loc

        for s, e in com.split_ranges(mask):
            yield make_block(self.values[s:e],
                             self.items[s:e].copy(),
                             self.ref_items,
                             ndim=self.ndim,
                             klass=self.__class__,
                             fastpath=True)

    def fillna(self, value, inplace=False, downcast=None):
        if not self._can_hold_na:
            if inplace:
                return self
            else:
                return self.copy()

        mask = com.isnull(self.values)
        value = self._try_fill(value)
        blocks = self.putmask(mask, value, inplace=inplace)

        if downcast:
            blocks = [ b.downcast() for b in blocks ]
        return blocks

    def downcast(self, dtypes=None):
        """ try to downcast each item to the dict of dtypes if present """

        if dtypes is None:
            dtypes = dict()

        values = self.values
        blocks = []
        for i, item in enumerate(self.items):

            dtype = dtypes.get(item, self._downcast_dtype)
            if dtype is None:
                nv = _block_shape(values[i])
                blocks.append(make_block(nv, [item], self.ref_items))
                continue

            nv = _possibly_downcast_to_dtype(values[i], np.dtype(dtype))
            nv = _block_shape(nv)
            blocks.append(make_block(nv, [item], self.ref_items))

        return blocks

    def astype(self, dtype, copy=False, raise_on_error=True, values=None):
        return self._astype(dtype, copy=copy, raise_on_error=raise_on_error,
                            values=values)

    def _astype(self, dtype, copy=False, raise_on_error=True, values=None,
                klass=None):
        """
        Coerce to the new type (if copy=True, return a new copy)
        raise on an except if raise == True
        """
        dtype = np.dtype(dtype)
        if self.dtype == dtype:
            if copy:
                return self.copy()
            return self

        try:
            # force the copy here
            if values is None:
                values = com._astype_nansafe(self.values, dtype, copy=True)
            newb = make_block(
                values, self.items, self.ref_items, ndim=self.ndim,
                fastpath=True, dtype=dtype, klass=klass)
        except:
            if raise_on_error is True:
                raise
            newb = self.copy() if copy else self

        if newb.is_numeric and self.is_numeric:
            if newb.shape != self.shape:
                raise TypeError("cannot set astype for copy = [%s] for dtype "
                                "(%s [%s]) with smaller itemsize that current "
                                "(%s [%s])" % (copy, self.dtype.name,
                                               self.itemsize, newb.dtype.name, newb.itemsize))
        return newb

    def convert(self, copy=True, **kwargs):
        """ attempt to coerce any object types to better types
            return a copy of the block (if copy = True)
            by definition we are not an ObjectBlock here!  """

        return self.copy() if copy else self

    def prepare_for_merge(self, **kwargs):
        """ a regular block is ok to merge as is """
        return self

    def post_merge(self, items, **kwargs):
        """ we are non-sparse block, try to convert to a sparse block(s) """
        overlap = set(items.keys()) & set(self.items)
        if len(overlap):
            overlap = _ensure_index(overlap)

            new_blocks = []
            for item in overlap:
                dtypes = set(items[item])

                # this is a safe bet with multiple dtypes
                dtype = list(dtypes)[0] if len(dtypes) == 1 else np.float64

                b = make_block(
                    SparseArray(self.get(item), dtype=dtype), [item], self.ref_items)
                new_blocks.append(b)

            return new_blocks

        return self

    def _can_hold_element(self, value):
        raise NotImplementedError()

    def _try_cast(self, value):
        raise NotImplementedError()

    def _try_cast_result(self, result):
        """ try to cast the result to our original type,
        we may have roundtripped thru object in the mean-time """
        return result

    def _try_coerce_args(self, values, other):
        """ provide coercion to our input arguments """
        return values, other

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args """
        return result

    def _try_fill(self, value):
        return value

    def to_native_types(self, slicer=None, na_rep='', **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            values = values[:, slicer]
        values = np.array(values, dtype=object)
        mask = isnull(values)
        values[mask] = na_rep
        return values.tolist()

    def replace(self, to_replace, value, inplace=False, filter=None,
                regex=False):
        """ replace the to_replace value with value, possible to create new
        blocks here this is just a call to putmask. regex is not used here.
        It is used in ObjectBlocks.  It is here for API
        compatibility."""
        mask = com.mask_missing(self.values, to_replace)
        if filter is not None:
            for i, item in enumerate(self.items):
                if item not in filter:
                    mask[i] = False

        if not mask.any():
            if inplace:
                return [self]
            return [self.copy()]
        return self.putmask(mask, value, inplace=inplace)

    def putmask(self, mask, new, inplace=False):
        """ putmask the data to the block; it is possible that we may create a new dtype of block
            return the resulting block(s) """

        new_values = self.values if inplace else self.values.copy()

        # may need to align the new
        if hasattr(new, 'reindex_axis'):
            axis = getattr(new, '_info_axis_number', 0)
            new = new.reindex_axis(self.items, axis=axis, copy=False).values.T

        # may need to align the mask
        if hasattr(mask, 'reindex_axis'):
            axis = getattr(mask, '_info_axis_number', 0)
            mask = mask.reindex_axis(
                self.items, axis=axis, copy=False).values.T

        if self._can_hold_element(new):
            new = self._try_cast(new)
            np.putmask(new_values, mask, new)

        # maybe upcast me
        elif mask.any():

            # need to go column by column
            new_blocks = []

            def create_block(v, m, n, item, reshape=True):
                """ return a new block, try to preserve dtype if possible """

                # n should the length of the mask or a scalar here
                if np.isscalar(n):
                    n = np.array([n] * len(m))

                # see if we are only masking values that if putted
                # will work in the current dtype
                nv = None
                try:
                    nn = n[m]
                    nn_at = nn.astype(self.dtype)
                    if (nn == nn_at).all():
                        nv = v.copy()
                        nv[mask] = nn_at
                except:
                    pass

                # change the dtype
                if nv is None:
                    dtype, _ = com._maybe_promote(n.dtype)
                    nv = v.astype(dtype)
                    np.putmask(nv, m, n)

                if reshape:
                    nv = _block_shape(nv)
                    return make_block(nv, [item], self.ref_items)
                else:
                    return make_block(nv, item, self.ref_items)

            if self.ndim > 1:
                for i, item in enumerate(self.items):
                    m = mask[i]
                    v = new_values[i]

                    # need a new block
                    if m.any():

                        n = new[i] if isinstance(
                            new, np.ndarray) else np.array(new)

                        # type of the new block
                        dtype, _ = com._maybe_promote(n.dtype)

                        # we need to exiplicty astype here to make a copy
                        n = n.astype(dtype)

                        block = create_block(v, m, n, item)

                    else:
                        nv = v if inplace else v.copy()
                        nv = _block_shape(nv)
                        block = make_block(
                            nv, Index([item]), self.ref_items, fastpath=True)

                    new_blocks.append(block)

            else:

                new_blocks.append(
                    create_block(new_values, mask, new, self.items, reshape=False))

            return new_blocks

        if inplace:
            return [self]

        return make_block(new_values, self.items, self.ref_items, fastpath=True)

    def interpolate(self, method='pad', axis=0, inplace=False,
                    limit=None, missing=None, coerce=False):

        # if we are coercing, then don't force the conversion
        # if the block can't hold the type
        if coerce:
            if not self._can_hold_na:
                if inplace:
                    return self
                else:
                    return self.copy()

        values = self.values if inplace else self.values.copy()
        values = com.interpolate_2d(values, method, axis, limit, missing)
        return make_block(values, self.items, self.ref_items, ndim=self.ndim, klass=self.__class__, fastpath=True)

    def take(self, indexer, ref_items, axis=1):
        if axis < 1:
            raise AssertionError('axis must be at least 1, got %d' % axis)
        new_values = com.take_nd(self.values, indexer, axis=axis,
                                 allow_fill=False)
        return make_block(new_values, self.items, ref_items, ndim=self.ndim, klass=self.__class__, fastpath=True)

    def get_values(self, dtype=None):
        return self.values

    def get_merge_length(self):
        return len(self.values)

    def diff(self, n):
        """ return block for the diff of the values """
        new_values = com.diff(self.values, n, axis=1)
        return make_block(new_values, self.items, self.ref_items, ndim=self.ndim, fastpath=True)

    def shift(self, indexer, periods):
        """ shift the block by periods, possibly upcast """

        new_values = self.values.take(indexer, axis=1)
        # convert integer to float if necessary. need to do a lot more than
        # that, handle boolean etc also
        new_values, fill_value = com._maybe_upcast(new_values)
        if periods > 0:
            new_values[:, :periods] = fill_value
        else:
            new_values[:, periods:] = fill_value
        return make_block(new_values, self.items, self.ref_items, ndim=self.ndim, fastpath=True)

    def eval(self, func, other, raise_on_error=True, try_cast=False):
        """
        evaluate the block; return result block from the result

        Parameters
        ----------
        func  : how to combine self, other
        other : a ndarray/object
        raise_on_error : if True, raise when I can't perform the function, False by default (and just return
             the data that we had coming in)

        Returns
        -------
        a new block, the result of the func
        """
        values = self.values

        # see if we can align other
        if hasattr(other, 'reindex_axis'):
            axis = getattr(other, '_info_axis_number', 0)
            other = other.reindex_axis(
                self.items, axis=axis, copy=False).values

        # make sure that we can broadcast
        is_transposed = False
        if hasattr(other, 'ndim') and hasattr(values, 'ndim'):
            if values.ndim != other.ndim or values.shape == other.shape[::-1]:
                values = values.T
                is_transposed = True

        values, other = self._try_coerce_args(values, other)
        args = [values, other]
        try:
            result = self._try_coerce_result(func(*args))
        except (Exception) as detail:
            if raise_on_error:
                raise TypeError('Could not operate [%s] with block values [%s]'
                                % (repr(other), str(detail)))
            else:
                # return the values
                result = np.empty(values.shape, dtype='O')
                result.fill(np.nan)

        if not isinstance(result, np.ndarray):
            raise TypeError('Could not compare [%s] with block values'
                            % repr(other))

        if is_transposed:
            result = result.T

        # try to cast if requested
        if try_cast:
            result = self._try_cast_result(result)

        return make_block(result, self.items, self.ref_items, ndim=self.ndim, fastpath=True)

    def where(self, other, cond, raise_on_error=True, try_cast=False):
        """
        evaluate the block; return result block(s) from the result

        Parameters
        ----------
        other : a ndarray/object
        cond  : the condition to respect
        raise_on_error : if True, raise when I can't perform the function, False by default (and just return
             the data that we had coming in)

        Returns
        -------
        a new block(s), the result of the func
        """

        values = self.values

        # see if we can align other
        if hasattr(other, 'reindex_axis'):
            axis = getattr(other, '_info_axis_number', 0)
            other = other.reindex_axis(self.items, axis=axis, copy=True).values

        # make sure that we can broadcast
        is_transposed = False
        if hasattr(other, 'ndim') and hasattr(values, 'ndim'):
            if values.ndim != other.ndim or values.shape == other.shape[::-1]:
                values = values.T
                is_transposed = True

        # see if we can align cond
        if not hasattr(cond, 'shape'):
            raise ValueError(
                "where must have a condition that is ndarray like")
        if hasattr(cond, 'reindex_axis'):
            axis = getattr(cond, '_info_axis_number', 0)
            cond = cond.reindex_axis(self.items, axis=axis, copy=True).values
        else:
            cond = cond.values

        # may need to undo transpose of values
        if hasattr(values, 'ndim'):
            if values.ndim != cond.ndim or values.shape == cond.shape[::-1]:
                values = values.T
                is_transposed = not is_transposed

        # our where function
        def func(c, v, o):
            if c.ravel().all():
                return v

            v, o = self._try_coerce_args(v, o)
            try:
                return self._try_coerce_result(expressions.where(c, v, o, raise_on_error=True))
            except (Exception) as detail:
                if raise_on_error:
                    raise TypeError('Could not operate [%s] with block values [%s]'
                                    % (repr(o), str(detail)))
                else:
                    # return the values
                    result = np.empty(v.shape, dtype='float64')
                    result.fill(np.nan)
                    return result

        # see if we can operate on the entire block, or need item-by-item
        result = func(cond, values, other)
        if self._can_hold_na:

            if not isinstance(result, np.ndarray):
                raise TypeError('Could not compare [%s] with block values'
                                % repr(other))

            if is_transposed:
                result = result.T

            # try to cast if requested
            if try_cast:
                result = self._try_cast_result(result)

            return make_block(result, self.items, self.ref_items, ndim=self.ndim)

        # might need to separate out blocks
        axis = cond.ndim - 1
        cond = cond.swapaxes(axis, 0)
        mask = np.array([cond[i].all() for i in range(cond.shape[0])],
                        dtype=bool)

        result_blocks = []
        for m in [mask, ~mask]:
            if m.any():
                items = self.items[m]
                slices = [slice(None)] * cond.ndim
                slices[axis] = self.items.get_indexer(items)
                r = self._try_cast_result(result[slices])
                result_blocks.append(make_block(r.T, items, self.ref_items))

        return result_blocks


class NumericBlock(Block):
    is_numeric = True
    _can_hold_na = True

    def _try_cast_result(self, result):
        return _possibly_downcast_to_dtype(result, self.dtype)


class FloatBlock(NumericBlock):
    _downcast_dtype = 'int64'

    def _can_hold_element(self, element):
        if isinstance(element, np.ndarray):
            return issubclass(element.dtype.type, (np.floating, np.integer))
        return isinstance(element, (float, int))

    def _try_cast(self, element):
        try:
            return float(element)
        except:  # pragma: no cover
            return element

    def to_native_types(self, slicer=None, na_rep='', float_format=None, **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            values = values[:, slicer]
        values = np.array(values, dtype=object)
        mask = isnull(values)
        values[mask] = na_rep
        if float_format:
            imask = (-mask).ravel()
            values.flat[imask] = np.array(
                [float_format % val for val in values.ravel()[imask]])
        return values.tolist()

    def should_store(self, value):
        # when inserting a column should not coerce integers to floats
        # unnecessarily
        return issubclass(value.dtype.type, np.floating) and value.dtype == self.dtype


class ComplexBlock(NumericBlock):

    def _can_hold_element(self, element):
        return isinstance(element, complex)

    def _try_cast(self, element):
        try:
            return complex(element)
        except:  # pragma: no cover
            return element

    def should_store(self, value):
        return issubclass(value.dtype.type, np.complexfloating)


class IntBlock(NumericBlock):
    _can_hold_na = False

    def _can_hold_element(self, element):
        if isinstance(element, np.ndarray):
            return issubclass(element.dtype.type, np.integer)
        return com.is_integer(element)

    def _try_cast(self, element):
        try:
            return int(element)
        except:  # pragma: no cover
            return element

    def should_store(self, value):
        return com.is_integer_dtype(value) and value.dtype == self.dtype


class BoolBlock(NumericBlock):
    is_bool = True
    _can_hold_na = False

    def _can_hold_element(self, element):
        return isinstance(element, (int, bool))

    def _try_cast(self, element):
        try:
            return bool(element)
        except:  # pragma: no cover
            return element

    def should_store(self, value):
        return issubclass(value.dtype.type, np.bool_)


class ObjectBlock(Block):
    is_object = True
    _can_hold_na = True

    def __init__(self, values, items, ref_items, ndim=2, fastpath=False, placement=None):
        if issubclass(values.dtype.type, compat.string_types):
            values = np.array(values, dtype=object)

        super(ObjectBlock, self).__init__(values, items, ref_items,
                                          ndim=ndim, fastpath=fastpath, placement=placement)

    @property
    def is_bool(self):
        """ we can be a bool if we have only bool values but are of type object """
        return lib.is_bool_array(self.values.ravel())

    def convert(self, convert_dates=True, convert_numeric=True, copy=True, by_item=True):
        """ attempt to coerce any object types to better types
            return a copy of the block (if copy = True)
            by definition we ARE an ObjectBlock!!!!!

            can return multiple blocks!
            """

        # attempt to create new type blocks
        is_unique = self.items.is_unique
        blocks = []
        if by_item:

            for i, c in enumerate(self.items):
                values = self.iget(i)

                values = com._possibly_convert_objects(
                    values, convert_dates=convert_dates, convert_numeric=convert_numeric)
                values = _block_shape(values)
                items = self.items.take([i])
                placement = None if is_unique else [i]
                newb = make_block(
                    values, items, self.ref_items, ndim=self.ndim, placement=placement)
                blocks.append(newb)

        else:

            values = com._possibly_convert_objects(
                self.values, convert_dates=convert_dates, convert_numeric=convert_numeric)
            blocks.append(
                make_block(values, self.items, self.ref_items, ndim=self.ndim))

        return blocks

    def _can_hold_element(self, element):
        return True

    def _try_cast(self, element):
        return element

    def should_store(self, value):
        return not issubclass(value.dtype.type,
                              (np.integer, np.floating, np.complexfloating,
                               np.datetime64, np.bool_))

    def replace(self, to_replace, value, inplace=False, filter=None,
                regex=False):
        blk = [self]
        to_rep_is_list = com.is_list_like(to_replace)
        value_is_list = com.is_list_like(value)
        both_lists = to_rep_is_list and value_is_list
        either_list = to_rep_is_list or value_is_list

        if not either_list and com.is_re(to_replace):
            blk[0], = blk[0]._replace_single(to_replace, value,
                                             inplace=inplace, filter=filter,
                                             regex=True)
        elif not (either_list or regex):
            blk = super(ObjectBlock, self).replace(to_replace, value,
                                                   inplace=inplace,
                                                   filter=filter, regex=regex)
        elif both_lists:
            for to_rep, v in zip(to_replace, value):
                blk[0], = blk[0]._replace_single(to_rep, v, inplace=inplace,
                                                 filter=filter, regex=regex)
        elif to_rep_is_list and regex:
            for to_rep in to_replace:
                blk[0], = blk[0]._replace_single(to_rep, value,
                                                 inplace=inplace,
                                                 filter=filter, regex=regex)
        else:
            blk[0], = blk[0]._replace_single(to_replace, value,
                                             inplace=inplace, filter=filter,
                                             regex=regex)
        return blk

    def _replace_single(self, to_replace, value, inplace=False, filter=None,
                        regex=False):
        # to_replace is regex compilable
        to_rep_re = com.is_re_compilable(to_replace)

        # regex is regex compilable
        regex_re = com.is_re_compilable(regex)

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
            result = super(ObjectBlock, self).replace(to_replace, value,
                                                      inplace=inplace,
                                                      filter=filter, regex=regex)
            if not isinstance(result, list):
                result = [result]
            return result

        new_values = self.values if inplace else self.values.copy()

        # deal with replacing values with objects (strings) that match but
        # whose replacement is not a string (numeric, nan, object)
        if isnull(value) or not isinstance(value, compat.string_types):
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

        try:
            filt = lmap(self.items.get_loc, filter)
        except TypeError:
            filt = slice(None)

        new_values[filt] = f(new_values[filt])

        return [self if inplace else make_block(new_values, self.items,
                                                self.ref_items, fastpath=True)]


class DatetimeBlock(Block):
    _can_hold_na = True

    def __init__(self, values, items, ref_items, fastpath=False, placement=None, **kwargs):
        if values.dtype != _NS_DTYPE:
            values = tslib.cast_to_nanoseconds(values)

        super(DatetimeBlock, self).__init__(values, items, ref_items,
                                            fastpath=True, placement=placement, **kwargs)

    def _gi(self, arg):
        return lib.Timestamp(self.values[arg])

    def _can_hold_element(self, element):
        return com.is_integer(element) or isinstance(element, datetime)

    def _try_cast(self, element):
        try:
            return int(element)
        except:
            return element

    def _try_coerce_args(self, values, other):
        """ provide coercion to our input arguments
            we are going to compare vs i8, so coerce to integer
            values is always ndarra like, other may not be """
        values = values.view('i8')
        if isinstance(other, datetime):
            other = lib.Timestamp(other).asm8.view('i8')
        elif isnull(other):
            other = tslib.iNaT
        else:
            other = other.view('i8')

        return values, other

    def _try_coerce_result(self, result):
        """ reverse of try_coerce_args """
        if isinstance(result, np.ndarray):
            if result.dtype == 'i8':
                result = tslib.array_to_datetime(
                    result.astype(object).ravel()).reshape(result.shape)
        elif isinstance(result, np.integer):
            result = lib.Timestamp(result)
        return result

    def _try_fill(self, value):
        """ if we are a NaT, return the actual fill value """
        if isinstance(value, type(tslib.NaT)):
            value = tslib.iNaT
        return value

    def to_native_types(self, slicer=None, na_rep=None, **kwargs):
        """ convert to our native types format, slicing if desired """

        values = self.values
        if slicer is not None:
            values = values[:, slicer]
        mask = isnull(values)

        rvalues = np.empty(values.shape, dtype=object)
        if na_rep is None:
            na_rep = 'NaT'
        rvalues[mask] = na_rep
        imask = (-mask).ravel()
        if self.dtype == 'datetime64[ns]':
            rvalues.flat[imask] = np.array(
                [Timestamp(val)._repr_base for val in values.ravel()[imask]], dtype=object)
        elif self.dtype == 'timedelta64[ns]':
            rvalues.flat[imask] = np.array([lib.repr_timedelta64(val)
                                           for val in values.ravel()[imask]], dtype=object)
        return rvalues.tolist()

    def should_store(self, value):
        return issubclass(value.dtype.type, np.datetime64)

    def astype(self, dtype, copy=False, raise_on_error=True):
        """
        handle convert to object as a special case
        """
        klass = None
        if np.dtype(dtype).type == np.object_:
            klass = ObjectBlock
        return self._astype(dtype, copy=copy, raise_on_error=raise_on_error, klass=klass)

    def set(self, item, value):
        """
        Modify Block in-place with new item value

        Returns
        -------
        None
        """
        loc = self.items.get_loc(item)

        if value.dtype != _NS_DTYPE:
            value = tslib.cast_to_nanoseconds(value)

        self.values[loc] = value

    def get_values(self, dtype=None):
        if dtype == object:
            flat_i8 = self.values.ravel().view(np.int64)
            res = tslib.ints_to_pydatetime(flat_i8)
            return res.reshape(self.values.shape)
        return self.values


class SparseBlock(Block):

    """ implement as a list of sparse arrays of the same dtype """
    __slots__ = ['items', 'ref_items', '_ref_locs', 'ndim', 'values']
    is_sparse = True
    is_numeric = True
    _can_hold_na = True
    _can_consolidate = False
    _verify_integrity = False
    _ftype = 'sparse'

    def __init__(self, values, items, ref_items, ndim=None, fastpath=False, placement=None):

        # kludgetastic
        if ndim is not None:
            if ndim == 1:
                ndim = 1
            elif ndim > 2:
                ndim = ndim
        else:
            if len(items) != 1:
                ndim = 1
            else:
                ndim = 2
        self.ndim = ndim

        self._ref_locs = None
        self.values = values
        if fastpath:
            self.items = items
            self.ref_items = ref_items
        else:
            self.items = _ensure_index(items)
            self.ref_items = _ensure_index(ref_items)

    @property
    def shape(self):
        return (len(self.items), self.sp_index.length)

    @property
    def itemsize(self):
        return self.dtype.itemsize

    @rwproperty.getproperty
    def fill_value(self):
        return self.values.fill_value

    @rwproperty.setproperty
    def fill_value(self, v):
        # we may need to upcast our fill to match our dtype
        if issubclass(self.dtype.type, np.floating):
            v = float(v)
        self.values.fill_value = v

    @rwproperty.getproperty
    def sp_values(self):
        return self.values.sp_values

    @rwproperty.setproperty
    def sp_values(self, v):
        # reset the sparse values
        self.values = SparseArray(
            v, sparse_index=self.sp_index, kind=self.kind, dtype=v.dtype, fill_value=self.fill_value, copy=False)

    @property
    def sp_index(self):
        return self.values.sp_index

    @property
    def kind(self):
        return self.values.kind

    def __len__(self):
        try:
            return self.sp_index.length
        except:
            return 0

    def should_store(self, value):
        return isinstance(value, SparseArray)

    def prepare_for_merge(self, **kwargs):
        """ create a dense block """
        return make_block(self.get_values(), self.items, self.ref_items)

    def post_merge(self, items, **kwargs):
        return self

    def set(self, item, value):
        self.values = value

    def get(self, item):
        if self.ndim == 1:
            loc = self.items.get_loc(item)
            return self.values[loc]
        else:
            return self.values

    def _slice(self, slicer):
        """ return a slice of my values (but densify first) """
        return self.get_values()[slicer]

    def get_values(self, dtype=None):
        """ need to to_dense myself (and always return a ndim sized object) """
        values = self.values.to_dense()
        if values.ndim == self.ndim - 1:
            values = values.reshape((1,) + values.shape)
        return values

    def get_merge_length(self):
        return 1

    def make_block(
        self, values, items=None, ref_items=None, sparse_index=None, kind=None, dtype=None, fill_value=None,
            copy=False, fastpath=True):
        """ return a new block """
        if dtype is None:
            dtype = self.dtype
        if fill_value is None:
            fill_value = self.fill_value
        if items is None:
            items = self.items
        if ref_items is None:
            ref_items = self.ref_items
        new_values = SparseArray(values, sparse_index=sparse_index,
                                 kind=kind or self.kind, dtype=dtype, fill_value=fill_value, copy=copy)
        return make_block(new_values, items, ref_items, ndim=self.ndim, fastpath=fastpath)

    def interpolate(self, method='pad', axis=0, inplace=False,
                    limit=None, missing=None, **kwargs):

        values = com.interpolate_2d(
            self.values.to_dense(), method, axis, limit, missing)
        return self.make_block(values, self.items, self.ref_items)

    def fillna(self, value, inplace=False, downcast=None):
        # we may need to upcast our fill to match our dtype
        if issubclass(self.dtype.type, np.floating):
            value = float(value)
        values = self.values if inplace else self.values.copy()
        return self.make_block(values.get_values(value), fill_value=value)

    def shift(self, indexer, periods):
        """ shift the block by periods """

        new_values = self.values.to_dense().take(indexer)
        # convert integer to float if necessary. need to do a lot more than
        # that, handle boolean etc also
        new_values, fill_value = com._maybe_upcast(new_values)
        if periods > 0:
            new_values[:periods] = fill_value
        else:
            new_values[periods:] = fill_value
        return self.make_block(new_values)

    def take(self, indexer, ref_items, axis=1):
        """ going to take our items
            along the long dimension"""
        if axis < 1:
            raise AssertionError('axis must be at least 1, got %d' % axis)

        return self.make_block(self.values.take(indexer))

    def reindex_axis(self, indexer, method=None, axis=1, fill_value=None, limit=None, mask_info=None):
        """
        Reindex using pre-computed indexer information
        """
        if axis < 1:
            raise AssertionError('axis must be at least 1, got %d' % axis)

        # taking on the 0th axis always here
        if fill_value is None:
            fill_value = self.fill_value
        return self.make_block(self.values.take(indexer), items=self.items, fill_value=fill_value)

    def reindex_items_from(self, new_ref_items, copy=True):
        """
        Reindex to only those items contained in the input set of items

        E.g. if you have ['a', 'b'], and the input items is ['b', 'c', 'd'],
        then the resulting items will be ['b']

        Returns
        -------
        reindexed : Block
        """

        # 2-d
        if self.ndim >= 2:
            if self.items[0] not in self.ref_items:
                return None
            return self.make_block(self.values, ref_items=new_ref_items, copy=copy)

        # 1-d
        new_ref_items, indexer = self.items.reindex(new_ref_items)
        if indexer is None:
            indexer = np.arange(len(self.items))

        return self.make_block(com.take_1d(self.values.values, indexer), items=new_ref_items, ref_items=new_ref_items, copy=copy)

    def sparse_reindex(self, new_index):
        """ sparse reindex and return a new block
            current reindex only works for float64 dtype! """
        values = self.values
        values = values.sp_index.to_int_index().reindex(
            values.sp_values.astype('float64'), values.fill_value, new_index)
        return self.make_block(values, sparse_index=new_index)

    def split_block_at(self, item):
        if len(self.items) == 1 and item == self.items[0]:
            return []
        return super(SparseBlock, self).split_block_at(self, item)


def make_block(values, items, ref_items, klass=None, ndim=None, dtype=None, fastpath=False, placement=None):

    if klass is None:
        dtype = dtype or values.dtype
        vtype = dtype.type

        if isinstance(values, SparseArray):
            klass = SparseBlock
        elif issubclass(vtype, np.floating):
            klass = FloatBlock
        elif issubclass(vtype, np.integer) and not issubclass(vtype, np.datetime64):
            klass = IntBlock
        elif dtype == np.bool_:
            klass = BoolBlock
        elif issubclass(vtype, np.datetime64):
            klass = DatetimeBlock
        elif issubclass(vtype, np.complexfloating):
            klass = ComplexBlock

        # try to infer a DatetimeBlock, or set to an ObjectBlock
        else:

            if np.prod(values.shape):
                flat = values.ravel()
                inferred_type = lib.infer_dtype(flat)
                if inferred_type == 'datetime':

                    # we have an object array that has been inferred as datetime, so
                    # convert it
                    try:
                        values = tslib.array_to_datetime(
                            flat).reshape(values.shape)
                        klass = DatetimeBlock
                    except:  # it already object, so leave it
                        pass

            if klass is None:
                klass = ObjectBlock

    return klass(values, items, ref_items, ndim=ndim, fastpath=fastpath, placement=placement)

# TODO: flexible with index=None and/or items=None


class BlockManager(PandasObject):

    """
    Core internal data structure to implement DataFrame

    Manage a bunch of labeled 2D mixed-type ndarrays. Essentially it's a
    lightweight blocked set of labeled data to be manipulated by the DataFrame
    public API class

    Parameters
    ----------


    Notes
    -----
    This is *not* a public API class
    """
    __slots__ = ['axes', 'blocks', '_ndim', '_shape', '_known_consolidated',
                 '_is_consolidated', '_has_sparse', '_ref_locs', '_items_map']

    def __init__(self, blocks, axes, do_integrity_check=True, fastpath=True):
        self.axes = [_ensure_index(ax) for ax in axes]
        self.blocks = blocks

        ndim = self.ndim
        for block in blocks:
            if not block.is_sparse and ndim != block.ndim:
                raise AssertionError(('Number of Block dimensions (%d) must '
                                      'equal number of axes (%d)')
                                     % (block.ndim, ndim))

        if do_integrity_check:
            self._verify_integrity()

        self._has_sparse = False
        self._consolidate_check()

        # we have a duplicate items index, setup the block maps
        if not self.items.is_unique:
            self._set_ref_locs(do_refs=True)

    @classmethod
    def make_empty(cls):
        return cls([], [[], []])

    def __nonzero__(self):
        return True

    # Python3 compat
    __bool__ = __nonzero__

    @property
    def shape(self):
        if getattr(self, '_shape', None) is None:
            self._shape = tuple(len(ax) for ax in self.axes)
        return self._shape

    @property
    def ndim(self):
        if getattr(self, '_ndim', None) is None:
            self._ndim = len(self.axes)
        return self._ndim

    def set_axis(self, axis, value, maybe_rename=True, check_axis=True):
        cur_axis = self.axes[axis]
        value = _ensure_index(value)

        if check_axis and len(value) != len(cur_axis):
            raise Exception('Length mismatch (%d vs %d)'
                            % (len(value), len(cur_axis)))

        self.axes[axis] = value
        self._shape = None

        if axis == 0:

            # set/reset ref_locs based on the current index
            # and map the new index if needed
            self._set_ref_locs(labels=cur_axis)

            # take via ref_locs
            for block in self.blocks:
                block.set_ref_items(self.items, maybe_rename=maybe_rename)

            # set/reset ref_locs based on the new index
            self._set_ref_locs(labels=value, do_refs=True)

    def _reset_ref_locs(self):
        """ take the current _ref_locs and reset ref_locs on the blocks
            to correctly map, ignoring Nones;
            reset both _items_map and _ref_locs """

        # let's reset the ref_locs in individual blocks
        if self.items.is_unique:
            for b in self.blocks:
                b._ref_locs = None
        else:
            for b in self.blocks:
                b.reset_ref_locs()
        self._rebuild_ref_locs()

        self._ref_locs = None
        self._items_map = None

    def _rebuild_ref_locs(self):
        """ take _ref_locs and set the individual block ref_locs, skipping Nones
            no effect on a unique index """
        if self._ref_locs is not None:
            item_count = 0
            for v in self._ref_locs:
                if v is not None:
                    block, item_loc = v
                    block._ref_locs[item_loc] = item_count
                    item_count += 1

    def _set_ref_locs(self, labels=None, do_refs=False):
        """
        if we have a non-unique index on this axis, set the indexers
        we need to set an absolute indexer for the blocks
        return the indexer if we are not unique

        labels : the (new) labels for this manager
        ref    : boolean, whether to set the labels (one a 1-1 mapping)

        """

        if labels is None:
            labels = self.items

        # we are unique, and coming from a unique
        is_unique = labels.is_unique
        if is_unique and not do_refs:

            if not self.items.is_unique:

                # reset our ref locs
                self._ref_locs = None
                for b in self.blocks:
                    b._ref_locs = None

            return None

        # we are going to a non-unique index
        # we have ref_locs on the block at this point
        if (not is_unique and do_refs) or do_refs == 'force':

            # create the items map
            im = getattr(self, '_items_map', None)
            if im is None:

                im = dict()
                for block in self.blocks:

                    # if we have a duplicate index but
                    # _ref_locs have not been set
                    try:
                        rl = block.ref_locs
                    except:
                        raise AssertionError("cannot create BlockManager._ref_locs because "
                                             "block [%s] with duplicate items [%s] "
                                             "does not have _ref_locs set" % (block, labels))

                    m = maybe_create_block_in_items_map(im, block)
                    for i, item in enumerate(block.items):
                        m[i] = rl[i]

                self._items_map = im

            # create the _ref_loc map here
            rl = [None] * len(labels)
            for block, items in im.items():
                for i, loc in enumerate(items):
                    rl[loc] = (block, i)
            self._ref_locs = rl
            return rl

        # return our cached _ref_locs (or will compute again
        # when we recreate the block manager if needed
        return getattr(self, '_ref_locs', None)

    def get_items_map(self, use_cached=True):
        """
        return an inverted ref_loc map for an item index
        block -> item (in that block) location -> column location

        use_cached : boolean, use the cached items map, or recreate
        """

        # cache check
        if use_cached:
            im = getattr(self, '_items_map', None)
            if im is not None:
                return im

        im = dict()
        rl = self._set_ref_locs()

        # we have a non-duplicative index
        if rl is None:

            axis = self.axes[0]
            for block in self.blocks:

                m = maybe_create_block_in_items_map(im, block)
                for i, item in enumerate(block.items):
                    m[i] = axis.get_loc(item)

        # use the ref_locs to construct the map
        else:

            for i, (block, idx) in enumerate(rl):

                m = maybe_create_block_in_items_map(im, block)
                m[idx] = i

        self._items_map = im
        return im

    # make items read only for now
    def _get_items(self):
        return self.axes[0]
    items = property(fget=_get_items)

    def get_dtype_counts(self):
        """ return a dict of the counts of dtypes in BlockManager """
        self._consolidate_inplace()
        counts = dict()
        for b in self.blocks:
            counts[b.dtype.name] = counts.get(b.dtype.name, 0) + b.shape[0]
        return counts

    def get_ftype_counts(self):
        """ return a dict of the counts of dtypes in BlockManager """
        self._consolidate_inplace()
        counts = dict()
        for b in self.blocks:
            counts[b.ftype] = counts.get(b.ftype, 0) + b.shape[0]
        return counts

    def __getstate__(self):
        block_values = [b.values for b in self.blocks]
        block_items = [b.items for b in self.blocks]
        axes_array = [ax for ax in self.axes]
        return axes_array, block_values, block_items

    def __setstate__(self, state):
        # discard anything after 3rd, support beta pickling format for a little
        # while longer
        ax_arrays, bvalues, bitems = state[:3]

        self.axes = [_ensure_index(ax) for ax in ax_arrays]
        self.axes = _handle_legacy_indexes(self.axes)

        blocks = []
        for values, items in zip(bvalues, bitems):
            blk = make_block(values, items, self.axes[0])
            blocks.append(blk)
        self.blocks = blocks

        self._post_setstate()

    def _post_setstate(self):
        self._is_consolidated = False
        self._known_consolidated = False
        self._set_has_sparse()

    def __len__(self):
        return len(self.items)

    def __unicode__(self):
        output = com.pprint_thing(self.__class__.__name__)
        for i, ax in enumerate(self.axes):
            if i == 0:
                output += '\nItems: %s' % ax
            else:
                output += '\nAxis %d: %s' % (i, ax)

        for block in self.blocks:
            output += '\n%s' % com.pprint_thing(block)
        return output

    def _verify_integrity(self):
        mgr_shape = self.shape
        tot_items = sum(len(x.items) for x in self.blocks)
        for block in self.blocks:
            if block.ref_items is not self.items:
                raise AssertionError("Block ref_items must be BlockManager "
                                     "items")
            if not block.is_sparse and block.values.shape[1:] != mgr_shape[1:]:
                construction_error(
                    tot_items, block.values.shape[1:], self.axes)
        if len(self.items) != tot_items:
            raise AssertionError('Number of manager items must equal union of '
                                 'block items\n# manager items: {0}, # '
                                 'tot_items: {1}'.format(len(self.items),
                                                         tot_items))

    def apply(self, f, *args, **kwargs):
        """ iterate over the blocks, collect and create a new block manager

        Parameters
        ----------
        f : the callable or function name to operate on at the block level
        axes : optional (if not supplied, use self.axes)
        filter : list, if supplied, only call the block if the filter is in the block
        """

        axes = kwargs.pop('axes', None)
        filter = kwargs.get('filter')
        do_integrity_check = kwargs.pop('do_integrity_check', False)
        result_blocks = []
        for blk in self.blocks:
            if filter is not None:
                kwargs['filter'] = set(kwargs['filter'])
                if not blk.items.isin(filter).any():
                    result_blocks.append(blk)
                    continue
            if callable(f):
                applied = f(blk, *args, **kwargs)
            else:
                applied = getattr(blk, f)(*args, **kwargs)

            if isinstance(applied, list):
                result_blocks.extend(applied)
            else:
                result_blocks.append(applied)
        bm = self.__class__(
            result_blocks, axes or self.axes, do_integrity_check=do_integrity_check)
        bm._consolidate_inplace()
        return bm

    def where(self, *args, **kwargs):
        return self.apply('where', *args, **kwargs)

    def eval(self, *args, **kwargs):
        return self.apply('eval', *args, **kwargs)

    def putmask(self, *args, **kwargs):
        return self.apply('putmask', *args, **kwargs)

    def diff(self, *args, **kwargs):
        return self.apply('diff', *args, **kwargs)

    def interpolate(self, *args, **kwargs):
        return self.apply('interpolate', *args, **kwargs)

    def shift(self, *args, **kwargs):
        return self.apply('shift', *args, **kwargs)

    def fillna(self, *args, **kwargs):
        return self.apply('fillna', *args, **kwargs)

    def downcast(self, *args, **kwargs):
        return self.apply('downcast', *args, **kwargs)

    def astype(self, *args, **kwargs):
        return self.apply('astype', *args, **kwargs)

    def convert(self, *args, **kwargs):
        return self.apply('convert', *args, **kwargs)

    def replace(self, *args, **kwargs):
        return self.apply('replace', *args, **kwargs)

    def replace_list(self, src_lst, dest_lst, inplace=False, regex=False):
        """ do a list replace """

        # figure out our mask a-priori to avoid repeated replacements
        values = self.as_matrix()

        def comp(s):
            if isnull(s):
                return isnull(values)
            return values == s
        masks = [comp(s) for i, s in enumerate(src_lst)]

        result_blocks = []
        for blk in self.blocks:

            # its possible to get multiple result blocks here
            # replace ALWAYS will return a list
            rb = [blk if inplace else blk.copy()]
            for i, (s, d) in enumerate(zip(src_lst, dest_lst)):
                new_rb = []
                for b in rb:
                    if b.dtype == np.object_:
                        result = b.replace(s, d, inplace=inplace,
                                           regex=regex)
                        if isinstance(result, list):
                            new_rb.extend(result)
                        else:
                            new_rb.append(result)
                    else:
                        # get our mask for this element, sized to this
                        # particular block
                        m = masks[i][b.ref_locs]
                        if m.any():
                            new_rb.extend(b.putmask(m, d, inplace=True))
                        else:
                            new_rb.append(b)
                rb = new_rb
            result_blocks.extend(rb)

        bm = self.__class__(result_blocks, self.axes)
        bm._consolidate_inplace()
        return bm

    def prepare_for_merge(self, *args, **kwargs):
        """ prepare for merging, return a new block manager with Sparse -> Dense """
        self._consolidate_inplace()
        if self._has_sparse:
            return self.apply('prepare_for_merge', *args, **kwargs)
        return self

    def post_merge(self, objs, **kwargs):
        """ try to sparsify items that were previously sparse """
        is_sparse = defaultdict(list)
        for o in objs:
            for blk in o._data.blocks:
                if blk.is_sparse:

                    # record the dtype of each item
                    for i in blk.items:
                        is_sparse[i].append(blk.dtype)

        if len(is_sparse):
            return self.apply('post_merge', items=is_sparse)

        return self

    def is_consolidated(self):
        """
        Return True if more than one block with the same dtype
        """
        if not self._known_consolidated:
            self._consolidate_check()
        return self._is_consolidated

    def _consolidate_check(self):
        ftypes = [blk.ftype for blk in self.blocks]
        self._is_consolidated = len(ftypes) == len(set(ftypes))
        self._known_consolidated = True
        self._set_has_sparse()

    def _set_has_sparse(self):
        self._has_sparse = any((blk.is_sparse for blk in self.blocks))

    @property
    def is_mixed_type(self):
        # Warning, consolidation needs to get checked upstairs
        self._consolidate_inplace()
        return len(self.blocks) > 1

    @property
    def is_numeric_mixed_type(self):
        # Warning, consolidation needs to get checked upstairs
        self._consolidate_inplace()
        return all([block.is_numeric for block in self.blocks])

    def get_block_map(self, copy=False, typ=None, columns=None, is_numeric=False, is_bool=False):
        """ return a dictionary mapping the ftype -> block list

            Parameters
            ----------
            typ : return a list/dict
            copy : copy if indicated
            columns : a column filter list
            filter if the type is indicated """

        # short circuit - mainly for merging
        if typ == 'dict' and columns is None and not is_numeric and not is_bool and not copy:
            bm = defaultdict(list)
            for b in self.blocks:
                bm[str(b.ftype)].append(b)
            return bm

        self._consolidate_inplace()

        if is_numeric:
            filter_blocks = lambda block: block.is_numeric
        elif is_bool:
            filter_blocks = lambda block: block.is_bool
        else:
            filter_blocks = lambda block: True

        def filter_columns(b):
            if columns:
                if not columns in b.items:
                    return None
                b = b.reindex_items_from(columns)
            return b

        maybe_copy = lambda b: b.copy() if copy else b

        def maybe_copy(b):
            if copy:
                b = b.copy()
            return b

        if typ == 'list':
            bm = []
            for b in self.blocks:
                if filter_blocks(b):
                    b = filter_columns(b)
                    if b is not None:
                        bm.append(maybe_copy(b))

        else:
            if typ == 'dtype':
                key = lambda b: b.dtype
            else:
                key = lambda b: b.ftype
            bm = defaultdict(list)
            for b in self.blocks:
                if filter_blocks(b):
                    b = filter_columns(b)
                    if b is not None:
                        bm[str(key(b))].append(maybe_copy(b))
        return bm

    def get_bool_data(self, **kwargs):
        kwargs['is_bool'] = True
        return self.get_data(**kwargs)

    def get_numeric_data(self, **kwargs):
        kwargs['is_numeric'] = True
        return self.get_data(**kwargs)

    def get_data(self, copy=False, columns=None, **kwargs):
        """
        Parameters
        ----------
        copy : boolean, default False
            Whether to copy the blocks
        """
        blocks = self.get_block_map(
            typ='list', copy=copy, columns=columns, **kwargs)
        if len(blocks) == 0:
            return self.__class__.make_empty()

        return self.combine(blocks)

    def combine(self, blocks):
        """ reutrn a new manager with the blocks """
        indexer = np.sort(np.concatenate([b.ref_locs for b in blocks]))
        new_items = self.items.take(indexer)

        new_blocks = []
        for b in blocks:
            b = b.copy(deep=False)
            b.ref_items = new_items
            new_blocks.append(b)
        new_axes = list(self.axes)
        new_axes[0] = new_items
        return self.__class__(new_blocks, new_axes, do_integrity_check=False)

    def get_slice(self, slobj, axis=0, raise_on_error=False):
        new_axes = list(self.axes)

        if raise_on_error:
            _check_slice_bounds(slobj, new_axes[axis])

        new_axes[axis] = new_axes[axis][slobj]

        if axis == 0:
            new_items = new_axes[0]
            if len(self.blocks) == 1:
                blk = self.blocks[0]
                newb = make_block(blk._slice(slobj),
                                  new_items,
                                  new_items,
                                  klass=blk.__class__,
                                  fastpath=True,
                                  placement=blk._ref_locs)
                new_blocks = [newb]
            else:
                return self.reindex_items(new_items)
        else:
            new_blocks = self._slice_blocks(slobj, axis)

        bm = self.__class__(new_blocks, new_axes, do_integrity_check=False)
        bm._consolidate_inplace()
        return bm

    def _slice_blocks(self, slobj, axis):
        new_blocks = []

        slicer = [slice(None, None) for _ in range(self.ndim)]
        slicer[axis] = slobj
        slicer = tuple(slicer)

        for block in self.blocks:
            newb = make_block(block._slice(slicer),
                              block.items,
                              block.ref_items,
                              klass=block.__class__,
                              fastpath=True,
                              placement=block._ref_locs)
            newb.set_ref_locs(block._ref_locs)
            new_blocks.append(newb)
        return new_blocks

    def get_series_dict(self):
        # For DataFrame
        return _blocks_to_series_dict(self.blocks, self.axes[1])

    def __contains__(self, item):
        return item in self.items

    @property
    def nblocks(self):
        return len(self.blocks)

    def copy(self, deep=True):
        """
        Make deep or shallow copy of BlockManager

        Parameters
        ----------
        deep : boolean, default True
            If False, return shallow copy (do not copy data)

        Returns
        -------
        copy : BlockManager
        """
        new_axes = list(self.axes)
        return self.apply('copy', axes=new_axes, deep=deep, do_integrity_check=False)

    def as_matrix(self, items=None):
        if len(self.blocks) == 0:
            mat = np.empty(self.shape, dtype=float)
        elif len(self.blocks) == 1:
            blk = self.blocks[0]
            if items is None or blk.items.equals(items):
                # if not, then just call interleave per below
                mat = blk.get_values()
            else:
                mat = self.reindex_items(items).as_matrix()
        else:
            if items is None:
                mat = self._interleave(self.items)
            else:
                mat = self.reindex_items(items).as_matrix()

        return mat

    def _interleave(self, items):
        """
        Return ndarray from blocks with specified item order
        Items must be contained in the blocks
        """
        dtype = _interleaved_dtype(self.blocks)
        items = _ensure_index(items)

        result = np.empty(self.shape, dtype=dtype)
        itemmask = np.zeros(len(items), dtype=bool)

        # By construction, all of the item should be covered by one of the
        # blocks
        if items.is_unique:

            for block in self.blocks:
                indexer = items.get_indexer(block.items)
                if (indexer == -1).any():
                    raise AssertionError('Items must contain all block items')
                result[indexer] = block.get_values(dtype)
                itemmask[indexer] = 1

        else:

            # non-unique, must use ref_locs
            rl = self._set_ref_locs()
            for i, (block, idx) in enumerate(rl):
                result[i] = block.get_values(dtype)[idx]
                itemmask[i] = 1

        if not itemmask.all():
            raise AssertionError('Some items were not contained in blocks')

        return result

    def xs(self, key, axis=1, copy=True):
        if axis < 1:
            raise AssertionError('Can only take xs across axis >= 1, got %d'
                                 % axis)

        loc = self.axes[axis].get_loc(key)
        slicer = [slice(None, None) for _ in range(self.ndim)]
        slicer[axis] = loc
        slicer = tuple(slicer)

        new_axes = list(self.axes)

        # could be an array indexer!
        if isinstance(loc, (slice, np.ndarray)):
            new_axes[axis] = new_axes[axis][loc]
        else:
            new_axes.pop(axis)

        new_blocks = []
        if len(self.blocks) > 1:
            if not copy:
                raise Exception('cannot get view of mixed-type or '
                                'non-consolidated DataFrame')
            for blk in self.blocks:
                newb = make_block(blk.values[slicer],
                                  blk.items,
                                  blk.ref_items,
                                  klass=blk.__class__,
                                  fastpath=True)
                new_blocks.append(newb)
        elif len(self.blocks) == 1:
            block = self.blocks[0]
            vals = block.values[slicer]
            if copy:
                vals = vals.copy()
            new_blocks = [make_block(vals,
                                     self.items,
                                     self.items,
                                     klass=block.__class__,
                                     fastpath=True)]

        return self.__class__(new_blocks, new_axes)

    def fast_2d_xs(self, loc, copy=False):
        """

        """
        if len(self.blocks) == 1:
            result = self.blocks[0].values[:, loc]
            if copy:
                result = result.copy()
            return result

        if not copy:
            raise Exception('cannot get view of mixed-type or '
                            'non-consolidated DataFrame')

        dtype = _interleaved_dtype(self.blocks)

        items = self.items
        n = len(items)
        result = np.empty(n, dtype=dtype)
        for blk in self.blocks:
            for j, item in enumerate(blk.items):
                i = items.get_loc(item)
                result[i] = blk._gi((j, loc))

        return result

    def consolidate(self):
        """
        Join together blocks having same dtype

        Returns
        -------
        y : BlockManager
        """
        if self.is_consolidated():
            return self

        bm = self.__class__(self.blocks, self.axes)
        bm._consolidate_inplace()
        return bm

    def _consolidate_inplace(self):
        if not self.is_consolidated():
            self.blocks = _consolidate(self.blocks, self.items)

            # reset our mappings
            if not self.items.is_unique:
                self._ref_locs = None
                self._items_map = None
                self._set_ref_locs(do_refs=True)

            self._is_consolidated = True
            self._known_consolidated = True
            self._set_has_sparse()

    def get(self, item):
        if self.items.is_unique:
            _, block = self._find_block(item)
            return block.get(item)
        else:
            indexer = self.items.get_loc(item)
            ref_locs = np.array(self._set_ref_locs())

            # duplicate index but only a single result
            if com.is_integer(indexer):

                b, loc = ref_locs[indexer]
                values = [b.iget(loc)]
                index = Index([self.items[indexer]])

            # we have a multiple result, potentially across blocks
            else:

                values = [block.iget(i) for block, i in ref_locs[indexer]]
                index = self.items[indexer]

            # create and return a new block manager
            axes = [index] + self.axes[1:]
            blocks = form_blocks(values, index, axes)
            mgr = BlockManager(blocks, axes)
            mgr._consolidate_inplace()
            return mgr

    def iget(self, i):
        item = self.items[i]
        if self.items.is_unique:
            return self.get(item)

        # compute the duplicative indexer if needed
        ref_locs = self._set_ref_locs()
        b, loc = ref_locs[i]
        return b.iget(loc)

    def get_scalar(self, tup):
        """
        Retrieve single item
        """
        item = tup[0]
        _, blk = self._find_block(item)

        # this could obviously be seriously sped up in cython
        item_loc = blk.items.get_loc(item),
        full_loc = item_loc + tuple(ax.get_loc(x)
                                    for ax, x in zip(self.axes[1:], tup[1:]))
        return blk.values[full_loc]

    def delete(self, item):

        is_unique = self.items.is_unique
        loc = self.items.get_loc(item)

        # dupe keys may return mask
        loc = _possibly_convert_to_indexer(loc)
        self._delete_from_all_blocks(loc, item)

        # _ref_locs, and _items_map are good here
        new_items = self.items.delete(loc)
        self.set_items_norename(new_items)

        self._known_consolidated = False

        if not is_unique:
            self._consolidate_inplace()

    def set(self, item, value):
        """
        Set new item in-place. Does not consolidate. Adds new Block if not
        contained in the current set of items
        """
        if not isinstance(value, SparseArray):
            if value.ndim == self.ndim - 1:
                value = value.reshape((1,) + value.shape)
            if value.shape[1:] != self.shape[1:]:
                raise AssertionError('Shape of new values must be compatible '
                                     'with manager shape')

        def _set_item(item, arr):
            i, block = self._find_block(item)
            if not block.should_store(value):
                # delete from block, create and append new block
                self._delete_from_block(i, item)
                self._add_new_block(item, arr, loc=None)
            else:
                block.set(item, arr)

        try:

            loc = self.items.get_loc(item)
            if isinstance(loc, int):
                _set_item(self.items[loc], value)
            else:
                subset = self.items[loc]
                if len(value) != len(subset):
                    raise AssertionError(
                        'Number of items to set did not match')

                # we are inserting multiple non-unique items as replacements
                # we are inserting one by one, so the index can go from unique
                # to non-unique during the loop, need to have _ref_locs defined
                # at all times
                if np.isscalar(item) and com.is_list_like(loc):

                    # first delete from all blocks
                    self.delete(item)

                    loc = _possibly_convert_to_indexer(loc)
                    for i, (l, arr) in enumerate(zip(loc, value)):

                        # insert the item
                        self.insert(
                            l, item, arr[None, :], allow_duplicates=True)

                        # reset the _ref_locs on indiviual blocks
                        # rebuild ref_locs
                        if self.items.is_unique:
                            self._reset_ref_locs()
                            self._set_ref_locs(do_refs='force')

                    self._rebuild_ref_locs()

                else:
                    for i, (item, arr) in enumerate(zip(subset, value)):
                        _set_item(item, arr[None, :])
        except KeyError:
            # insert at end
            self.insert(len(self.items), item, value)

        self._known_consolidated = False

    def insert(self, loc, item, value, allow_duplicates=False):

        if not allow_duplicates and item in self.items:
            raise Exception('cannot insert %s, already exists' % item)

        try:
            new_items = self.items.insert(loc, item)
            self.set_items_norename(new_items)

            # new block
            self._add_new_block(item, value, loc=loc)

        except:

            # so our insertion operation failed, so back out of the new items
            # GH 3010
            new_items = self.items.delete(loc)
            self.set_items_norename(new_items)

            # re-raise
            raise

        if len(self.blocks) > 100:
            self._consolidate_inplace()

        self._known_consolidated = False

        # clear the internal ref_loc mappings if necessary
        if loc != len(self.items) - 1 and new_items.is_unique:
            self.set_items_clear(new_items)

    def set_items_norename(self, value):
        self.set_axis(0, value, maybe_rename=False, check_axis=False)
        self._shape = None

    def set_items_clear(self, value):
        """ clear the ref_locs on all blocks """
        self.set_axis(0, value, maybe_rename='clear', check_axis=False)

    def _delete_from_all_blocks(self, loc, item):
        """ delete from the items loc the item
            the item could be in multiple blocks which could
            change each iteration (as we split blocks) """

        # possibily convert to an indexer
        loc = _possibly_convert_to_indexer(loc)

        if isinstance(loc, (list, tuple, np.ndarray)):
            for l in loc:
                for i, b in enumerate(self.blocks):
                    if item in b.items:
                        self._delete_from_block(i, item)

        else:
            i, _ = self._find_block(item)
            self._delete_from_block(i, item)

    def _delete_from_block(self, i, item):
        """
        Delete and maybe remove the whole block

        Remap the split blocks to there old ranges,
        so after this function, _ref_locs and _items_map (if used)
        are correct for the items, None fills holes in _ref_locs
        """
        block = self.blocks.pop(i)
        ref_locs = self._set_ref_locs()
        prev_items_map = self._items_map.pop(
            block) if ref_locs is not None else None

        # if we can't consolidate, then we are removing this block in its
        # entirey
        if block._can_consolidate:

            # compute the split mask
            loc = block.items.get_loc(item)
            if type(loc) == slice or com.is_integer(loc):
                mask = np.array([True] * len(block))
                mask[loc] = False
            else:  # already a mask, inverted
                mask = -loc

            # split the block
            counter = 0
            for s, e in com.split_ranges(mask):

                sblock = make_block(block.values[s:e],
                                    block.items[s:e].copy(),
                                    block.ref_items,
                                    klass=block.__class__,
                                    fastpath=True)

                self.blocks.append(sblock)

                # update the _ref_locs/_items_map
                if ref_locs is not None:

                    # fill the item_map out for this sub-block
                    m = maybe_create_block_in_items_map(
                        self._items_map, sblock)
                    for j, itm in enumerate(sblock.items):

                        # is this item masked (e.g. was deleted)?
                        while (True):

                            if counter > len(mask) or mask[counter]:
                                break
                            else:
                                counter += 1

                        # find my mapping location
                        m[j] = prev_items_map[counter]
                        counter += 1

                    # set the ref_locs in this block
                    sblock.set_ref_locs(m)

        # reset the ref_locs to the new structure
        if ref_locs is not None:

            # items_map is now good, with the original locations
            self._set_ref_locs(do_refs=True)

            # reset the ref_locs based on the now good block._ref_locs
            self._reset_ref_locs()

    def _add_new_block(self, item, value, loc=None):
        # Do we care about dtype at the moment?

        # hm, elaborate hack?
        if loc is None:
            loc = self.items.get_loc(item)
        new_block = make_block(value, self.items[loc:loc + 1].copy(),
                               self.items, fastpath=True)
        self.blocks.append(new_block)

        # set ref_locs based on the this new block
        # and add to the ref/items maps
        if not self.items.is_unique:

            # insert into the ref_locs at the appropriate location
            # _ref_locs is already long enough,
            # but may need to shift elements
            new_block.set_ref_locs([0])

            # need to shift elements to the right
            if self._ref_locs[loc] is not None:
                for i in reversed(lrange(loc+1,len(self._ref_locs))):
                    self._ref_locs[i] = self._ref_locs[i-1]

            self._ref_locs[loc] = (new_block, 0)

            # and reset
            self._reset_ref_locs()
            self._set_ref_locs(do_refs=True)

    def _find_block(self, item):
        self._check_have(item)
        for i, block in enumerate(self.blocks):
            if item in block:
                return i, block

    def _check_have(self, item):
        if item not in self.items:
            raise KeyError('no item named %s' % com.pprint_thing(item))

    def reindex_axis(self, new_axis, method=None, axis=0, fill_value=None, limit=None, copy=True):
        new_axis = _ensure_index(new_axis)
        cur_axis = self.axes[axis]

        if new_axis.equals(cur_axis):
            if copy:
                result = self.copy(deep=True)
                result.axes[axis] = new_axis
                result._shape = None

                if axis == 0:
                    # patch ref_items, #1823
                    for blk in result.blocks:
                        blk.ref_items = new_axis

                return result
            else:
                return self

        if axis == 0:
            if method is not None:
                raise AssertionError('method argument not supported for '
                                     'axis == 0')
            return self.reindex_items(new_axis, copy=copy, fill_value=fill_value)

        new_axis, indexer = cur_axis.reindex(
            new_axis, method, copy_if_needed=True)
        return self.reindex_indexer(new_axis, indexer, axis=axis, fill_value=fill_value)

    def reindex_indexer(self, new_axis, indexer, axis=1, fill_value=None):
        """
        pandas-indexer with -1's only.
        """
        if axis == 0:
            return self._reindex_indexer_items(new_axis, indexer, fill_value)

        new_blocks = []
        for block in self.blocks:
            newb = block.reindex_axis(
                indexer, axis=axis, fill_value=fill_value)
            new_blocks.append(newb)

        new_axes = list(self.axes)
        new_axes[axis] = new_axis
        return self.__class__(new_blocks, new_axes)

    def _reindex_indexer_items(self, new_items, indexer, fill_value):
        # TODO: less efficient than I'd like

        item_order = com.take_1d(self.items.values, indexer)

        # keep track of what items aren't found anywhere
        mask = np.zeros(len(item_order), dtype=bool)
        new_axes = [new_items] + self.axes[1:]

        new_blocks = []
        for blk in self.blocks:
            blk_indexer = blk.items.get_indexer(item_order)
            selector = blk_indexer != -1

            # update with observed items
            mask |= selector

            if not selector.any():
                continue

            new_block_items = new_items.take(selector.nonzero()[0])
            new_values = com.take_nd(blk.values, blk_indexer[selector], axis=0,
                                     allow_fill=False)
            new_blocks.append(make_block(new_values, new_block_items,
                                         new_items, fastpath=True))

        if not mask.all():
            na_items = new_items[-mask]
            na_block = self._make_na_block(na_items, new_items,
                                           fill_value=fill_value)
            new_blocks.append(na_block)
            new_blocks = _consolidate(new_blocks, new_items)

        return self.__class__(new_blocks, new_axes)

    def reindex_items(self, new_items, copy=True, fill_value=None):
        """

        """
        new_items = _ensure_index(new_items)
        data = self
        if not data.is_consolidated():
            data = data.consolidate()
            return data.reindex_items(new_items, copy=copy, fill_value=fill_value)

        # TODO: this part could be faster (!)
        new_items, indexer = self.items.reindex(new_items, copy_if_needed=True)
        new_axes = [new_items] + self.axes[1:]

        # could have so me pathological (MultiIndex) issues here
        new_blocks = []
        if indexer is None:
            for blk in self.blocks:
                if copy:
                    new_blocks.append(blk.reindex_items_from(new_items))
                else:
                    blk.ref_items = new_items
                    new_blocks.append(blk)
        else:
            for block in self.blocks:
                newb = block.reindex_items_from(new_items, copy=copy)
                if len(newb.items) > 0:
                    new_blocks.append(newb)

            # add a na block if we are missing items
            mask = indexer == -1
            if mask.any():
                extra_items = new_items[mask]
                na_block = self._make_na_block(extra_items, new_items,
                                               fill_value=fill_value)
                new_blocks.append(na_block)
                new_blocks = _consolidate(new_blocks, new_items)

        return self.__class__(new_blocks, new_axes)

    def _make_na_block(self, items, ref_items, fill_value=None):
        # TODO: infer dtypes other than float64 from fill_value

        if fill_value is None:
            fill_value = np.nan
        block_shape = list(self.shape)
        block_shape[0] = len(items)

        dtype, fill_value = com._infer_dtype_from_scalar(fill_value)
        block_values = np.empty(block_shape, dtype=dtype)
        block_values.fill(fill_value)
        na_block = make_block(block_values, items, ref_items)
        return na_block

    def take(self, indexer, new_index=None, axis=1, verify=True):
        if axis < 1:
            raise AssertionError('axis must be at least 1, got %d' % axis)

        if isinstance(indexer, list):
            indexer = np.array(indexer)

        indexer = com._ensure_platform_int(indexer)
        n = len(self.axes[axis])

        if verify:
            indexer = _maybe_convert_indices(indexer, n)

        if ((indexer == -1) | (indexer >= n)).any():
            raise Exception('Indices must be nonzero and less than '
                            'the axis length')

        new_axes = list(self.axes)
        if new_index is None:
            new_index = self.axes[axis].take(indexer)

        new_axes[axis] = new_index
        return self.apply('take', axes=new_axes, indexer=indexer, ref_items=new_axes[0], axis=axis)

    def merge(self, other, lsuffix=None, rsuffix=None):
        if not self._is_indexed_like(other):
            raise AssertionError('Must have same axes to merge managers')

        this, other = self._maybe_rename_join(other, lsuffix, rsuffix)

        cons_items = this.items + other.items
        new_axes = list(this.axes)
        new_axes[0] = cons_items

        consolidated = _consolidate(this.blocks + other.blocks, cons_items)
        return self.__class__(consolidated, new_axes)

    def _maybe_rename_join(self, other, lsuffix, rsuffix, copydata=True):
        to_rename = self.items.intersection(other.items)
        if len(to_rename) > 0:
            if not lsuffix and not rsuffix:
                raise Exception('columns overlap: %s' % to_rename)

            def lrenamer(x):
                if x in to_rename:
                    return '%s%s' % (x, lsuffix)
                return x

            def rrenamer(x):
                if x in to_rename:
                    return '%s%s' % (x, rsuffix)
                return x

            this = self.rename_items(lrenamer, copydata=copydata)
            other = other.rename_items(rrenamer, copydata=copydata)
        else:
            this = self

        return this, other

    def _is_indexed_like(self, other):
        """
        Check all axes except items
        """
        if self.ndim != other.ndim:
            raise AssertionError(('Number of dimensions must agree '
                                  'got %d and %d') % (self.ndim, other.ndim))
        for ax, oax in zip(self.axes[1:], other.axes[1:]):
            if not ax.equals(oax):
                return False
        return True

    def rename_axis(self, mapper, axis=1):

        index = self.axes[axis]
        if isinstance(index, MultiIndex):
            new_axis = MultiIndex.from_tuples(
                [tuple(mapper(y) for y in x) for x in index], names=index.names)
        else:
            new_axis = Index([mapper(x) for x in index], name=index.name)

        if not new_axis.is_unique:
            raise AssertionError('New axis must be unique to rename')

        new_axes = list(self.axes)
        new_axes[axis] = new_axis
        return self.__class__(self.blocks, new_axes)

    def rename_items(self, mapper, copydata=True):
        if isinstance(self.items, MultiIndex):
            items = [tuple(mapper(y) for y in x) for x in self.items]
            new_items = MultiIndex.from_tuples(items, names=self.items.names)
        else:
            items = [mapper(x) for x in self.items]
            new_items = Index(items, name=self.items.name)

        new_blocks = []
        for block in self.blocks:
            newb = block.copy(deep=copydata)
            newb.set_ref_items(new_items, maybe_rename=True)
            new_blocks.append(newb)
        new_axes = list(self.axes)
        new_axes[0] = new_items
        return self.__class__(new_blocks, new_axes)

    def add_prefix(self, prefix):
        f = (('%s' % prefix) + '%s').__mod__
        return self.rename_items(f)

    def add_suffix(self, suffix):
        f = ('%s' + ('%s' % suffix)).__mod__
        return self.rename_items(f)

    @property
    def block_id_vector(self):
        # TODO
        result = np.empty(len(self.items), dtype=int)
        result.fill(-1)

        for i, blk in enumerate(self.blocks):
            indexer = self.items.get_indexer(blk.items)
            if (indexer == -1).any():
                raise AssertionError('Block items must be in manager items')
            result.put(indexer, i)

        if (result < 0).any():
            raise AssertionError('Some items were not in any block')
        return result

    @property
    def item_dtypes(self):
        result = np.empty(len(self.items), dtype='O')
        mask = np.zeros(len(self.items), dtype=bool)
        for i, blk in enumerate(self.blocks):
            indexer = self.items.get_indexer(blk.items)
            result.put(indexer, blk.dtype.name)
            mask.put(indexer, 1)
        if not (mask.all()):
            raise AssertionError('Some items were not in any block')
        return result


class SingleBlockManager(BlockManager):

    """ manage a single block with """
    ndim = 1
    _is_consolidated = True
    _known_consolidated = True
    __slots__ = ['axes', 'blocks', '_block',
                 '_values', '_shape', '_has_sparse']

    def __init__(self, block, axis, do_integrity_check=False, fastpath=True):

        if isinstance(axis, list):
            if len(axis) != 1:
                raise ValueError(
                    "cannot create SingleBlockManager with more than 1 axis")
            axis = axis[0]

        # passed from constructor, single block, single axis
        if fastpath:
            self.axes = [axis]
            if isinstance(block, list):
                if len(block) != 1:
                    raise ValueError(
                        "cannot create SingleBlockManager with more than 1 block")
                block = block[0]
            if not isinstance(block, Block):
                block = make_block(block, axis, axis, ndim=1, fastpath=True)

        else:

            self.axes = [_ensure_index(axis)]

            # create the block here
            if isinstance(block, list):

                # provide consolidation to the interleaved_dtype
                if len(block) > 1:
                    dtype = _interleaved_dtype(block)
                    block = [b.astype(dtype) for b in block]
                    block = _consolidate(block, axis)

                if len(block) != 1:
                    raise ValueError(
                        "cannot create SingleBlockManager with more than 1 block")
                block = block[0]

            if not isinstance(block, Block):
                block = make_block(block, axis, axis, ndim=1, fastpath=True)

        self.blocks = [block]
        self._block = self.blocks[0]
        self._values = self._block.values
        self._has_sparse = self._block.is_sparse

    def _post_setstate(self):
        self._block = self.blocks[0]
        self._values = self._block.values

    @property
    def shape(self):
        if getattr(self, '_shape', None) is None:
            self._shape = tuple([len(self.axes[0])])
        return self._shape

    def reindex(self, new_axis, method=None, limit=None, copy=True):

        # if we are the same and don't copy, just return
        if not copy and self.index.equals(new_axis):
            return self
        block = self._block.reindex_items_from(new_axis, copy=copy)

        if method is not None or limit is not None:
            block = block.interpolate(method=method, limit=limit)
        mgr = SingleBlockManager(block, new_axis)
        mgr._consolidate_inplace()
        return mgr

    def get_slice(self, slobj, raise_on_error=False):
        if raise_on_error:
            _check_slice_bounds(slobj, self.index)
        return self.__class__(self._block._slice(slobj), self.index._getitem_slice(slobj), fastpath=True)

    def set_axis(self, axis, value):
        cur_axis = self.axes[axis]
        value = _ensure_index(value)

        if len(value) != len(cur_axis):
            raise Exception('Length mismatch (%d vs %d)'
                            % (len(value), len(cur_axis)))
        self.axes[axis] = value
        self._shape = None
        self._block.set_ref_items(self.items, maybe_rename=True)

    def set_ref_items(self, ref_items, maybe_rename=True):
        """ we can optimize and our ref_locs are always equal to ref_items """
        if maybe_rename:
            self.items = ref_items
        self.ref_items = ref_items

    @property
    def index(self):
        return self.axes[0]

    def convert(self, *args, **kwargs):
        """ convert the whole block as one """
        kwargs['by_item'] = False
        return self.apply('convert', *args, **kwargs)

    @property
    def dtype(self):
        return self._block.dtype

    @property
    def ftype(self):
        return self._block.ftype

    @property
    def values(self):
        return self._values.view()

    @property
    def itemsize(self):
        return self._block.itemsize

    @property
    def _can_hold_na(self):
        return self._block._can_hold_na

    def is_consolidated(self):
        return True

    def _consolidate_check(self):
        pass

    def _consolidate_inplace(self):
        pass


def construction_error(tot_items, block_shape, axes):
    """ raise a helpful message about our construction """
    raise ValueError("Shape of passed values is %s, indices imply %s" % (
        tuple(map(int, [tot_items] + list(block_shape))),
        tuple(map(int, [len(ax) for ax in axes]))))


def create_block_manager_from_blocks(blocks, axes):
    try:

        # if we are passed values, make the blocks
        if len(blocks) == 1 and not isinstance(blocks[0], Block):
            placement = None if axes[0].is_unique else np.arange(len(axes[0]))
            blocks = [
                make_block(blocks[0], axes[0], axes[0], placement=placement)]

        mgr = BlockManager(blocks, axes)
        mgr._consolidate_inplace()
        return mgr

    except (ValueError):
        blocks = [getattr(b, 'values', b) for b in blocks]
        tot_items = sum(b.shape[0] for b in blocks)
        construction_error(tot_items, blocks[0].shape[1:], axes)


def create_block_manager_from_arrays(arrays, names, axes):
    try:
        blocks = form_blocks(arrays, names, axes)
        mgr = BlockManager(blocks, axes)
        mgr._consolidate_inplace()
        return mgr
    except (ValueError):
        construction_error(len(arrays), arrays[0].shape[1:], axes)


def maybe_create_block_in_items_map(im, block):
    """ create/return the block in an items_map """
    try:
        return im[block]
    except:
        im[block] = l = [None] * len(block.items)
    return l


def form_blocks(arrays, names, axes):

    # pre-filter out items if we passed it
    items = axes[0]

    if len(arrays) < len(items):
        nn = set(names)
        extra_items = Index([i for i in items if i not in nn])
    else:
        extra_items = []

    # put "leftover" items in float bucket, where else?
    # generalize?
    float_items = []
    complex_items = []
    int_items = []
    bool_items = []
    object_items = []
    sparse_items = []
    datetime_items = []

    for i, (k, v) in enumerate(zip(names, arrays)):
        if isinstance(v, SparseArray) or is_sparse_series(v):
            sparse_items.append((i, k, v))
        elif issubclass(v.dtype.type, np.floating):
            float_items.append((i, k, v))
        elif issubclass(v.dtype.type, np.complexfloating):
            complex_items.append((i, k, v))
        elif issubclass(v.dtype.type, np.datetime64):
            if v.dtype != _NS_DTYPE:
                v = tslib.cast_to_nanoseconds(v)

            if hasattr(v, 'tz') and v.tz is not None:
                object_items.append((i, k, v))
            else:
                datetime_items.append((i, k, v))
        elif issubclass(v.dtype.type, np.integer):
            if v.dtype == np.uint64:
                # HACK #2355 definite overflow
                if (v > 2 ** 63 - 1).any():
                    object_items.append((i, k, v))
                    continue
            int_items.append((i, k, v))
        elif v.dtype == np.bool_:
            bool_items.append((i, k, v))
        else:
            object_items.append((i, k, v))

    is_unique = items.is_unique
    blocks = []
    if len(float_items):
        float_blocks = _multi_blockify(float_items, items, is_unique=is_unique)
        blocks.extend(float_blocks)

    if len(complex_items):
        complex_blocks = _simple_blockify(
            complex_items, items, np.complex128, is_unique=is_unique)
        blocks.extend(complex_blocks)

    if len(int_items):
        int_blocks = _multi_blockify(int_items, items, is_unique=is_unique)
        blocks.extend(int_blocks)

    if len(datetime_items):
        datetime_blocks = _simple_blockify(
            datetime_items, items, _NS_DTYPE, is_unique=is_unique)
        blocks.extend(datetime_blocks)

    if len(bool_items):
        bool_blocks = _simple_blockify(
            bool_items, items, np.bool_, is_unique=is_unique)
        blocks.extend(bool_blocks)

    if len(object_items) > 0:
        object_blocks = _simple_blockify(
            object_items, items, np.object_, is_unique=is_unique)
        blocks.extend(object_blocks)

    if len(sparse_items) > 0:
        sparse_blocks = _sparse_blockify(sparse_items, items)
        blocks.extend(sparse_blocks)

    if len(extra_items):
        shape = (len(extra_items),) + tuple(len(x) for x in axes[1:])

        # empty items -> dtype object
        block_values = np.empty(shape, dtype=object)
        block_values.fill(np.nan)

        placement = None if is_unique else np.arange(len(extra_items))
        na_block = make_block(
            block_values, extra_items, items, placement=placement)
        blocks.append(na_block)

    return blocks


def _simple_blockify(tuples, ref_items, dtype, is_unique=True):
    """ return a single array of a block that has a single dtype; if dtype is not None, coerce to this dtype """
    block_items, values, placement = _stack_arrays(tuples, ref_items, dtype)

    # CHECK DTYPE?
    if dtype is not None and values.dtype != dtype:  # pragma: no cover
        values = values.astype(dtype)

    if is_unique:
        placement = None
    block = make_block(values, block_items, ref_items, placement=placement)
    return [block]


def _multi_blockify(tuples, ref_items, dtype=None, is_unique=True):
    """ return an array of blocks that potentially have different dtypes """

    # group by dtype
    grouper = itertools.groupby(tuples, lambda x: x[2].dtype)

    new_blocks = []
    for dtype, tup_block in grouper:

        block_items, values, placement = _stack_arrays(
            list(tup_block), ref_items, dtype)
        if is_unique:
            placement = None
        block = make_block(values, block_items, ref_items, placement=placement)
        new_blocks.append(block)

    return new_blocks


def _sparse_blockify(tuples, ref_items, dtype=None):
    """ return an array of blocks that potentially have different dtypes (and are sparse) """

    new_blocks = []
    for i, names, array in tuples:

        if not isinstance(names, (list, tuple)):
            names = [names]
        items = ref_items[ref_items.isin(names)]

        array = _maybe_to_sparse(array)
        block = make_block(
            array, items, ref_items, klass=SparseBlock, fastpath=True)
        new_blocks.append(block)

    return new_blocks


def _stack_arrays(tuples, ref_items, dtype):

    # fml
    def _asarray_compat(x):
        if is_series(x):
            return x.values
        else:
            return np.asarray(x)

    def _shape_compat(x):
        if is_series(x):
            return len(x),
        else:
            return x.shape

    placement, names, arrays = zip(*tuples)

    first = arrays[0]
    shape = (len(arrays),) + _shape_compat(first)

    stacked = np.empty(shape, dtype=dtype)
    for i, arr in enumerate(arrays):
        stacked[i] = _asarray_compat(arr)

    # index may box values
    if ref_items.is_unique:
        items = ref_items[ref_items.isin(names)]
    else:
        items = _ensure_index([n for n in names if n in ref_items])
        if len(items) != len(stacked):
            raise Exception("invalid names passed _stack_arrays")

    return items, stacked, placement


def _blocks_to_series_dict(blocks, index=None):
    from pandas.core.series import Series

    series_dict = {}

    for block in blocks:
        for item, vec in zip(block.items, block.values):
            series_dict[item] = Series(vec, index=index, name=item)
    return series_dict


def _interleaved_dtype(blocks):
    if not len(blocks):
        return None

    counts = defaultdict(lambda: [])
    for x in blocks:
        counts[type(x)].append(x)

    def _lcd_dtype(l):
        """ find the lowest dtype that can accomodate the given types """
        m = l[0].dtype
        for x in l[1:]:
            if x.dtype.itemsize > m.itemsize:
                m = x.dtype
        return m

    have_int = len(counts[IntBlock]) > 0
    have_bool = len(counts[BoolBlock]) > 0
    have_object = len(counts[ObjectBlock]) > 0
    have_float = len(counts[FloatBlock]) > 0
    have_complex = len(counts[ComplexBlock]) > 0
    have_dt64 = len(counts[DatetimeBlock]) > 0
    have_sparse = len(counts[SparseBlock]) > 0
    have_numeric = have_float or have_complex or have_int

    if (have_object or
        (have_bool and have_numeric) or
            (have_numeric and have_dt64)):
        return np.dtype(object)
    elif have_bool:
        return np.dtype(bool)
    elif have_int and not have_float and not have_complex:

        # if we are mixing unsigned and signed, then return
        # the next biggest int type (if we can)
        lcd = _lcd_dtype(counts[IntBlock])
        kinds = set([i.dtype.kind for i in counts[IntBlock]])
        if len(kinds) == 1:
            return lcd

        if lcd == 'uint64' or lcd == 'int64':
            return np.dtype('int64')

        # return 1 bigger on the itemsize if unsinged
        if lcd.kind == 'u':
            return np.dtype('int%s' % (lcd.itemsize * 8 * 2))
        return lcd

    elif have_dt64 and not have_float and not have_complex:
        return np.dtype('M8[ns]')
    elif have_complex:
        return np.dtype('c16')
    else:
        return _lcd_dtype(counts[FloatBlock] + counts[SparseBlock])


def _consolidate(blocks, items):
    """
    Merge blocks having same dtype, exclude non-consolidating blocks
    """

    # sort by _can_consolidate, dtype
    gkey = lambda x: x._consolidate_key
    grouper = itertools.groupby(sorted(blocks, key=gkey), gkey)

    new_blocks = []
    for (_can_consolidate, dtype), group_blocks in grouper:
        merged_blocks = _merge_blocks(
            list(group_blocks), items, dtype=dtype, _can_consolidate=_can_consolidate)
        if isinstance(merged_blocks, list):
            new_blocks.extend(merged_blocks)
        else:
            new_blocks.append(merged_blocks)

    return new_blocks


def _merge_blocks(blocks, items, dtype=None, _can_consolidate=True):
    if len(blocks) == 1:
        return blocks[0]

    if _can_consolidate:

        if dtype is None:
            if len(set([b.dtype for b in blocks])) != 1:
                raise AssertionError("_merge_blocks are invalid!")
            dtype = blocks[0].dtype

        new_values = _vstack([b.values for b in blocks], dtype)
        new_items = blocks[0].items.append([b.items for b in blocks[1:]])
        new_block = make_block(new_values, new_items, items)

        # unique, can reindex
        if items.is_unique:
            return new_block.reindex_items_from(items)

        # merge the ref_locs
        new_ref_locs = [b._ref_locs for b in blocks]
        if all([x is not None for x in new_ref_locs]):
            new_block.set_ref_locs(np.concatenate(new_ref_locs))
        return new_block

    # no merge
    return blocks


def _block_shape(values, ndim=1, shape=None):
    """ guarantee the shape of the values to be at least 1 d """
    if values.ndim == ndim:
        if shape is None:
            shape = values.shape
        values = values.reshape(tuple((1,) + shape))
    return values


def _vstack(to_stack, dtype):

    # work around NumPy 1.6 bug
    if dtype == _NS_DTYPE or dtype == _TD_DTYPE:
        new_values = np.vstack([x.view('i8') for x in to_stack])
        return new_values.view(dtype)

    else:
        return np.vstack(to_stack)


def _possibly_convert_to_indexer(loc):
    if com._is_bool_indexer(loc):
        loc = [i for i, v in enumerate(loc) if v]
    elif isinstance(loc,slice):
        loc = lrange(loc.start,loc.stop)
    return loc
