from collections import defaultdict

import numpy


class Grouper(object):
    """
    The `Grouper` class provides a callable which sums together groups of
    matrix rows. We generally use it for aggregating practice level data into
    organisations that consist of groups of practices like CCGs or STPs.
    """

    # Maps group IDs (which are usually strings but can be any hashable type)
    # to their row offset within the grouped matrix
    offsets = None
    # Maps row offsets in the grouped matrix to the group ID of that row
    ids = None

    def __init__(self, group_assignments):
        """
        `group_assignments` is an iterable of (row_offset, group_id) pairs
        assigning rows to groups

        It's acceptable for a row to appear in multiple groups or not to appear
        in any group at all
        """
        groups = defaultdict(list)
        for row_offset, group_id in group_assignments:
            groups[group_id].append(row_offset)
        # Maps group offset to ID
        self.ids = list(groups.keys())
        # Maps group ID to offset
        self.offsets = {
            group_id: group_offset
            for (group_offset, group_id) in enumerate(self.ids)
        }
        self._group_selectors = [
            numpy.array(groups[group_id])
            for group_id in self.ids
        ]

    def __call__(self, matrix):
        """
        Sum rows of matrix column-wise, according to their group

        Returns a matrix of shape:

            (number_of_groups X columns_in_original_matrix)
        """
        rows = len(self._group_selectors)
        columns = matrix.shape[1]
        grouped = numpy.empty((rows, columns), dtype=matrix.dtype)
        for group_offset, rows_selector in enumerate(self._group_selectors):
            row_group = matrix[rows_selector]
            grouped[group_offset] = numpy.sum(row_group, axis=0)
        return grouped
