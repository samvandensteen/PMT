#!/usr/bin/python

#  This file is part of the program: Processor Modeling Tool (PMT).
#
#  PMT is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  PMT is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with PMT.  If not, see <http://www.gnu.org/licenses/>.
#
#  Authors: Moncef Mechri, Uppsala University
#			Andreas Sandberg, Uppsala University
#  Copyright: 2016, Moncef Mechri and Andreas Sandberg

from math   import fabs
from bisect import bisect_right

class Interp:
    def __init__(self, points):
        self.points = points
        self.points.sort(lambda (x1, y1), (x2, y2): cmp(x1, x2))
        self.points_x = map(lambda x: x[0], self.points)
        self.points_y = map(lambda x: x[1], self.points)

    def _right(self, x, x0, y0, x1, y1):
        return 0.0

    def _left(self, x, x0, y0, x1, y1):
        return 0.0

    def _interp(self, x, x0, y0, x1, y1):
        return 0.0

    def _area_elem(self, x0, y0, x1, y1):
        return 0.0

    def f(self, x):
        min_x = self.points_x[0]
        max_x = self.points_x[-1]
        if x < min_x:
            x0 = self.points_x[0]
            y0 = self.points_y[0]
            x1 = self.points_x[1]
            y1 = self.points_y[1]
            return self._right(x, x0, y0, x1, y1)
        if x >= max_x:
            x0 = self.points_x[-2]
            y0 = self.points_y[-2]
            x1 = self.points_x[-1]
            y1 = self.points_y[-1]
            return self._left(x, x0, y0, x1, y1)

        i = bisect_right(self.points_x, x)
        x0 = self.points_x[i - 1]
        y0 = self.points_y[i - 1]
        x1 = self.points_x[i]
        y1 = self.points_y[i]
        assert(x0 <= x and x < x1)
        return self._interp(x, x0, y0, x1, y1)

    def __getitem__(self, x):
        return self.f(x)

    def __iter__(self):
        return iter(self.points)

    def scale_x(self, fx):
        self.points_x = map(lambda x: x * fx, self.points_x)
        self.points = map(lambda (x, y): (x * fx, y), self.points)

    def area(self):
        area = 0.0
        for i in range(len(self.points) - 1):
            x0 = self.points_x[i]
            y0 = self.points_y[i]
            x1 = self.points_x[i + 1]
            y1 = self.points_y[i + 1]
            area += fabs(self._area_elem(x0, y0, x1, y1))
        return area



class LinearInterp(Interp):
    def __init__(self, points):
        Interp.__init__(self, points)

    def _right(self, x, x0, y0, x1, y1):
        return self._interp(x, x0, y0, x1, y1)

    def _left(self, x, x0, y0, x1, y1):
        return self._interp(x, x0, y0, x1, y1)

    def _interp(self, x, x0, y0, x1, y1):
        k = (y1 - y0) / (x1 - x0)
        return k * (x - x0) + y0

    def _area_elem(self, x0, y0, x1, y1):
        area  = y0 * (x1 - x0)
        area += float((y1 - y0) * (x1 - x0)) / 2
        return area


class StepInterp(Interp):
    def __init__(self, points, reverse = True):
        Interp.__init__(self, points)
        self.reverse = reverse

    def _interp(self, x, x0, y0, x1, y1):
        return (y0, y1)[self.reverse]

    # That shouldn't be implemented
    def _area_elem(self, x0, y0, x1, y1):
        assert(0)
        return self._interp(float(x0 + x1) / 2, x0, y0, x1, y1) * (x1 - x0)

    def _right(self, x, x0, y0, x1, y1):
        return (0, y0)[self.reverse]

    def _left(self, x, x0, y0, x1, y1):
        return (y1, 0)[self.reverse]

    def f(self, x):
        if len(self.points) == 1:
            min_x = self.points_x[0]
            max_x = self.points_x[-1]
            if x < min_x:
                x0 = self.points_x[0]
                y0 = self.points_y[0]
                return self._right(x, x0, y0, 0, 0)
            if x >= max_x:
                x1 = self.points_x[-1]
                y1 = self.points_y[-1]
                return self._left(x, 0, 0, x1, y1)

        return Interp.f(self, x)
##
## Test cases
##
if __name__ == "__main__":
    import sys

    class Test(uart.test.TestCase):
        def do_test_interp(self, i, ref):
            for x, y in ref:
                self.fail_if(y != i[x])

        def do_test_area(self, i, ref):
            self.fail_if(i.area() != ref)

        def test1(self):
            data = [(0,1), (1,2)]
            ref  = [(-1, 0), (-0.5, 0.5), (0,1), (0.5, 1.5), (1, 2), (2, 3)]
            i = LinearInterp(data)
            self.do_test_interp(i, ref)
            self.do_test_area(i, 1.5)

        def test2(self):
            data = [(0,2), (1,1)]
            ref = [(-1, 3), (-0.5, 2.5), (0, 2), (0.5, 1.5), (1, 1), (2, 0)]
            i = LinearInterp(data)
            self.do_test_interp(i, ref)
            self.do_test_area(i, 1.5)

        def test3(self):
            data = [(-1, 0), (1, 0)]
            ref = [(-10, 0), (-1,0), (1,0), (10, 0)]
            i = LinearInterp(data)
            self.do_test_interp(i, ref)
            self.do_test_area(i, 0.0)

        def test4(self):
            data = [(1,1), (4, 3), (8,1), (10, 2), (11, 0.5)]
            ref = [(-1, 0), (0,0), (1, 1), (2, 1), (5, 3), (6,3), (9, 1), (20, 0.5)]
            i = StepInterp(data, False)
            self.do_test_interp(i, ref)
            #self.do_test_area(i, 4.0)

            ref = [(-1, 1), (0,1), (1, 3), (2, 3), (5, 1), (6,1), (9, 2), (20, 0)]
            i = StepInterp(data, True)
            self.do_test_interp(i, ref)
            #self.do_test_area(i, 12.0)

        def test5(self):
            data = [(3,4)]
            ref = [(-1, 0), (0, 0), (1, 0), (3, 4), (5, 4), (6,4), (9, 4), (20, 4)]
            i = StepInterp(data, False)
            self.do_test_interp(i, ref)

            ref = [(-1, 4), (0, 4), (1, 4), (3, 0), (5, 0), (6,0), (9, 0), (20, 0)]
            i = StepInterp(data, True)
            self.do_test_interp(i, ref)

    sys.exit(Test().run())
