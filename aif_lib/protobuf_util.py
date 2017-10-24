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
#  Authors: Sam Van den Steen, Ghent University
#           Moncef Mechri, Uppsala University
#  Copyright: 2016, Ghent University

import zlib

from google.protobuf.internal import encoder
from google.protobuf.internal import decoder

def readRawVarint32(stream):
    raw_varint32 = []
    while 1:
        b = stream.read(1)
        # eof
        if b == "":
            break
        raw_varint32.append(b)

        if not (ord(b) & 0x80):
            # we found a byte starting with a 0, which means it's the last byte of this varint
            break

    return raw_varint32

def readDelimitedFrom(MessageType, stream):
    raw_varint32 = readRawVarint32(stream)
    message = None

    if raw_varint32:
        size, _ = decoder._DecodeVarint32(raw_varint32, 0)

        data = stream.read(size)
        if len(data) < size:
            raise Exception("Unexpected end of file")

        message = MessageType()
        message.ParseFromString(data)

    return message

def readDelimitedFrom_inplace(message, stream):
    raw_varint32 = readRawVarint32(stream)

    if raw_varint32:
        size, _ = decoder._DecodeVarint32(raw_varint32, 0)

        data = stream.read(size)
        if len(data) < size:
            raise Exception("Unexpected end of file")

        message.ParseFromString(data)

        return message
    else:
        return None

def decodeRawVarint32(dec_buff):
    raw_varint32 = []
    for c in dec_buff:
        # eof
        if c == "":
            break
        raw_varint32.append(c)

        if not (ord(c) & 0x80):
            # we found a byte starting with a 0, which means it's the last byte of this varint
            break

    return raw_varint32

def readDelimitedFrom_gzip(MessageType, dec_buff, gzip_stream, decompress_obj):
    if len(dec_buff) < 4:
        gzip_buffer = gzip_stream.read(1024)
        dec_buff += decompress_obj.decompress(gzip_buffer)

    raw_varint32 = decodeRawVarint32(dec_buff)
    message = None

    if raw_varint32:
        size, _ = decoder._DecodeVarint32(raw_varint32, 0)

        while len(dec_buff) < size + len(raw_varint32):
            gzip_buffer = gzip_stream.read(1024)
            dec_buff += decompress_obj.decompress(gzip_buffer)

        message = MessageType()
        message.ParseFromString(dec_buff[len(raw_varint32) : size + len(raw_varint32)])

        return message, dec_buff[len(raw_varint32) + size : ]
    else:
        return None, None

def readDelimitedFrom_inplace_gzip(message, dec_buff, gzip_stream, decompress_obj):
    # int max 4 bytes
    if len(dec_buff) < 4:
        gzip_buffer = gzip_stream.read(1024)
        dec_buff += decompress_obj.decompress(gzip_buffer)

    raw_varint32 = decodeRawVarint32(dec_buff)

    if raw_varint32:
        size, _ = decoder._DecodeVarint32(raw_varint32, 0)

        while len(dec_buff) < size + len(raw_varint32):
            gzip_buffer = gzip_stream.read(1024)
            dec_buff += decompress_obj.decompress(gzip_buffer)

        message.ParseFromString(dec_buff[len(raw_varint32) : size + len(raw_varint32)])

        return message, dec_buff[len(raw_varint32) + size : ]
    else:
        return None, None

def writeDelimitedTo(message, stream):
    message_str = message.SerializeToString()
    delimiter = encoder._VarintBytes(len(message_str))

    stream.write(delimiter + message_str)
