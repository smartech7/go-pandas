# -*- coding: utf-8 -*-

import numpy as np
import pandas.lib as lib
import pandas.util.testing as tm


class TestMisc(tm.TestCase):

    def test_max_len_string_array(self):

        arr = a = np.array(['foo', 'b', np.nan], dtype='object')
        self.assertTrue(lib.max_len_string_array(arr), 3)

        # unicode
        arr = a.astype('U').astype(object)
        self.assertTrue(lib.max_len_string_array(arr), 3)

        # bytes for python3
        arr = a.astype('S').astype(object)
        self.assertTrue(lib.max_len_string_array(arr), 3)

        # raises
        tm.assertRaises(TypeError,
                        lambda: lib.max_len_string_array(arr.astype('U')))


class TestIndexing(tm.TestCase):

    def test_maybe_indices_to_slice_left_edge(self):
        target = np.arange(100)

        # slice
        indices = np.array([], dtype=np.int64)
        maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
        self.assertTrue(isinstance(maybe_slice, slice))
        self.assert_numpy_array_equal(target[indices], target[maybe_slice])

        for end in [1, 2, 5, 20, 99]:
            for step in [1, 2, 4]:
                indices = np.arange(0, end, step, dtype=np.int64)
                maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
                self.assertTrue(isinstance(maybe_slice, slice))
                self.assert_numpy_array_equal(target[indices],
                                              target[maybe_slice])

                # reverse
                indices = indices[::-1]
                maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
                self.assertTrue(isinstance(maybe_slice, slice))
                self.assert_numpy_array_equal(target[indices],
                                              target[maybe_slice])

        # not slice
        for case in [[2, 1, 2, 0], [2, 2, 1, 0], [0, 1, 2, 1], [-2, 0, 2],
                     [2, 0, -2]]:
            indices = np.array(case, dtype=np.int64)
            maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
            self.assertFalse(isinstance(maybe_slice, slice))
            self.assert_numpy_array_equal(maybe_slice, indices)
            self.assert_numpy_array_equal(target[indices], target[maybe_slice])

    def test_maybe_indices_to_slice_right_edge(self):
        target = np.arange(100)

        # slice
        for start in [0, 2, 5, 20, 97, 98]:
            for step in [1, 2, 4]:
                indices = np.arange(start, 99, step, dtype=np.int64)
                maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
                self.assertTrue(isinstance(maybe_slice, slice))
                self.assert_numpy_array_equal(target[indices],
                                              target[maybe_slice])

                # reverse
                indices = indices[::-1]
                maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
                self.assertTrue(isinstance(maybe_slice, slice))
                self.assert_numpy_array_equal(target[indices],
                                              target[maybe_slice])

        # not slice
        indices = np.array([97, 98, 99, 100], dtype=np.int64)
        maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
        self.assertFalse(isinstance(maybe_slice, slice))
        self.assert_numpy_array_equal(maybe_slice, indices)
        with self.assertRaises(IndexError):
            target[indices]
        with self.assertRaises(IndexError):
            target[maybe_slice]

        indices = np.array([100, 99, 98, 97], dtype=np.int64)
        maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
        self.assertFalse(isinstance(maybe_slice, slice))
        self.assert_numpy_array_equal(maybe_slice, indices)
        with self.assertRaises(IndexError):
            target[indices]
        with self.assertRaises(IndexError):
            target[maybe_slice]

        for case in [[99, 97, 99, 96], [99, 99, 98, 97], [98, 98, 97, 96]]:
            indices = np.array(case, dtype=np.int64)
            maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
            self.assertFalse(isinstance(maybe_slice, slice))
            self.assert_numpy_array_equal(maybe_slice, indices)
            self.assert_numpy_array_equal(target[indices], target[maybe_slice])

    def test_maybe_indices_to_slice_both_edges(self):
        target = np.arange(10)

        # slice
        for step in [1, 2, 4, 5, 8, 9]:
            indices = np.arange(0, 9, step, dtype=np.int64)
            maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
            self.assertTrue(isinstance(maybe_slice, slice))
            self.assert_numpy_array_equal(target[indices], target[maybe_slice])

            # reverse
            indices = indices[::-1]
            maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
            self.assertTrue(isinstance(maybe_slice, slice))
            self.assert_numpy_array_equal(target[indices], target[maybe_slice])

        # not slice
        for case in [[4, 2, 0, -2], [2, 2, 1, 0], [0, 1, 2, 1]]:
            indices = np.array(case, dtype=np.int64)
            maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
            self.assertFalse(isinstance(maybe_slice, slice))
            self.assert_numpy_array_equal(maybe_slice, indices)
            self.assert_numpy_array_equal(target[indices], target[maybe_slice])

    def test_maybe_indices_to_slice_middle(self):
        target = np.arange(100)

        # slice
        for start, end in [(2, 10), (5, 25), (65, 97)]:
            for step in [1, 2, 4, 20]:
                indices = np.arange(start, end, step, dtype=np.int64)
                maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
                self.assertTrue(isinstance(maybe_slice, slice))
                self.assert_numpy_array_equal(target[indices],
                                              target[maybe_slice])

                # reverse
                indices = indices[::-1]
                maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
                self.assertTrue(isinstance(maybe_slice, slice))
                self.assert_numpy_array_equal(target[indices],
                                              target[maybe_slice])

        # not slice
        for case in [[14, 12, 10, 12], [12, 12, 11, 10], [10, 11, 12, 11]]:
            indices = np.array(case, dtype=np.int64)
            maybe_slice = lib.maybe_indices_to_slice(indices, len(target))
            self.assertFalse(isinstance(maybe_slice, slice))
            self.assert_numpy_array_equal(maybe_slice, indices)
            self.assert_numpy_array_equal(target[indices], target[maybe_slice])

    def test_maybe_booleans_to_slice(self):
        arr = np.array([0, 0, 1, 1, 1, 0, 1], dtype=np.uint8)
        result = lib.maybe_booleans_to_slice(arr)
        self.assertTrue(result.dtype == np.bool_)

        result = lib.maybe_booleans_to_slice(arr[:0])
        self.assertTrue(result == slice(0, 0))

    def test_get_reverse_indexer(self):
        indexer = np.array([-1, -1, 1, 2, 0, -1, 3, 4], dtype=np.int64)
        result = lib.get_reverse_indexer(indexer, 5)
        expected = np.array([4, 2, 3, 6, 7], dtype=np.int64)
        self.assertTrue(np.array_equal(result, expected))


def test_duplicated_with_nas():
    keys = np.array([0, 1, np.nan, 0, 2, np.nan], dtype=object)

    result = lib.duplicated(keys)
    expected = [False, False, False, True, False, True]
    assert (np.array_equal(result, expected))

    result = lib.duplicated(keys, keep='first')
    expected = [False, False, False, True, False, True]
    assert (np.array_equal(result, expected))

    result = lib.duplicated(keys, keep='last')
    expected = [True, False, True, False, False, False]
    assert (np.array_equal(result, expected))

    result = lib.duplicated(keys, keep=False)
    expected = [True, False, True, True, False, True]
    assert (np.array_equal(result, expected))

    keys = np.empty(8, dtype=object)
    for i, t in enumerate(zip([0, 0, np.nan, np.nan] * 2,
                              [0, np.nan, 0, np.nan] * 2)):
        keys[i] = t

    result = lib.duplicated(keys)
    falses = [False] * 4
    trues = [True] * 4
    expected = falses + trues
    assert (np.array_equal(result, expected))

    result = lib.duplicated(keys, keep='last')
    expected = trues + falses
    assert (np.array_equal(result, expected))

    result = lib.duplicated(keys, keep=False)
    expected = trues + trues
    assert (np.array_equal(result, expected))

if __name__ == '__main__':
    import nose

    nose.runmodule(argv=[__file__, '-vvs', '-x', '--pdb', '--pdb-failure'],
                   exit=False)
