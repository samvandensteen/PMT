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

import os
import matplotlib.pyplot as plt
import numpy as np

class Results_Printer:
    def __init__(self, input_dir, output_dir, benchmark):
        self.input_dir = os.path.abspath(input_dir)
        self.output_dir = os.path.abspath(output_dir)
        self.benchmark = benchmark

    def save_to_log(self, message):
        if not os.path.exists(os.path.join(self.output_dir, self.benchmark)):
            os.mkdir(os.path.join(self.output_dir, self.benchmark))

        f = open(os.path.join(self.output_dir, self.benchmark, "log.out"), "a+")
        f.write(message + "\n")
        f.close()

    def save_results(self, labels, values):
        if not os.path.exists(os.path.join(self.output_dir, self.benchmark)):
            os.mkdir(os.path.join(self.output_dir, self.benchmark))

        f_results = open(os.path.join(self.output_dir, self.benchmark, "result.out"), "w+")
        f_results.write("Benchmark\t")
        for l in labels:
            f_results.write(l + "\t")
        f_results.write("\n")
        f_results.write(self.benchmark + "\t")
        for v in values:
            f_results.write(str(v) + "\t")
        f_results.write("\n")
        f_results.close()

    def save_window_stats(self, labels, values):
        if not os.path.exists(os.path.join(self.output_dir, self.benchmark)):
            os.mkdir(os.path.join(self.output_dir, self.benchmark))

        f = open(os.path.join(self.output_dir, self.benchmark, "windowed.out"), "w+")
        for label in labels:
            f.write(label + "\t")
        f.write("\n")
        for stats in values:
            for s in stats:
                f.write(str(s) + "\t")
            f.write("\n")
        f.close()

    def plot_cpi_stack(self, keys, values):
		# 10 distinct colors
		colors = [[166,206,227],[31,120,180],[178,223,138],[51,160,44],[251,154,153],[227,26,28],[253,191,111],[255,127,0],[202,178,214],[106,61,154],[255,255,153],[177,89,40]]
		# scale colors
		for c in range(0, len(colors)):
			r,g,b = colors[c]
			colors[c] = [float(r) / 255, float(g) / 255, float(b) / 255]

		# figure 1
		fig, ax = plt.subplots()
		fig.set_size_inches(10,10)
		width = 1

		# plot them
		plots = []
		i, bottom_sum = 0, 0
		for v in values:
			plots.append(plt.bar(1, v, width, color=colors[i], bottom=bottom_sum))
			bottom_sum += v
			i += 1

		# put a legend on the right side, outside the figure
		ax.legend(plots, keys, bbox_to_anchor=(1.05, 1), loc=2, fancybox=True)

		# make x-axis larger so the plots looks better
		plt.xlim([0, 3])
		plt.ylim([0, bottom_sum * 1.1])

		# make ticks and labels of x axis invisible
		plt.tick_params(axis='x',          # changes apply to the x-axis
    					which='both',      # both major and minor ticks are affected
    					bottom='off',      # ticks along the bottom edge are off
    					top='off',         # ticks along the top edge are off
    					labelbottom='off') # labels along the bottom edge are off

		# set labels
		ax.set_xlabel(self.benchmark)
		ax.set_ylabel('CPI')

		# save figure
		plt.savefig(os.path.join(self.output_dir, self.benchmark, "cpi_stack.png") , bbox_inches='tight')
		plt.close(fig)
