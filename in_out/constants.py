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

import os, pdb

class Constants:
	def __init__(self):
		self.input_dir = os.getcwd()
		self.output_dir = os.getcwd()
		self.benchmarks = []
		self.processor_config = "config/nehalem.cfg"

		self.mlp_model = "stride"

		self.statstack = "new"

		self.parallel = 1

		self.overwrite_config_parameters = {}

		self.queue_model = "MLP"
		self.prefetch = False
		# heuristic
		self.alpha = 0.3

		self.cpi_stack = False

		self.top_level_dir = ""
