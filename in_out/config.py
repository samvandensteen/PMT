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

class Config:
    def __init__(self, config_file, overwrite_config, output_dir):
        self.config_file = config_file
        self.output_dir = output_dir
        self.config = {}

        self.read_config()

    	# dictionary that might not be empty, if not empty, overwrite config
    	if overwrite_config != {}:
    		self.overwrite_config_parameters(overwrite_config)
    	self.save_used_config()

        self.get_cache_configuration()

        self.data_cache_access_cost = {}
        for key in self.cache_sizes:
            self.data_cache_access_cost[key] = sum(self.cache_tag_times[0:self.cache_sizes.index(key)]) + self.cache_access_time[self.cache_sizes.index(key)]

        self.data_cache_miss_cost = {}
        for key in self.cache_sizes[:-1]:
            self.data_cache_miss_cost[key] = sum(self.cache_tag_times[0:self.cache_sizes.index(key) + 1]) + self.cache_access_time[self.cache_sizes.index(key) + 1]
        self.data_cache_miss_cost[self.cache_sizes[-1]] = sum(self.cache_tag_times) + float(self.config["DRAM"]["data_access_time"]) + float(self.config["BUS"]["transfer_cycles"])

    def read_config(self):
    	f = open(self.config_file, "r")
    	for line in f:
    		if line.startswith("#"):
    			continue
    		elif "[" in line and "]" in line:
    			key = line.strip()[1:-1]
    			self.config[key] = {}
    		else:
    			if line != "\n":
    				self.config[key][line.split("=")[0].strip()] = line.split("=")[1].strip()

    def get_cache_configuration(self):
        self.cache_config = {}
    	self.cache_sizes, self.cache_access_time, self.cache_tag_times = [], [], []
    	self.cacheline_size = 0

        for k1,v1 in self.config.iteritems():
            for k2,v2 in v1.iteritems():
                if k2 == "type" and v2 == "cache":
                    self.cache_config[k1] = {}
                    for k3,v3 in v1.iteritems():
                        if k3 == "size":
                            self.cache_config[k1][k3] = int(v3) * 1024
                            if self.config[k1]["content"] == "data" or self.config[k1]["content"] == "both":
    							# kB from config to bytes
                                self.cache_sizes.append(int(v3) * 1024)
                                self.cache_access_time.append(int(self.config[k1]["data_access_time"]))
                                self.cache_tag_times.append(int(self.config[k1]["tag_time"]))
                        elif k3 == "line_size":
                            if self.cacheline_size != 0 and self.cacheline_size != int(v3):
                                print "We do not support different cacheline sizes in different cache levels, this will lead to undefined behaviour!"
                                sys.exit(1)
                            self.cacheline_size = int(v3)
                        else:
                            try:
                                self.cache_config[k1][k3] = int(v3)
                            except ValueError:
                                self.cache_config[k1][k3] = v3

        self.cache_access_time = [x for (y,x) in sorted(zip(self.cache_sizes, self.cache_access_time))]
        self.cache_tag_times = [x for (y,x) in sorted(zip(self.cache_sizes, self.cache_tag_times))]
        self.cache_sizes = sorted(self.cache_sizes)

    def overwrite_config_parameters(self, new_config):
        for structure,pv in new_config.iteritems():
        	if not structure in self.config:
        		print "Not a valid structure given as argument of -a | --argument (structure/parameter=value)!"
        	else:
        		for parameter,value in pv.iteritems():
        			if not parameter in self.config[structure]:
        				print "Not a valid parameter given as argument of -a | --argument (structure/parameter=value)!"
        			else:
        				self.config[structure][parameter] = value

    def save_used_config(self):
        f_config = open(os.path.join(self.output_dir, "used_config.cfg"), "a+")
        for structure,pv in self.config.iteritems():
            f_config.write("[" + str(structure) + "]\n")
            for parameter,value in pv.iteritems():
                f_config.write(parameter + " = " + self.config[structure][parameter] + "\n")
            f_config.write("\n")
        f_config.close()

    def get_cache_access_cost(self, cache_size):
        return self.data_cache_access_cost[cache_size]

    def get_cache_miss_cost(self, cache_size):
        return self.data_cache_miss_cost[cache_size]

    def get_LLC_size(self):
        return int(self.cache_sizes[-1])

    def get_LLC_access_cost(self):
        return self.data_cache_access_cost[self.cache_sizes[-1]]

    def get_LLC_miss_cost(self):
        return self.data_cache_miss_cost[self.cache_sizes[-1]]

    def get_cache_sizes(self):
        return self.cache_sizes

    def get_cacheline_size(self):
        return self.cacheline_size

    def get_cache_config(self):
        return self.cache_config

    def get_ROB_size(self):
        return int(self.config["CORE"]["window_size"])

    def get_frontend_size(self):
        return int(self.config["CORE"]["front_end_pipeline"])

    def get_MSHR_entries(self):
        return int(self.config["MSHR"]["entries"])

    def get_dispatch_width(self):
        return int(self.config["CORE"]["dispatch_width"])

    def get_prefetch_in_page(self):
        if self.config["PREFETCHER"]["prefetch_in_page"] == "true":
            return True
        else:
            return False

    def get_prefetcher_flows(self):
        return int(self.config["PREFETCHER"]["flows"])

    def get_DRAM_page_size(self):
        # used to check prefetches within page boundaries
        # we don't know where the address originited in a page, so we place it in the middle, hence half a page size +/- yields a prefetch out of the page
        return int(self.config["DRAM"]["page_size"]) / 2

    def get_DRAM_latency_with_tag(self):
        return sum(self.cache_tag_times) + float(self.config["DRAM"]["data_access_time"]) + float(self.config["BUS"]["transfer_cycles"])

    def get_DRAM_latency_no_tag(self):
        return float(self.config["DRAM"]["data_access_time"]) + float(self.config["BUS"]["transfer_cycles"])

    def get_bus_transfer_cycles(self):
        return float(self.config["BUS"]["transfer_cycles"])

    def get_instruction_latencies(self):
        return self.config["INSTRUCTION_LATENCIES"]

    def get_functional_units_ports(self):
        return self.config["FUNCTIONAL_UNITS_PORT"]

    def get_functional_unit_pipelined(self):
        return self.config["FUNCTIONAL_UNITS_PIPELINED"]

    def get_instruction_functional_unit(self):
        return self.config["INSTRUCTION_FUNCTIONAL_UNIT"]

    def get_branch_predictor_name(self):
        return self.config["BRANCH"]["name"]

    def get_entropy_type(self):
        return self.config["BRANCH"]["type"]

    def get_IP_bits(self):
        return self.config["BRANCH"]["ipBits_Pht"]

    def get_BHR_size(self):
        return  self.config["BRANCH"]["size_bhr"]
