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
#			Moncef Mechri, Uppsala University
#  Copyright: 2016, Ghent University

import sys, os, bisect, pickle, pdb, time, glob
from collections import Counter, defaultdict

import lrumodel
from aif_lib import sd_file_util, memory_file_pb2, Stream_Reader
from in_out import Debug_Printer

class Statstack:
	def __init__(self, constants, benchmark, base_name, ss_version, _type, content, profiler_metadata, progress_printer):
		self.input_dir = constants.input_dir
		self.output_dir = constants.output_dir
		self.benchmark = benchmark
		self.benchmark_root = os.path.join(self.input_dir, benchmark)
		self.file_base_name = base_name

		# use old or new statstack
		self.ss_version = ss_version
		# type = (sample, trace)
		self.type = _type
		# content = (data, instr)
		self.content = content

		self.compressed = bool(int(profiler_metadata["enable_compression"]))
		self.sample_rate = int(profiler_metadata["p"])

		self.progress_printer = progress_printer
		self.debug_printer = Debug_Printer(self.output_dir, benchmark, "debug_statstack")

		self.prev_bursts = []
		self.prev_sd_hists = {}

		# generate sd file names
		self.load_sd_file, self.store_sd_file = None, None
		if self.type == "sample":
			if self.content == "data":
				self.load_sd_file = os.path.join(self.input_dir, "sd_hists_" + self.ss_version, "sd_load_" + self.benchmark + ".in")
				self.store_sd_file = os.path.join(self.input_dir, "sd_hists_" + self.ss_version, "sd_store_" + self.benchmark + ".in")
			elif self.content == "instr":
				self.load_sd_file = os.path.join(self.input_dir, "sd_hists_" + self.ss_version, "sd_instr_" + self.benchmark + ".in")
		elif self.type == "trace":
			self.load_sd_file = os.path.join(self.input_dir, "sd_hists_" + self.ss_version, "sd_load_PC_" + self.benchmark + ".in")

		# check if these files exist already, if they do, we don't need to calculate stack distances again
		self.load_sd_gen, self.store_sd_gen = None, None
		if os.path.isfile(self.load_sd_file):
			if self.type == "sample":
				load_reader = sd_file_util.SD_Hist_Reader(self.load_sd_file, PC = False)
			elif self.type == "trace":
				load_reader = sd_file_util.SD_Hist_Reader(self.load_sd_file, PC = True)
			self.load_sd_gen = load_reader.iter_in_place()
		if self.store_sd_file != None and os.path.isfile(self.store_sd_file):
			store_reader = sd_file_util.SD_Hist_Reader(self.store_sd_file, PC = False)
			self.store_sd_gen = store_reader.iter_in_place()

		# if one or more generators don't exist, we have to read the files
		if (self.type != "trace" and self.content != "instr" and self.store_sd_gen == None) or self.load_sd_gen == None:
			no_ooo_sample_files = self.discover_sample_files()
			self.progress_printer.print_message("Creating reuse distance histograms from files " + ", ".join(sorted([s.split("/")[-1] for s in self.all_samples])))
			if self.ss_version == "old":
				self.create_rdist_hists_old()
				if self.type == "trace":
					self.create_rdist_hists_old_PC()
			elif self.ss_version == "new":
				self.create_rdist_hists_new()

				self.create_generators()

				self.last_dangling = None
				self.last_ooo = [None] * no_ooo_sample_files

			self.create_sd_hist_writers()

		# read burst boundaries for alignment
		self.read_burst_edges(os.path.join(self.benchmark_root, "burst_" + self.file_base_name + ".0"))

	def get_sd_hists(self, _type="rw", bursts = []):
		unique_bursts = sorted(list(set(bursts) - set(self.prev_bursts)))
		if _type == "r":
			if self.load_sd_gen != None:
				# fetch the stack distance histogram
				self.sdist_hists = {}
				for ub in unique_bursts:
					sd_hist_pb = next(self.load_sd_gen)
					if self.type == "sample":
						self.sdist_hists[ub] = Counter()
						for sd,count in zip(sd_hist_pb.sd, sd_hist_pb.count):
							self.sdist_hists[ub][int(sd)] = int(count)
					elif self.type == "trace":
						self.sdist_hists_PC = defaultdict(Counter)
						burst = sd_hist_pb.burst_id
						self.sdist_hists_PC[burst] = defaultdict(Counter)
						for sd_hist in sd_hist_pb.sd_hists:
							PC = sd_hist.id
							self.sdist_hists_PC[burst][PC] = defaultdict(Counter)
							for sd,count in zip(sd_hist.sd, sd_hist.count):
								self.sdist_hists_PC[burst][PC][sd] = count

				intersection = list(set(self.prev_bursts) & set(bursts))
				for intersect in intersection:
					if self.type == "sample":
						self.sdist_hists[intersect] = self.prev_sd_hists[intersect]
					elif self.type == "trace":
						self.sdist_hists_PC[intersect] = self.prev_sd_hists[intersect]
			else:
				# calculate the stack distance histogram
				if self.ss_version == "old":
					# we're not using generators here anymore, all data is kept in memory, so no need to use unique bursts
					self.calculate_sdist_hists_old(bursts)
				elif self.ss_version == "new":
					# because we're using a generator here, we need to use unique bursts, because the stack distances for previously encountered bursts have already been calculated and we cannot calculate them again without rebuilding and reiterating the generator
					self.sdist_hists = defaultdict(Counter)
					if self.type == "trace":
						self.sdist_hists_PC = defaultdict()
					if len(unique_bursts) > 0:
						self.calculate_sdist_hists_new(unique_bursts, _type='r')
					if self.type == "sample":
						self.save_sd_hist(self.sdist_hists, "load")
						intersection = list(set(self.prev_bursts) & set(bursts))
						for intersect in intersection:
							self.sdist_hists[intersect] = self.prev_sd_hists[intersect]
					elif self.type == "trace":
						self.save_sd_hist(self.sdist_hists_PC, "load")
						intersection = list(set(self.prev_bursts) & set(bursts))
						for intersect in intersection:
							self.sdist_hists_PC[intersect] = self.prev_sd_hists[intersect]
		elif _type == "w":
			if self.store_sd_gen != None:
				# fetch the stack distance histogram
				self.sdist_hists = {}
				for ub in unique_bursts:
					if self.type == "sample":
						sd_hist_pb = next(self.store_sd_gen)
						self.sdist_hists[ub] = Counter()
						for sd,count in zip(sd_hist_pb.sd, sd_hist_pb.count):
							self.sdist_hists[ub][int(sd)] = int(count)
					elif self.type == "trace":
						self.sdist_hists_PC = defaultdict(Counter)
						burst = sd_hist_pb.burst_id
						self.sdist_hists_PC[burst] = defaultdict(Counter)
						for sd_hist in sd_hist_pb.sd_hists:
							PC = sd_hist.id
							self.sdist_hists_PC[burst][PC] = defaultdict(Counter)
							for sd,count in zip(sd_hist.sd, sd_hist.count):
								self.sdist_hists_PC[burst][PC][sd] = count

				intersection = list(set(self.prev_bursts) & set(bursts))
				for intersect in intersection:
					if self.type == "sample":
						self.sdist_hists[intersect] = self.prev_sd_hists[intersect]
					elif self.type == "trace":
						self.sdist_hists_PC[intersect] = self.prev_sd_hists[intersect]
			else:
				# calculate the stack distance histogram
				if self.ss_version == "old":
					self.calculate_sdist_hists_old(bursts)
				elif self.ss_version == "new":
					self.sdist_hists = defaultdict(Counter)
					if self.type == "trace":
						self.sdist_hists_PC = defaultdict()
					if len(unique_bursts) > 0:
						self.calculate_sdist_hists_new(unique_bursts, _type='w')
					if self.type == "sample":
						self.save_sd_hist(self.sdist_hists, "store")
						intersection = list(set(self.prev_bursts) & set(bursts))
						for intersect in intersection:
							self.sdist_hists[intersect] = self.prev_sd_hists[intersect]
					elif self.type == "trace":
						self.save_sd_hist(self.sdist_hists_PC, "store")
						intersection = list(set(self.prev_bursts) & set(bursts))
						for intersect in intersection:
							self.sdist_hists_PC[intersect] = self.prev_sd_hists[intersect]

		self.prev_bursts = bursts
		if self.type == "sample":
			self.prev_sd_hists = self.sdist_hists
			return self.sdist_hists
		elif self.type == "trace":
			self.prev_sd_hists = self.sdist_hists_PC
			return self.sdist_hists_PC

	def create_sd_hist_writers(self):
		sd_hists_dir_name = "sd_hists_" + self.ss_version

		if not os.path.exists(os.path.join(self.input_dir, sd_hists_dir_name)):
			os.makedirs(os.path.join(self.input_dir, sd_hists_dir_name))

		if self.load_sd_file != None:
			self.load_sd_writer = sd_file_util.SD_Hist_Writer(self.load_sd_file)
		if self.store_sd_file != None:
			self.store_sd_writer = sd_file_util.SD_Hist_Writer(self.store_sd_file)

	def save_sd_hist(self, sd_to_save, data):
		if data == "load":
			writer = self.load_sd_writer
		elif data == "store":
			writer = self.store_sd_writer

		if self.type == "sample":
			message = writer.dict_to_proto(sd_to_save)
		if self.type == "trace":
			message = writer.PC_dict_to_proto(sd_to_save)
		for burst, proto in message:
			writer.write_sd_hist(proto)

	def read_burst_edges(self, file_name):
		self.burst_edges, self.burst_begin_edges = [], []

		burst_boundaries = memory_file_pb2.Burst_Profile()
		f = open(file_name, "rb")
		burst_boundaries.ParseFromString(f.read())
		f.close()

		for burst in burst_boundaries.bursts:
			self.burst_edges.append([int(burst.instr_begin), int(burst.instr_end), int(burst.memaccess_begin), int(burst.memaccess_end), int(burst.takeoff_loads), int(burst.takeoff_stores), int(burst.landing_loads), int(burst.landing_stores)])

			self.burst_begin_edges.append(int(burst.memaccess_begin))

	def align_bursts_windows(self, window_bounds):
		aligned_bursts, iterate_burst_bounds = [], self.burst_edges

		for wb in window_bounds:
			burst_low = iterate_burst_bounds[0]
			for ss_wb in iterate_burst_bounds:
				if ss_wb[0] <= wb[0]:
					burst_low = ss_wb
				else:
					break
			burst_low_index = self.burst_edges.index(burst_low)
			iterate_burst_bounds = self.burst_edges[burst_low_index:]

			burst_high = iterate_burst_bounds[0]
			for ss_wb in iterate_burst_bounds:
				if ss_wb[1] > wb[1]:
					burst_high = ss_wb
					break
			burst_high_index = self.burst_edges.index(burst_high)

			aligned_bursts.append([])
			for b in range(burst_low_index, burst_high_index + 1):
				aligned_bursts[-1].append(b)

		return aligned_bursts

	def interpolate_miss_ratios(self, current_window, current_bursts, miss_ratios):
		interpolated_miss_ratios = {}

		current_burst_edges = [[self.burst_edges[cb][0], self.burst_edges[cb][1]] for cb in current_bursts]

		for cs,mr in miss_ratios.iteritems():
			if len(current_burst_edges) > 1:
				sample_low, sample_high = current_window[0], current_window[1]
				curr_burst, all_misses, all_accesses = 0, 0, 0
				ratio1, mpi1, misses1, api1, accesses1 = 0, 0, 0, 0, 0
				mpi2, misses2, api2, accesses2 = 0, 0, 0, 0

				while sample_low != sample_high:
					if curr_burst + 1 < len(current_burst_edges):
						ratio1 = max(current_burst_edges[curr_burst][1] - sample_low, 0.0)
						try:
							instr_curr_burst = current_burst_edges[curr_burst][1] - current_burst_edges[curr_burst][0]
							mpi1 = float(mr[curr_burst][0] * mr[curr_burst][1] * self.sample_rate) / instr_curr_burst
							api1 = float(mr[curr_burst][1] * self.sample_rate) / instr_curr_burst
						except IndexError:
							mpi1 = 0
							api1 = 0
						misses1 = mpi1 * ratio1
						accesses1 = api1 * ratio1

						# integration of linear interpolated function between mpi1 and mpi2
						# no interpolation needed if difference is 0, bursts are next to each other
						# CHECK THIS: this does not happen in our current setup, so we cannot test if it's correct
						x1 = max(current_burst_edges[curr_burst][1], sample_low)
						x2 = min(current_burst_edges[curr_burst + 1][0], current_window[1])
						if current_burst_edges[curr_burst + 1][0] - current_burst_edges[curr_burst][1] != 0:
							try:
								instr_next_burst = current_burst_edges[curr_burst + 1][1] - current_burst_edges[curr_burst + 1][0]
								mpi2 = float(mr[curr_burst][0] * mr[curr_burst][1] * self.sample_rate) / instr_next_burst
								api2 = float(mr[curr_burst][1] * self.sample_rate) / instr_next_burst
							except IndexError:
								mpi2 = 0
								api2 = 0

							instr_burst = current_burst_edges[curr_burst + 1][0] - current_burst_edges[curr_burst][1]
							misses2 = float(mpi1) * (x2 - x1) + float(mpi2 - mpi1) / instr_burst * (float(x2 ** 2) / 2 - float(x1 ** 2) / 2) + (current_burst_edges[curr_burst][1] * mpi1 - current_burst_edges[curr_burst][1] * mpi2) / instr_burst * (x2 - x1)
							accesses2 = float(api1) * (x2 - x1) + float(api2 - api1) / instr_burst * (float(x2 ** 2) / 2 - float(x1 ** 2) / 2) + (current_burst_edges[curr_burst][1] * api1 - current_burst_edges[curr_burst][1] * api2) / instr_burst * (x2 - x1)

						sample_low += ratio1 + (x2 - x1)
						all_misses += misses1 + misses2
						all_accesses += accesses1 + accesses2
					else:
						ratio1 = sample_high - current_burst_edges[curr_burst][0]
						try:
							instr_burst = current_burst_edges[curr_burst][1] - current_burst_edges[curr_burst][0]
							mpi1 = float(mr[curr_burst][0] * mr[curr_burst][1] * self.sample_rate) / instr_burst
							api1 = float(mr[curr_burst][1] * self.sample_rate) / instr_burst
						except IndexError:
							mpi1 = 0
							api1 = 0
						misses1 = mpi1 * ratio1
						accesses1 = api1 * ratio1

						sample_low += ratio1
						all_misses += misses1
						all_accesses += accesses1

					curr_burst += 1

				if all_accesses == 0:
					interpolated_miss_ratios[cs] = (0, 0)
				else:
					interpolated_miss_ratios[cs] = (all_misses / all_accesses, all_accesses)
			else:
				try:
					instr_burst = (current_burst_edges[0][1] - current_burst_edges[0][0])
					mpi = float(mr[0][0] * mr[0][1] * self.sample_rate) / instr_burst
					api = float(mr[0][1] * self.sample_rate) / instr_burst
				except IndexError:
					mpi = 0
					api = 0

				if api == 0:
					interpolated_miss_ratios[cs] = (0, 0)
				else:
					interpolated_miss_ratios[cs]= (mpi / api, api * (current_window[1] - current_window[0]))

		return interpolated_miss_ratios

	def interpolate_L1_hits(self, current_window, current_bursts, L1_miss_ratio):
		interpolated_miss_ratios = {}

		current_burst_edges = [[self.burst_edges[cb][0], self.burst_edges[cb][1]] for cb in current_bursts]

		if len(current_burst_edges) > 1:
			sample_low, sample_high = current_window[0], current_window[1]
			curr_burst, all_hits, all_accesses = 0, 0, 0
			ratio1, hpi1, hits1, api1, accesses1 = 0, 0, 0, 0, 0
			hpi2, hits2, api2, accesses2 = 0, 0, 0, 0

			while sample_low != sample_high:
				if curr_burst + 1 < len(current_burst_edges):
					ratio1 = max(current_burst_edges[curr_burst][1] - sample_low, 0.0)
					try:
						instr_curr_burst = current_burst_edges[curr_burst][1] - current_burst_edges[curr_burst][0]
						hpi1 = float((1 - L1_miss_ratio[curr_burst][0]) * L1_miss_ratio[curr_burst][1] * self.sample_rate) / instr_curr_burst
						api1 = float(L1_miss_ratio[curr_burst][1] * self.sample_rate) / instr_curr_burst
					except IndexError:
						hpi1 = 0
						api1 = 0
					hits1 = hpi1 * ratio1
					accesses1 = api1 * ratio1

					# integration of linear interpolated function between hpi1 and hpi2
					# no interpolation needed if difference is 0, bursts are next to each other
					# CHECK THIS: this does not happen in our current setup, so we cannot test if it's correct
					x1 = max(current_burst_edges[curr_burst][1], sample_low)
					x2 = min(current_burst_edges[curr_burst + 1][0], current_window[1])
					if current_burst_edges[curr_burst + 1][0] - current_burst_edges[curr_burst][1] != 0:
						try:
							instr_next_burst = current_burst_edges[curr_burst + 1][1] - current_burst_edges[curr_burst + 1][0]
							hpi2 = float((1 - L1_miss_ratio[curr_burst][0]) * L1_miss_ratio[curr_burst][1] * self.sample_rate) / instr_next_burst
							api2 = float(L1_miss_ratio[curr_burst][1] * self.sample_rate) / instr_next_burst
						except IndexError:
							mpi2 = 0
							api2 = 0

						instr_burst = current_burst_edges[curr_burst + 1][0] - current_burst_edges[curr_burst][1]
						misses2 = float(hpi1) * (x2 - x1) + float(hpi2 - hpi1) / instr_burst * (float(x2 ** 2) / 2 - float(x1 ** 2) / 2) + (current_burst_edges[curr_burst][1] * hpi1 - current_burst_edges[curr_burst][1] * hpi2) / instr_burst * (x2 - x1)
						accesses2 = float(api1) * (x2 - x1) + float(api2 - api1) / instr_burst * (float(x2 ** 2) / 2 - float(x1 ** 2) / 2) + (current_burst_edges[curr_burst][1] * api1 - current_burst_edges[curr_burst][1] * api2) / instr_burst * (x2 - x1)

					sample_low += ratio1 + (x2 - x1)
					all_hits += hits1 + hits2
					all_accesses += accesses1 + accesses2
				else:
					ratio1 = sample_high - current_burst_edges[curr_burst][0]
					try:
						instr_burst = (current_burst_edges[curr_burst][1] - current_burst_edges[curr_burst][0])
						hpi1 = float((1 - L1_miss_ratio[curr_burst][0]) * L1_miss_ratio[curr_burst][1] * self.sample_rate) / instr_burst
						api1 = float(L1_miss_ratio[curr_burst][1] * self.sample_rate) / instr_burst
					except IndexError:
						hpi1 = 0
						api1 = 0
					hits1 = hpi1 * ratio1
					accesses1 = api1 * ratio1

					sample_low += ratio1
					all_hits += hits1
					all_accesses += accesses1

				curr_burst += 1

			if all_accesses == 0:
				interpolated_L1_hits = 0
			else:
				interpolated_L1_hits = all_hits
		else:
			try:
				instr_burst = (current_burst_edges[0][1] - current_burst_edges[0][0])
				hpi = float((1 - L1_miss_ratio[0][0]) * L1_miss_ratio[0][1] * self.sample_rate) / instr_burst
				api = float(L1_miss_ratio[0][1] * self.sample_rate) / instr_burst
			except IndexError:
				hpi = 0
				api = 0

			if api == 0:
				interpolated_L1_hits = 0
			else:
				interpolated_L1_hits = hpi  * (current_window[1] - current_window[0])

		return interpolated_L1_hits

	# Return an approximated first access assuming that it lands in the middle of the landing window
	def find_takeoff_burst(self, rdist, landing_burst):
		burst_size = self.burst_edges[landing_burst][3] - self.burst_edges[landing_burst][2]
		takeoff = max(self.burst_begin_edges[landing_burst] + (burst_size / 2) - rdist - 1, self.burst_begin_edges[0])
		takeoff_burst = bisect.bisect(self.burst_begin_edges, takeoff) - 1
		assert(takeoff_burst >= 0)
		return takeoff_burst

	# Merge rdist_hists from rdist_hists[first] to rdist_hists[last]. Also add optional_counter if not None
	def merge_counters_range(self, first, last, optional_counter=None):
		merged_counters = Counter()
		if optional_counter:
			merged_counters = optional_counter

		for i in range(first, last + 1):
			merged_counters.update(self.rdist_hists[i])

		return merged_counters

	def discover_sample_files(self):
		self.all_samples = []

		no_ooo_sample_files = 0
		for root,dirs,files in os.walk(self.benchmark_root):
			for f in files:
				if "_" + self.file_base_name + "." in f and f != "burst_" + self.file_base_name + ".0":
					self.all_samples.append(os.path.join(root, f))
				if "ooo_" + self.file_base_name in f:
					no_ooo_sample_files += 1

		return no_ooo_sample_files

	def create_rdist_hists_new(self):
		self.rdist_hists = defaultdict(Counter)

		sample_reader = Stream_Reader(self.all_samples, "STATSTACK", self.compressed)
		for sample in sample_reader.iter_in_place():
			if sample.HasField('end'):
				rdist = sample.end.access_counter - sample.begin.access_counter - 1
				# should this be begin or end?
				self.rdist_hists[sample.begin.burst_id][rdist] += 1
			else:
				self.rdist_hists[sample.begin.burst_id][sys.maxint] += 1

	def create_rdist_hists_old(self):
		self.rdist_hists, self.rdist_hists_load, self.rdist_hists_store = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)

		sample_reader = Stream_Reader(self.all_samples, "STATSTACK", self.compressed)
		for sample in sample_reader.iter_in_place():
			if sample.HasField('end'):
				rdist = sample.end.access_counter - sample.begin.access_counter - 1
				self.rdist_hists[sample.begin.burst_id][rdist] += 1
				if sample.end.access_type == 0:
					self.rdist_hists_load[sample.begin.burst_id][rdist] += 1
				elif sample.end.access_type == 1:
					self.rdist_hists_store[sample.begin.burst_id][rdist] += 1
			else:
				self.rdist_hists[sample.begin.burst_id][sys.maxint] += 1
				if sample.begin.access_type == 0:
					self.rdist_hists_load[sample.begin.burst_id][sys.maxint] += 1
				elif sample.begin.access_type == 1:
					self.rdist_hists_store[sample.begin.burst_id][sys.maxint] += 1

	def create_rdist_hists_old_PC(self):
		self.rdist_hists, self.rdist_hists_load, self.rdist_hists_store = defaultdict(), defaultdict(), defaultdict()

		sample_reader = Stream_Reader(self.all_samples, "STATSTACK", self.compressed)
		for sample in sample_reader.iter_in_place():
			pc = sample.begin.program_counter

			if not sample.begin.burst_id in self.rdist_hists:
				self.rdist_hists[sample.begin.burst_id] = defaultdict(Counter)
				self.rdist_hists_load[sample.begin.burst_id] = defaultdict(Counter)
				self.rdist_hists_store[sample.begin.burst_id] = defaultdict(Counter)

			if sample.HasField('end'):
				rdist = sample.end.access_counter - sample.begin.access_counter - 1
				self.rdist_hists[sample.begin.burst_id][pc][rdist] += 1
				if sample.end.access_type == 0:
					self.rdist_hists_load[sample.begin.burst_id][pc][rdist] += 1
				elif sample.end.access_type == 1:
					self.rdist_hists_store[sample.begin.burst_id][pc][rdist] += 1
			else:
				self.rdist_hists[sample.begin.burst_id][pc][sys.maxint] += 1
				if sample.begin.access_type == 0:
					self.rdist_hists_load[sample.begin.burst_id][pc][sys.maxint] += 1
				elif sample.begin.access_type == 1:
					self.rdist_hists_store[sample.begin.burst_id][pc][sys.maxint] += 1

	def create_generators(self):
		all_samples, all_ooo, all_dangling = [], [], []

		for root,dirs,files in os.walk(self.benchmark_root):
			for f in files:
				if "sample_" + self.file_base_name + "." in f and f != "burst_" + self.file_base_name + ".0":
					all_samples.append(os.path.join(root, f))
				elif "ooo_" + self.file_base_name + "." in f and f != "burst_" + self.file_base_name + ".0":
					all_ooo.append(os.path.join(root, f))
				elif "dangling_" + self.file_base_name + "." in f and f != "burst_" + self.file_base_name + ".0":
					all_dangling.append(os.path.join(root, f))

		all_samples = sorted(all_samples, key = lambda name: int(name.split(".")[-1]))
		all_ooo = sorted(all_ooo, key = lambda name: int(name.split(".")[-1]))
		all_dangling = sorted(all_dangling, key = lambda name: int(name.split(".")[-1]))

		sample_reader = Stream_Reader(all_samples, "STATSTACK", self.compressed)
		self.gen_sample = sample_reader.iter_in_place()

		# we need to keep the OoO generators seperately because if we append them, they might not be fully sorted
		self.gens_ooo = []
		for ooo in all_ooo:
			sample_reader = Stream_Reader([ooo], "STATSTACK", self.compressed)
			self.gens_ooo.append(sample_reader.iter_in_place())

		sample_reader = Stream_Reader(all_dangling, "STATSTACK", self.compressed)
		self.gen_dangling = sample_reader.iter_in_place()

	def categorize_landing_events(self, extracted_burst_edges, valid_bursts, _type = 'rw'):
		self.filtered_rdist_hists = defaultdict(Counter)
		if self.type == "trace":
			self.per_PC_filtered_rdist_hists = defaultdict()

		if self.type == "trace":
			if _type == "r":
				self.memops_to_find = sum([ebe[4] for ebe in extracted_burst_edges])
			elif _type == "w":
				self.memops_to_find = sum([ebe[5] for ebe in extracted_burst_edges])
		else:
			if _type == "r":
				self.memops_to_find = sum([ebe[6] for ebe in extracted_burst_edges])
			elif _type == "w":
				self.memops_to_find = sum([ebe[7] for ebe in extracted_burst_edges])

		self.events_dangling(valid_bursts, _type = _type)

		# edge case where we only have dangling samples (never seen)
		if self.memops_to_find != 0:
			self.events_ooo(valid_bursts, _type = _type)

		# edge case where we only have OoO and dangling samples (never seen)
		if self.memops_to_find != 0:
			self.events_complete(valid_bursts, _type = _type)

		if self.memops_to_find > 0:
			print "Error: number of memops is not 0, something is wrong in the streaming statstack version!"
			self.debug_printer.save_error_stats("Error: number of memops is not 0, something is wrong in the streaming statstack version!")
			sys.exit(1)

	def events_dangling(self, valid_bursts, _type = 'rw'):
		# check the last sample from a previous iteration
		check_next_dangling = False
		if self.last_dangling != None:
			if (_type == 'r' and self.last_dangling.begin.access_type == 0) or (_type == 'w' and self.last_dangling.begin.access_type == 1):
				burst = self.last_dangling.begin.burst_id
				if burst in valid_bursts:
					takeoff_PC = self.last_dangling.begin.program_counter

					self.filtered_rdist_hists[burst][sys.maxint] += 1

					if self.type == "trace":
						if burst not in self.per_PC_filtered_rdist_hists:
							self.per_PC_filtered_rdist_hists[burst] = defaultdict(Counter)

						self.per_PC_filtered_rdist_hists[burst][takeoff_PC][sys.maxint] += 1

					self.memops_to_find -= 1
					check_next_dangling = True
					self.last_dangling = None

				if burst < valid_bursts[0]:
					check_next_dangling = True

		if self.last_dangling == None or check_next_dangling:
			for sample in self.gen_dangling:
				# If the requested _type is not 'rw', then we keep only the dangling samples whose begin access' access_type is corresponds to _type.
				# This is not ideal, because the access_type of a dangling sample might not match the access_type of the corresponding cold miss, but we can't really do better than this
				if (_type == 'r' and sample.begin.access_type == 0) or (_type == 'w' and sample.begin.access_type == 1):
					burst = sample.begin.burst_id
					takeoff_PC = sample.begin.program_counter

					if burst > valid_bursts[-1]:
						self.last_dangling = sample
						break

					if burst in valid_bursts:
						self.filtered_rdist_hists[burst][sys.maxint] += 1

						if self.type == "trace":
							if burst not in self.per_PC_filtered_rdist_hists:
								self.per_PC_filtered_rdist_hists[burst] = defaultdict(Counter)

							self.per_PC_filtered_rdist_hists[burst][takeoff_PC][sys.maxint] += 1

						self.memops_to_find -= 1

	def events_ooo(self, valid_bursts, _type = 'rw'):
		# check the last sample from a previous iteration
		check_next_ooo = False
		for last in range(0, len(self.last_ooo)):
			if self.last_ooo[last] != None:
				if self.type == "sample" and ((_type == 'r' and self.last_ooo[last].end.access_type == 0) or (_type == 'w' and self.last_ooo[last].end.access_type == 1)):
					landing_burst = self.last_ooo[last].end.burst_id
					if landing_burst in valid_bursts:
						rdist = self.last_ooo[last].end.access_counter - self.last_ooo[last].begin.access_counter - 1
						self.filtered_rdist_hists[landing_burst][rdist] += 1

						self.memops_to_find -= 1

						check_next_ooo = True

					if landing_burst < valid_bursts[0]:
						check_next_ooo = True

				if self.type == "trace" and ((_type == 'r' and self.last_ooo[last].begin.access_type == 0) or (_type == 'w' and self.last_ooo[last].begin.access_type == 1)):
					# we take the takeoff pc instead of landing pc because their behaviour should be the same
					takeoff_burst = self.last_ooo[last].begin.burst_id
					takeoff_PC = self.last_ooo[last].begin.program_counter
					if takeoff_burst in valid_bursts:
						rdist = self.last_ooo[last].end.access_counter - self.last_ooo[last].begin.access_counter - 1
						self.filtered_rdist_hists[takeoff_burst][rdist] += 1

						if takeoff_burst not in self.per_PC_filtered_rdist_hists:
							self.per_PC_filtered_rdist_hists[takeoff_burst] = defaultdict(Counter)

						self.per_PC_filtered_rdist_hists[takeoff_burst][takeoff_PC][rdist] += 1

						self.memops_to_find -= 1

						check_next_ooo = True

					if takeoff_burst < valid_bursts[0]:
						check_next_ooo = True

			if self.last_ooo[last] == None or check_next_ooo:
				for sample in self.gens_ooo[last]:
					# If the requested _type is not 'rw', then we keep only the dangling samples whose begin access' access_type is corresponds to _type.
					# This is not ideal, because the access_type of a dangling sample might not match the access_type of the corresponding cold miss, but we can't really do better than this
					if self.type == "sample" and ((_type == 'r' and sample.end.access_type == 0) or (_type == 'w' and sample.end.access_type == 1)):
						landing_burst = sample.end.burst_id

						if landing_burst > valid_bursts[-1]:
							self.last_ooo[last] = sample
							break

						if landing_burst in valid_bursts:
							rdist = sample.end.access_counter - sample.begin.access_counter - 1
							self.filtered_rdist_hists[landing_burst][rdist] += 1

							self.memops_to_find -= 1

					if self.type == "trace" and ((_type == 'r' and sample.begin.access_type == 0) or (_type == 'w' and sample.begin.access_type == 1)):
						# we take the takeoff pc instead of landing pc because their behaviour should be the same
						takeoff_burst = sample.begin.burst_id
						landing_burst = sample.end.burst_id
						takeoff_PC = sample.begin.program_counter

						if takeoff_burst > valid_bursts[-1]:
							self.last_ooo[last] = sample
							break

						if takeoff_burst in valid_bursts:
							rdist = sample.end.access_counter - sample.begin.access_counter - 1
							self.filtered_rdist_hists[takeoff_burst][rdist] += 1

							if takeoff_burst not in self.per_PC_filtered_rdist_hists:
								self.per_PC_filtered_rdist_hists[takeoff_burst] = defaultdict(Counter)

							self.per_PC_filtered_rdist_hists[takeoff_burst][takeoff_PC][rdist] += 1

							self.memops_to_find -= 1

	def events_complete(self, valid_bursts, _type = 'rw'):
		for sample in self.gen_sample:
			if self.type == "sample" and ((_type == 'r' and sample.end.access_type == 0) or (_type == 'w' and sample.end.access_type == 1)):
				landing_burst = sample.end.burst_id

				if landing_burst in valid_bursts:
					self.memops_to_find -= 1
				# fast forward through warmup phases
				elif self.memops_to_find > 0:
					continue

				rdist = sample.end.access_counter - sample.begin.access_counter - 1
				self.filtered_rdist_hists[landing_burst][rdist] += 1

				if self.memops_to_find == 0:
					break

			if self.type == "trace" and ((_type == 'r' and sample.begin.access_type == 0) or (_type == 'w' and sample.begin.access_type == 1)):
				# we take the takeoff pc instead of landing pc because their behaviour should be the same
				takeoff_burst = sample.begin.burst_id
				landing_burst = sample.end.burst_id
				takeoff_PC = sample.begin.program_counter

				if takeoff_burst in valid_bursts:
					self.memops_to_find -= 1
				elif self.memops_to_find > 0:
					continue

				rdist = sample.end.access_counter - sample.begin.access_counter - 1
				self.filtered_rdist_hists[takeoff_burst][rdist] += 1

				if takeoff_burst not in self.per_PC_filtered_rdist_hists:
					self.per_PC_filtered_rdist_hists[takeoff_burst] = defaultdict(Counter)

				self.per_PC_filtered_rdist_hists[takeoff_burst][takeoff_PC][rdist] += 1

				if self.memops_to_find == 0:
					break

	def calculate_sdist_hists_old(self, bursts, _type='rw'):
		if _type != 'rw' and _type != 'r' and _type != 'w':
			raise ValueError('Unknown access_type %s' % (_type))

		self.sdist_hists = defaultdict()
		if self.type == "trace":
			self.sdist_hists_PC = defaultdict()

		for burst_id in bursts:
			dict_rdists = {"rw_rdist_hist" : self.rdist_hists[burst_id], "rd_rdist_hist" : self.rdist_hists_load[burst_id], "wr_rdist_hist" : self.rdist_hists_store[burst_id]}
			if self.type == "sample":
				self.sdist_hists[burst_id] = lrumodel.sdist_hist(dict_rdists, _type=_type)
			else:
				self.sdist_hists_PC[burst_id] = lrumodel.sdist_hist_PC(dict_rdists, _type=_type)

	def calculate_sdist_hists_new(self, bursts, _type='rw'):
		if _type != 'rw' and _type != 'r' and _type != 'w':
			raise ValueError('Unknown access_type %s' % (_type))

		extracted_burst_edges = [self.burst_edges[b] for b in bursts]
		self.categorize_landing_events(extracted_burst_edges, bursts, _type = _type)

		burst_errors = 0
		# if we found no landing memory operations of one type (e.g. loads) in a certain burst, this burst won't be added, add it here to make sure the interpolation is correct
		for burst in bursts:
			if not burst in self.filtered_rdist_hists:
				self.filtered_rdist_hists[burst] = Counter()
				if self.type == "trace":
					self.per_PC_filtered_rdist_hists[burst] = Counter()

		for burst, hist in self.filtered_rdist_hists.iteritems():
			current_vicinity = Counter()
			current_mapping = Counter()
			oldest_burst_in_vicinity = None
			self.sdist_hists[burst] = Counter()
			if self.type == "trace":
				self.sdist_hists_PC[burst] = Counter()
			for rdist in sorted(hist.keys()):
				if rdist != sys.maxint:
					begin_burst = self.find_takeoff_burst(rdist, burst)

					if begin_burst >= 0: #New add
						if oldest_burst_in_vicinity is None:
							current_vicinity = self.merge_counters_range(begin_burst, burst)
							oldest_burst_in_vicinity = begin_burst
							current_mapping = lrumodel.lru_sdist(current_vicinity)

						if begin_burst < oldest_burst_in_vicinity:
							current_vicinity = self.merge_counters_range(begin_burst, oldest_burst_in_vicinity -1, current_vicinity)
							oldest_burst_in_vicinity = begin_burst
							current_mapping = lrumodel.lru_sdist(current_vicinity)

						#if rdist is not in current_mapping, it means that we are missing one burst in the vicinity due to the approximation made in find_takeoff_burst()
						while begin_burst > 0 and rdist not in current_mapping:
							begin_burst -= 1
							current_vicinity = self.merge_counters_range(begin_burst, oldest_burst_in_vicinity -1, current_vicinity)
							oldest_burst_in_vicinity = begin_burst
							current_mapping = lrumodel.lru_sdist(current_vicinity)

						if rdist not in current_mapping:
							self.debug_printer.save_log_stats("Warning: reuse distance" + str(rdist) + "is not in the current mapping!")
							continue

						sdist = int(round(current_mapping[rdist]))
					else:
						burst_errors += 1 #New add
				else:
					sdist = sys.maxint

				self.sdist_hists[burst][sdist] += hist[rdist]

				if self.type == "trace":
					# burst might not be in per_PC_filtered_rdist_hists if there were only Dangling samples (no landing samples, thus, no rdist) or no samples at all
					if burst in self.per_PC_filtered_rdist_hists:
						# We could keep a list of per-pc histograms that contain rdist instead of doing a linear search through all the per-pc histograms for each rdist
						for pc, pc_rdist_hist in self.per_PC_filtered_rdist_hists[burst].iteritems():
							if rdist in pc_rdist_hist:
								if pc not in self.sdist_hists_PC[burst]:
									self.sdist_hists_PC[burst][pc] = Counter()

								self.sdist_hists_PC[burst][pc][sdist] += pc_rdist_hist[rdist]

		if burst_errors:
			print "Warning: " + str(burst_errors) + " burst errors encountered!"

	#Takes in a stack distance histogram and a cache size and returns the miss ratio
	def compute_miss_ratio(self, sdist_hist, cache_size, line_size):
		cache_size_in_lines = cache_size / line_size
		ref_count = 0
		miss_count = 0
		for sdist, count in sdist_hist.items():
			ref_count += count
			if sdist >= cache_size_in_lines:
				miss_count += count

		if ref_count == 0:
			return 0.0
		else:
			return miss_count / float(ref_count)

	def calculate_sample_miss_ratios(self, cache_sizes, sdist_hists, line_size):
		miss_ratios = {}
		cache_sizes = sorted(cache_sizes)
		for c in cache_sizes:
			miss_ratios[c] = []
			loop_keys = sorted(sdist_hists.keys())
			for k in loop_keys:
				miss_ratios[c].append((self.compute_miss_ratio(sdist_hists[k], c, line_size), sum(sdist_hists[k].values())))

		return miss_ratios

	def calculate_PC_miss_ratios(self, cache_sizes, sdist_hists_PC, line_size):
		miss_ratios_PC = {}
		cache_sizes = sorted(cache_sizes)

		for c in cache_sizes:
			miss_ratios_PC[c] = {}
			burst = sdist_hists_PC.keys()[0]
			for pc in sdist_hists_PC[burst].keys():
				miss_ratios_PC[c][pc] = (self.compute_miss_ratio(sdist_hists_PC[burst][pc], c, line_size), sum(sdist_hists_PC[burst][pc].values()))

		return miss_ratios_PC

	def print_sample(self, sample):
		if sample.HasField("end"):
			print "==Sample== MA_1: burst: " + str(sample.begin.burst_id) + " time: " + str(sample.begin.access_counter) + " PC: " + str(sample.begin.program_counter) + " address: " + str(sample.begin.memory_address) + " type: " + str(sample.begin.access_type) + " tid: " + str(sample.begin.thread_id),
			print " -- MA_2: burst: " + str(sample.end.burst_id) + " time: " + str(sample.end.access_counter) + " PC: " + str(sample.end.program_counter) + " address: " + str(sample.end.memory_address) + " type: " + str(sample.end.access_type) + " tid: " + str(sample.end.thread_id)
		else:
			print "==Dangling Sample== MA_1: burst: " + str(sample.begin.burst_id) + " time: " + str(sample.begin.access_counter) + " PC: " + str(sample.begin.program_counter) + " address: " + str(sample.begin.memory_address) + " type: " + str(sample.begin.access_type) + " tid: " + str(sample.begin.thread_id)

	def calculate_exclusive_miss_ratios(self, trace_load_miss_ratios):
		exclusive_trace_miss_ratios, sum_loads, prev_cs = {}, {}, 0
		for cs, pcs in trace_load_miss_ratios.iteritems():
			sum_loads[cs] = 0.0
			exclusive_trace_miss_ratios[cs] = 0.0
			for miss_data in pcs.itervalues():
				sum_loads[cs] += miss_data[1]
				exclusive_trace_miss_ratios[cs] += (miss_data[0] * miss_data[1])
			if prev_cs != 0:
				exclusive_trace_miss_ratios[prev_cs] -= exclusive_trace_miss_ratios[cs]

			prev_cs = cs

		for cs in trace_load_miss_ratios.keys():
			if sum_loads[cs] > 0:
				exclusive_trace_miss_ratios[cs] /= sum_loads[cs]
			else:
				exclusive_trace_miss_ratios[cs] = 0

		return exclusive_trace_miss_ratios, sum_loads
