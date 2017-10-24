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

import os, sys, pdb, glob
from aif_lib import Stream_Reader

class Data_Reader():
	def __init__(self, input_root, config):
		self.input_root = input_root
		self.ROB_size = config.get_ROB_size()
		self.cacheblock_size = config.get_cacheline_size()
		self.entropy_type = config.get_entropy_type()
		self.IP_bits = int(config.get_IP_bits())
		self.BHR_size = int(config.get_BHR_size())

		self.read_metadata()
		self.read_phase_window_bounds()

		self.create_utrace_generator()
		self.create_entropy_generator()
		self.create_MLP_generator()
		self.create_cold_generator()

	def get_log_contents(self):
		return self.profiler_metadata, self.phase_bounds, self.window_bounds

	def read_metadata(self):
		self.profiler_metadata = {}

		f = open(os.path.join(self.input_root, "log.out"), "r")
		# parse metadata
		for line in f:
			if len(line) > 1:
				if line == "--BEGIN METADATA--\n":
					begin_metadata = True
				elif line == "--END METADATA--\n":
					break
				elif begin_metadata:
					# ignore some lines
					if line.startswith("VERSION") or "configuration" in line:
						continue
					else:
						line = line.strip()
						parameter,value = line.split(" ")
						if parameter == "used_uops":
							self.profiler_metadata[parameter] = value.split(",")
						else:
							self.profiler_metadata[parameter] = value
		f.close()

		self.compressed = bool(int(self.profiler_metadata["enable_compression"]))

	def read_phase_window_bounds(self):
		# parse phase bounds
		# [PINTOOL] Reached fastforward phase at instruction 0, fasforwarding until instruction 800000000
		# [PINTOOL] Reached warmup phase at instruction 800000001, warming up until instruction 900000000
		# [PINTOOL] Reached detailed phase at instruction 900000003, instrumenting detailed until instruction 1000000000
		# parse window lengths
		# [PINTOOL] Window started at 901000009
		# [PINTOOL] Window ended at 902000007
		self.phase_bounds, self.window_bounds = [], []
		f = open(os.path.join(self.input_root, "log.out"), "r")
		window_started = False
		for line in f:
			if "fastforward phase" in line:
				self.phase_bounds.append(("F", line.split(" ")[6]))
			elif "warmup phase" in line:
				self.phase_bounds.append(("W", line.split(" ")[6]))
			elif "detailed phase" in line:
				self.phase_bounds.append(("D", line.split(" ")[6]))
			elif "Window started" in line:
				self.window_bounds.append([int(line.split(",")[0].split(" ")[-1])])
				window_started = True
			elif "Window ended" in line:
				if not window_started:
					print "[ERROR] log-file is not in correct format, 'Window ended'-string should have been preceeded by 'Window started'-string!"
				self.window_bounds[-1].append(int(line.split(",")[0].split(" ")[-1]))
				window_started = False
		f.close()
		if window_started:
			print "[ERROR] log-file is not in correct format, 'Window started'-string should have been followed by 'Window ended'-string!"

	def read_trace_data(self):
		trace = []

		# parse trace lengths
		trace_lengths = utrace_file_pb2.uTrace()
		f = open(os.path.join(self.input_root, "utraces.0"), "rb")
		trace_lengths.ParseFromString(f.read())
		f.close()

		for i,u,l,s in zip(trace_lengths.inscount, trace_lengths.uopcount, trace_lengths.loads, trace_lengths.stores):
			trace.append([int(i), int(u), int(l), int(s)])

		return trace

	def create_utrace_generator(self):
		utrace_files = []
		for root,dirs,files in os.walk(self.input_root):
			for f in files:
				if "utrace." in f:
					utrace_files.append(os.path.join(root, f))

		utrace_reader = Stream_Reader(utrace_files, "UTRACE", self.compressed)

		# this protobuf file contains one message at the start detailing the used uop categories, read this first, then construct a generator for the other uTrace-messages
		uop_string = utrace_reader.read_message()
		self.uop_cats = {}
		counter = 0
		for ids in uop_string.uop_id_to_string:
			self.uop_cats[counter] = ids
			counter += 1

		self.gen_utrace = utrace_reader.iter_in_place()

	def create_entropy_generator(self):
		entropy_files = []
		for root,dirs,files in os.walk(self.input_root):
			for f in files:
				if "entropy." in f:
					entropy_files.append(os.path.join(root, f))

		entropy_reader = Stream_Reader(entropy_files, "BRANCH", self.compressed)

		self.gen_entropy = entropy_reader.iter_in_place()

	def create_MLP_generator(self):
		mlp_files = []
		for root,dirs,files in os.walk(self.input_root):
			for f in files:
				if "mlp." in f:
					mlp_files.append(os.path.join(root, f))

		mlp_reader = Stream_Reader(mlp_files, "MLP", self.compressed)

		self.gen_mlp = mlp_reader.iter_in_place()

	def create_cold_generator(self):
		cold_files = []
		for root,dirs,files in os.walk(self.input_root):
			for f in files:
				if "cold_misses." in f:
					cold_files.append(os.path.join(root, f))

		cold_reader = Stream_Reader(cold_files, "COLD", self.compressed)

		self.gen_cold = cold_reader.iter_in_place()

	def read_next_utrace(self):
		utrace = next(self.gen_utrace)

		stats = [utrace.stats.inscount, utrace.stats.uopcount, utrace.stats.loads, utrace.stats.stores]

		dependences = []
		for rob, AP, BP, CP in zip(utrace.trace.rob, utrace.trace.average_path, utrace.trace.branch_path, utrace.trace.critical_path):
			dependences.append([rob, AP, BP, CP])

		uop_hist = {}
		for uid,freq in zip(utrace.hist.uop_id, utrace.hist.uop_freq):
			uop_hist[self.uop_cats[uid]] = freq

		return stats, dependences, uop_hist

	def read_next_entropy_window(self):
		entropy_window = next(self.gen_entropy)

		# we have to check up to three different windows, because the local, global and tour window are saved subsequently
		if entropy_window.type != self.entropy_type:
			entropy_window = next(self.gen_entropy)
			if entropy_window.type != self.entropy_type:
				entropy_window = next(self.gen_entropy)

		branches = entropy_window.branches

		if entropy_window.type != self.entropy_type:
			print "Needed entropy type was not found in file!"
			sys.exit(1)

		for ip in entropy_window.ips:
			if ip.bits == self.IP_bits:
				for bhr,entropy in zip(ip.bhr_bits, ip.entropy):
					if bhr == self.BHR_size:
						return (entropy, branches)
				# if we execute the following lines of code, something went wrong
				print "Required BHR size not found in entropy files, you need to reprofile for a BHR up to " + str(self.BHR_size) + "!"
				sys.exit(1)
			else:
				continue

		# if we execute the following lines of code, something went wrong
		print "Required IP bits not found in entropy files, you need to reprofile for IP bits up to " + str(self.IP_bits) + "!"
		sys.exit(1)

	def read_next_MLP_window(self):
		mlp = next(self.gen_mlp)

		load_dependence_distr = []
		for lc in mlp.chain_stats:
			ROB_size = int(lc.ROB_size)
			# take the first line for which the ROB size is smaller or equal, this is the correct load distribution
			if ROB_size <= self.ROB_size:
				total_loads = [int(load) for load in lc.frequency]
				load_dependence_distr = [sum(total_loads)]
				load_dependence_distr.extend([float(freq) / load_dependence_distr[0] for freq in total_loads])
			elif ROB_size > self.ROB_size:
				break

		reuse_distr = {}
		for pc,reuse_stat in zip(mlp.pc, mlp.reuse_stats):
			reuse_distr[int(pc)] = [int(reuse_stat.first_reference)]
			reuse_distr[int(pc)].extend([(int(rs),int(t)) for rs,t in zip(reuse_stat.reuse, reuse_stat.times)])

		stride_distr = {}
		for pc,stride_stat in zip(mlp.pc, mlp.stride_stats):
			stride_distr[int(pc)] = [int(stride_stat.first_address)]
			stride_distr[int(pc)].extend([(int(s),int(t)) for s,t in zip(stride_stat.stride, stride_stat.times)])

		return load_dependence_distr, reuse_distr, stride_distr

	def read_next_cold_window(self):
		cold = next(self.gen_cold)

		cold_miss_distr = []
		for cd in cold.cold_distribution:
			ROB_size = int(cd.ROB_size)
			cacheblock_size = int(cd.cacheblock_size)
			# take the first line for which the ROB size is smaller or equal, this is the correct load distribution
			if ROB_size == self.ROB_size and cacheblock_size == self.cacheblock_size:
				for misses, occurences in zip(cd.misses_in_ROB, cd.occurences):
					cold_miss_distr.append((misses, occurences))
				return cold_miss_distr

		print "Error: no cold miss distribution found for cacheblock = " + str(self.cacheblock_size) + " and ROB = " + str(self.ROB_size)
