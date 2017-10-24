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

import protobuf_util
import sd_hist_file_pb2
import itertools, zlib, pdb

class SD_Hist_Reader(object):
    def __init__(self, filename, PC = False, compression = False):
        self.file = open(filename, 'rb')
        self.PC = PC
        self.compression = compression
        if self.compression:
            self.dec_buff = ""
            self.decompress_obj = zlib.decompressobj(zlib.MAX_WBITS | 16)

    def iter_in_place(self):
        if not self.PC:
            message = sd_hist_file_pb2.sd_hist()
        else:
            message = sd_hist_file_pb2.sd_PC_hist()
        while 1:
            if self.compression:
                msg, self.dec_buff = protobuf_util.readDelimitedFrom_inplace_gzip(message, self.dec_buff, self.file, self.decompress_obj)
            else:
                msg = protobuf_util.readDelimitedFrom_inplace(message, self.file)
            if msg is None:
                break

            yield msg

    def __iter__(self):
        while 1:
            if self.compression:
                if not self.PC:
                    msg, self.dec_buff = protobuf_util.readDelimitedFrom_gzip(sd_hist_file_pb2.sd_hist, self.dec_buff, self.file, self.decompress_obj)
                else:
                    msg, self.dec_buff = protobuf_util.readDelimitedFrom_gzip(sd_hist_file_pb2.sd_PC_hist, self.dec_buff, self.file, self.decompress_obj)
            else:
                if not self.PC:
                    msg = protobuf_util.readDelimitedFrom(sd_hist_file_pb2.sd_hist, self.file)
                else:
                    msg = protobuf_util.readDelimitedFrom(sd_hist_file_pb2.sd_PC_hist, self.file)
            if msg is None:
                break

            yield msg

class SD_Hist_Writer(object):
    def __init__(self, filename):
        self.filename = filename

    def dict_to_proto(self, sd_dict):
        all_bursts = {}
        for burst, sd_count in sd_dict.iteritems():
            burst_hist = sd_hist_file_pb2.sd_hist()
            burst_hist.id = burst
            burst_hist.sd.extend(sd_count.keys())
            burst_hist.count.extend(sd_count.values())
            all_bursts[burst] = burst_hist

        return sorted(all_bursts.items())

    def PC_dict_to_proto(self, PC_sd_dict):
        all_bursts = {}
        for burst, PC_dict in PC_sd_dict.iteritems():
            burst_hist = sd_hist_file_pb2.sd_PC_hist()
            burst_hist.burst_id = burst
            for PC, sd_dict in PC_dict.iteritems():
                PC_hist = burst_hist.sd_hists.add()
                PC_hist.id = PC
                PC_hist.sd.extend(sd_dict.keys())
                PC_hist.count.extend(sd_dict.values())

            all_bursts[burst] = burst_hist

        return sorted(all_bursts.items())

    def write_sd_hist(self, message):
        self.file = open(self.filename, 'ab')
        protobuf_util.writeDelimitedTo(message, self.file)
        self.file.close()
