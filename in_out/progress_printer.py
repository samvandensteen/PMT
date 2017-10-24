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
#  Copyright: 2016, Ghent University

import sys

class Progress_Printer:
    def __init__(self, sum_items, log_file = ""):
        self.log_file = open(log_file, "w+")
        self.progressbar_width = 100
        self.sum_items = sum_items
        self.last_progressed = 0

    def setup_progressbar(self, message = ""):
        if self.log_file != "":
            if message:
                self.log_file.write(message + "\n")
            self.log_file.write("[%s]" % (" " * self.progressbar_width))
            self.log_file.flush()
            self.log_file.write("\b" * (self.progressbar_width + 1)) # return to start of line, after '['
        else:
            if message:
                sys.stdout.write(message + "\n")
            sys.stdout.write("[%s]" % (" " * self.progressbar_width))
            sys.stdout.flush()
            sys.stdout.write("\b" * (self.progressbar_width + 1)) # return to start of line, after '['

    def print_progress(self, current_progress):
    	if current_progress * self.progressbar_width / self.sum_items > self.last_progressed:
            if self.log_file != "":
        		self.log_file.write('#' * int(current_progress * self.progressbar_width / self.sum_items - self.last_progressed))
        		self.log_file.flush()
            else:
        		sys.stdout.write('#' * int(current_progress * self.progressbar_width / self.sum_items - self.last_progressed))
        		sys.stdout.flush()
            self.last_progressed = current_progress * self.progressbar_width / self.sum_items

    	if current_progress == self.sum_items - 1:
            if self.log_file != "":
        		self.log_file.write('#' * int(self.progressbar_width - self.last_progressed))
        		self.log_file.write("]\n")
        		self.log_file.flush()
            else:
        		sys.stdout.write('#' * int(self.progressbar_width - self.last_progressed))
        		sys.stdout.write("]\n")
        		sys.stdout.flush()

    def print_message(self, message):
        if self.log_file != "":
            self.log_file.write(message + "\n")
            self.log_file.flush()
        else:
            sys.stdout.write(message + "\n")
            sys.stdout.flush()

    def close_log_file(self):
        if self.log_file != "" and not self.log_file.closed:
            self.log_file.close()
