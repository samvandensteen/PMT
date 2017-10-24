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

import os, sys, pdb
import constants

class Debug_Printer:
    def __init__(self, output_root, benchmark, file_name):
        self.benchmark = benchmark
        self.abs_path = os.path.join(output_root, benchmark, file_name)
        if not os.path.exists(self.abs_path):
            os.makedirs(self.abs_path)

    def save_log_stats(self, message):
    	f = open(os.path.join(self.abs_path, "log.out"), "a+")
    	f.write(message + "\n")
    	f.close()

    def save_error_stats(self, message):
    	f = open(os.path.join(self.abs_path, "errors.out"), "a+")
    	f.write(message + "\n")
    	f.close()

    def save_debug_stats_live(self, stats):
    	f = open(os.path.join(self.abs_path, "debug_window.out"), "a+")
    	for s in stats:
    		f.write(str(s) + "\t")
    	f.write("\n")
    	f.close()

    def save_debug_stats(self, merged_stat_labels, merged_stats, debug_string):
    	f = open(os.path.join(self.abs_path, "debug_window.out"), "w+")
    	for label in merged_stat_labels:
    		f.write(label + "\t")
    	f.write("\n")
    	for stats in merged_stats:
    		for s in stats:
    			f.write(str(s) + "\t")
    		f.write("\n")
    	f.close()

        self.process_merged_stats(merged_stats, debug_string)

        f = open(os.path.join(self.abs_path, "debug_all.out"), "w+")
        f.write("Benchmark\t")
    	for label in merged_stat_labels:
    		f.write(label + "\t")
    	f.write("\n")
        f.write(self.benchmark + "\t")
        for overall in self.overall_stats:
            f.write(str(overall) + "\t")
        f.write("\n")
        f.close()

        f.close()

    def process_merged_stats(self, merged_stats, debug_string):
        self.overall_stats = []
        debug_all = debug_string.split("-")
        for da in debug_all:
            if da == "S" or da == "A":
                self.overall_stats.append(0)
            elif da == "WA":
                self.overall_stats.append([0,0])
        for window in merged_stats:
            prev_stat = 0
            for i,(stat,da) in enumerate(zip(window, debug_all)):
                if da == "S":
                    self.overall_stats[i] += stat
                elif da == "A":
                    self.overall_stats[i] += stat
                elif da == "WA":
                    self.overall_stats[i][0] += stat * prev_stat
                    self.overall_stats[i][1] += prev_stat
                prev_stat = stat
        for i,da in enumerate(debug_all):
            if da == "A":
                self.overall_stats[i] = float(self.overall_stats[i]) / len(self.overall_stats[i])
            elif da == "WA":
                if self.overall_stats[i][1] != 0:
                    self.overall_stats[i] = float(self.overall_stats[i][0]) / self.overall_stats[i][1]
                else:
                    self.overall_stats[i] = 0
