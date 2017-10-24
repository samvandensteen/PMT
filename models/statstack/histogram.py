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

import math

import uart.interp

from uart.hist import Hist as _Hist
from uart.hist import Pdf
from uart.hist import Cdf  as _Cdf
from uart.hist import Cdf_r

class Hist(_Hist):
    def __init__(self, dict_):
        _Hist.__init__(self, dict_)

    def __len__(self):
        return len(self.dict)

    def empty(self):
        return len(self.dict) == 0

    def values(self):
        return self.dict.values()

    def count_entries(self, ignore=[]):
        count = 0
        for v, c in self:
            if v in ignore:
                continue
            count += c
        return count

    def mean(self, ignore=[]):
        if (self.count_entries(ignore) == 0):
            return 0
        mean = 0.0
        for v, c in self:
            if v in ignore:
                continue
            mean += v * c
        return mean / self.count_entries(ignore)

    def variance(self, ignore=[]):
        if (self.count_entries(ignore) == 0):
            return 0
        mean = self.mean()
        variance = 0.0
        for v, c in self:
            if v in ignore:
                continue
            variance += v * (c - mean) * (c - mean)
        return variance / self.count_entries(ignore)

    def stdev(self, ignore=[]):
        return math.sqrt(self.variance(ignore))

    def stats(self, ignore=[], round_amount=4):
        return str(self.count_entries(ignore)) + " items, mean " + \
               str(round(self.mean(ignore), round_amount)) + ", stdev " + \
               str(round(self.stdev(ignore), round_amount)) + \
               " (ignore list=" + str(ignore) +")"


class Cdf(_Cdf):
    def __init__(self, dict_):
        _Cdf.__init__(self, dict_)

    def __sub__(self, other):
        x_values = list(set(self.dict.keys() + other.dict.keys()))

        s_interp = uart.interp.StepInterp(self.dict.items())
        o_interp = uart.interp.StepInterp(other.dict.items())

        dict_ = {}
        for x in x_values:
            dict_[x] = s_interp[x] - o_interp[x]

        ret = Cdf({})
        ret.dict = dict_
        return ret

    def area(self):
        return uart.interp.StepInterp(self.dict.items(), False).area()
