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

class Cache_Model:
    def __init__(self, constants, config, benchmark):
        self.config = config
        self.ROB_size = self.config.get_ROB_size()
    	self.LLC_hit_delay = self.config.get_LLC_access_cost()
        self.cache_config = self.config.get_cache_config()

        self.output_dir = constants.output_dir
        self.debug_printer = Debug_Printer(self.output_dir, benchmark, "debug_base")

    def set_window_stats(self, L1D_load_hits, L1D_store_hits, load_misses, store_misses, instruction_misses):
        self.L1D_load_hits = L1D_load_hits
        self.L1D_store_hits = L1D_store_hits
        self.load_misses = load_misses
        self.store_misses = store_misses
        self.instruction_misses = instruction_misses

        self.compile_cache_data()
        self.calculate_load_latency()

    def compile_cache_data(self):
        self.cache_data = {}
        sorted_cache_levels = sorted(zip(self.cache_config.keys(), [v["size"] for v in self.cache_config.values()]), key = lambda x: x[1])
        for cache, size in sorted_cache_levels:
            self.cache_data[cache] = {}
            if self.cache_config[cache]["level"] == 1 and self.cache_config[cache]["content"] == "data":
                self.cache_data[cache]['data_loads'] = self.L1D_load_hits + self.load_misses[size]
                self.cache_data[cache]['data_load_misses'] = self.load_misses[size]
                self.cache_data[cache]['data_stores'] = self.L1D_store_hits + self.store_misses[size]
                self.cache_data[cache]['data_store_misses'] = self.store_misses[size]
            elif self.cache_config[cache]["content"] == "data":
                self.cache_data[cache]['data_loads'] = self.load_misses[previous_cache_level_size]
                self.cache_data[cache]['data_load_misses'] = self.load_misses[size]
                self.cache_data[cache]['data_stores'] = self.store_misses[previous_cache_level_size]
                self.cache_data[cache]['data_store_misses'] = self.store_misses[size]
            elif self.cache_config[cache]["content"] == "instructions":
                self.cache_data[cache]['instr_load_misses'] = self.instruction_misses[size]
            elif self.cache_config[cache]["content"] == "both":
                self.cache_data[cache]['data_loads'] = self.load_misses[previous_cache_level_size]
                self.cache_data[cache]['data_load_misses'] = self.load_misses[size]
                self.cache_data[cache]['data_stores'] = self.store_misses[previous_cache_level_size]
                self.cache_data[cache]['data_store_misses'] = self.store_misses[size]
                self.cache_data[cache]['instr_load_misses'] = self.instruction_misses[size]
            else:
                print "The cache configuration is not valid!"
                sys.exit(1)

            if self.cache_config[cache]["content"] == "data" or self.cache_config[cache]["content"] == "both":
                previous_cache_level_size = self.cache_config[cache]["size"]

        # save name for the LLC
        self.LLC = cache

    def calculate_load_latency(self):
    	total_cache_latency = 0.0
    	for k,v in self.cache_data.iteritems():
        	# leave instruction cache data out
            if self.cache_config[k]["content"] == "data" or self.cache_config[k]["content"] == "both":
    		    total_cache_latency += float(v["data_loads"] - v["data_load_misses"]) * self.config.get_cache_access_cost(self.cache_config[k]["size"])

    	if self.cache_data["L1D"]["data_loads"] != 0:
    		self.load_latency = total_cache_latency / self.cache_data["L1D"]["data_loads"]
    	else:
    		self.load_latency = 0

    def get_load_latency(self):
        return self.load_latency

    def get_cache_data(self):
        return self.cache_data

    def estimate_LLC_penalty(self, D_eff, interpolated_dependences, dep_load_distr, micro_op_count, sample_rate):
    	LLC_loads = self.cache_data[self.LLC]["data_loads"]
    	LLC_load_misses = self.cache_data[self.LLC]["data_load_misses"]

    	LLC_ROB_hits = float(LLC_loads - LLC_load_misses) / (sample_rate * micro_op_count) * self.ROB_size
    	average_path = interpolated_dependences[0]
    	# longest_load_path = interpolated_dependences[3]

    	if len(dep_load_distr) > 0:
    		loads_in_ROB = float(dep_load_distr[0]) / micro_op_count * self.ROB_size
    		min_dependent = LLC_ROB_hits / (dep_load_distr[1] * loads_in_ROB)
    		chance_dependent = 1.0 / (dep_load_distr[1] * loads_in_ROB)
    	else:
    		return 0

    	max_dependent = min(LLC_ROB_hits, dep_load_distr[-1] * loads_in_ROB)
        # max_dependent = min(LLC_ROB_hits, longest_load_path)

    	max_bound = int(max_dependent - int(min_dependent))
    	penalty_min_down_max_down = self.LLC_hit_delay * int(min_dependent) + max(0, self.LLC_hit_delay * (max_bound - 1) * chance_dependent)
    	penalty_min_down_max_up = self.LLC_hit_delay * int(min_dependent) + self.LLC_hit_delay * max_bound * chance_dependent

    	max_bound = int(max_dependent - int(min_dependent) + 1)
    	penalty_min_up_max_down = self.LLC_hit_delay * (int(min_dependent) + 1) + max(0, self.LLC_hit_delay * (max_bound - 1) * chance_dependent)
    	penalty_min_up_max_up = self.LLC_hit_delay * (int(min_dependent) + 1) + self.LLC_hit_delay * max_bound * chance_dependent

    	LLC_penalty_min_down_max_down_new = max(0, penalty_min_down_max_down - self.ROB_size / D_eff)
    	LLC_penalty_min_down_max_up_new = max(0, penalty_min_down_max_up - self.ROB_size / D_eff)
    	LLC_penalty_min_up_max_down_new = max(0, penalty_min_up_max_down - self.ROB_size / D_eff)
    	LLC_penalty_min_up_max_up_new = max(0, penalty_min_up_max_up - self.ROB_size / D_eff)

    	fract_min_down, fract_min_up = 1 - math.modf(min_dependent)[0], math.modf(min_dependent)[0]
    	fract_max_down, fract_max_up = 1 - math.modf(max_dependent)[0], math.modf(max_dependent)[0]

    	LLC_penalty = fract_min_down * fract_max_down * LLC_penalty_min_down_max_down_new + fract_min_down * fract_max_up * LLC_penalty_min_down_max_up_new + fract_min_up * fract_max_down * LLC_penalty_min_up_max_down_new + fract_min_up * fract_max_up * LLC_penalty_min_up_max_up_new

    	return LLC_penalty * micro_op_count / self.ROB_size * sample_rate
        # return LLC_penalty

    def calculate_instruction_miss_penalty(self):
        instruction_miss_penalty = 0
        for k1, v1 in self.cache_data.iteritems():
            for k2, v2 in v1.iteritems():
                if k2 == 'instr_load_misses':
                    instruction_miss_penalty += v2 * self.config.get_cache_miss_cost(self.cache_config[k1]["size"])
        return instruction_miss_penalty
