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

import sys
import copy

class _Base:
    def __init__(self, dict_ = {}):
        self.dict = copy.copy(dict_)

    def __iter__(self):
        item_list = self.dict.items()
        # Sort by key
        item_list.sort(lambda (k1, v1), (k2, v2): cmp(k1, k2))
        return iter(item_list)

    def __getitem__(self, key):
        if key in self.dict:
            return 0
        return self.dict[key]

    def __str__(self):
        s = ""
        for k, v in self:
            s += "%d, %f\n" % (k, v)
        return s

    def __open(self, file_name, mode):
        if file_name:
            file = open(file_name, mode)
        else:
            file = sys.stdout
        return file

    def __close(self, file):
        if file != sys.stdout:
            file.close()

    def dump(self, file_name = None):
        file = self.__open(file_name, "w")
        print >> file, self.dict
        self.__close(file)

    def load(self, file_name = None):
        file = self.__open(file_name, "r")
        self.dict = eval(file.read())
        self.__close(file)


class Hist(_Base):
    def __init__(self, dict_ = {}):
        _Base.__init__(self, dict_)

    def __add__(self, other):
        hist = Hist()
        for rdist in set(self.dict.keys() + other.dict.keys()):
            count = 0
            if rdist in self.dict:
                count += self.dict[rdist]
            if rdist in other.dict:
                count += other.dict[rdist]
            hist.dict[rdist] = count
        return hist


class Pdf(_Base):
    def __init__(self, dict_):
        _Base.__init__(self)
        count = sum(dict_.values())
        for b, c in dict_.items():
            self.dict[b] = float(c) / count


class Cdf(_Base):
    def __init__(self, dict_):
        _Base.__init__(self)
        cdf = 0.0
        for b, c in Pdf(dict_):
            self.dict[b] = cdf
            cdf += c


class Cdf_r(_Base):
    def __init__(self, hist):
        _Base.__init__(self)
        for b, c in Cdf(hist):
            self.dict[b] =  1.0 - c
