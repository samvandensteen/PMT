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
#  Authors: Sam Van den Steen, Ghent University
#  Copyright: 2016, Ghent University

import itertools, zlib, pdb
import branch_file_pb2, memory_file_pb2, mlp_file_pb2, cold_file_pb2, utrace_file_pb2
import protobuf_util

class Stream_Reader(object):
    def __init__(self, file_list, file_type, compression):
        self.file_list = file_list
        self.file_type = file_type
        self.compression = compression
        self.file = open(self.file_list[0], 'rb')
        if self.compression:
            self.dec_buff = ""
            self.decompress_obj = zlib.decompressobj(zlib.MAX_WBITS | 16)
        self.next_file = 1

    def open_next_file(self):
        self.file.close()
        self.file = open(self.file_list[self.next_file], 'rb')
        if self.compression:
            self.dec_buff = ""
            self.decompress_obj = zlib.decompressobj(zlib.MAX_WBITS | 16)
        self.next_file += 1

    def read_message(self):
        if self.file_type == "UTRACE":
            message = utrace_file_pb2.ID_string()
            if self.compression:
                msg, self.dec_buff = protobuf_util.readDelimitedFrom_inplace_gzip(message, self.dec_buff, self.file, self.decompress_obj)
            else:
                msg = protobuf_util.readDelimitedFrom_inplace(message, self.file)
            return msg
        else:
            print "Not supported!"
            sys.exit(1)

    def iter_in_place(self):
        if self.file_type == "BRANCH":
            message = branch_file_pb2.Entropy_Window()
        elif self.file_type == "STATSTACK":
            message = memory_file_pb2.Sample()
        elif self.file_type == "MLP":
            message = mlp_file_pb2.MLP_Trace()
        elif self.file_type == "COLD":
            message = cold_file_pb2.Cold_Window()
        elif self.file_type == "UTRACE":
            message = utrace_file_pb2.uTrace()
        while 1:
            if self.compression:
                msg, self.dec_buff = protobuf_util.readDelimitedFrom_inplace_gzip(message, self.dec_buff, self.file, self.decompress_obj)
            else:
                msg = protobuf_util.readDelimitedFrom_inplace(message, self.file)
            if msg is None:
                if self.next_file < len(self.file_list):
                    self.open_next_file()
                    continue
                else:
                    break

            yield msg

    def iter(self):
        if self.file_type == "BRANCH":
            message = branch_file_pb2.Entropy_Window
        elif self.file_type == "STATSTACK":
            message = memory_file_pb2.Sample
        elif self.file_type == "MLP":
            message = mlp_file_pb2.MLP_Trace
        elif self.file_type == "COLD":
            message = cold_file_pb2.Cold_Window()
        elif self.file_type == "UTRACE":
            message = utrace_file_pb2.uTrace
        while 1:
            if self.compression:
                msg, self.dec_buff = protobuf_util.readDelimitedFrom_gzip(message, self.dec_buff, self.file, self.decompress_obj)
            else:
                msg = protobuf_util.readDelimitedFrom(message, self.file)
            if msg is None:
                if self.next_file < len(self.file_list):
                    self.open_next_file()
                    continue
                else:
                    break

            yield msg
