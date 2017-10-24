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

import os, sys, math, pdb
from in_out import Debug_Printer

class Branch_Model:
    def __init__(self, constants, config, benchmark):
        self.config = config
        self.dispatch_width = self.config.get_dispatch_width()
        self.ROB_size = self.config.get_ROB_size()
        self.front_end_refill_time = self.config.get_frontend_size()

        self.top_level_dir = constants.top_level_dir
        self.output_dir = constants.output_dir
        self.debug_printer = Debug_Printer(self.output_dir, benchmark, "debug_branch")

        self.branch_file = self.config.get_branch_predictor_name() + "_" + self.config.get_IP_bits() + "_" + self.config.get_BHR_size() + ".cfg"
    	self.read_branch_model()

    def read_branch_model(self):
    	model = [0, 0]

    	f = open(os.path.join(self.top_level_dir, "config/branch_models", self.branch_file))
    	model_lines = f.readlines()
    	f.close()

    	self.model = [float(model_lines[0].split("\t")[0]), float(model_lines[0].split("\t")[1])]

    def estimate_branch_misses(self, entropy):
    	# entropy[0] is entropy for a specific IP-bits configuration and bhr-size; entropy[1] is number of branches in a trace
    	self.branch_misses = (self.model[0] + self.model[1] * entropy[0]) / 100 * entropy[1]

    def estimate_branch_resolution_time(self, micro_op_count, instruction_latency, interpolated_dependences, independent_instructions, sample_rate):
    	if self.branch_misses != 0:
    		N_i = micro_op_count / (float(self.branch_misses) / sample_rate)
    		W_i = self.dispatch_width

    		while N_i > 0:
    			if N_i < self.dispatch_width and W_i + N_i <= self.ROB_size:
    				W_i = W_i + N_i
    				N_i = 0
    			elif N_i < self.dispatch_width and W_i + N_i > self.ROB_size:
    				N_i = N_i - (self.ROB_size - W_i)
    				W_i = W_i + (self.ROB_size - W_i)
    			elif N_i >= self.dispatch_width and W_i + self.dispatch_width <= self.ROB_size:
    				N_i = N_i - self.dispatch_width
    				W_i = W_i + self.dispatch_width
    			else:
    				N_i = N_i - (self.ROB_size - W_i)
    				W_i = W_i + (self.ROB_size - W_i)

    			leave = min(independent_instructions[int(W_i)], self.dispatch_width)
    			W_i = W_i - leave

    		W_i = math.ceil(W_i)
    		self.branch_resolution_time = instruction_latency * interpolated_dependences[int(W_i)][1]
    	else:
    		self.branch_resolution_time = 0

    def calculate_branch_component(self):
        return self.branch_misses * (self.branch_resolution_time + self.front_end_refill_time)
