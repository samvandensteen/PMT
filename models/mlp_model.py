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

import os, sys, pdb, random, math, bisect, numpy
from collections import deque
from in_out import Debug_Printer

class MLP_Model():
	def __init__(self, constants, config, benchmark, debug = False):
		self.config = config
		self.alpha = constants.alpha
		self.mlp_model = constants.mlp_model
		self.output_dir = constants.output_dir
		self.prefetcher_enabled = constants.prefetch
		self.queue_model = constants.queue_model

		# often used configuration variables
		self.ROB_size = self.config.get_ROB_size()
		self.cacheline_size = self.config.get_cacheline_size()
		self.DRAM_page_size = self.config.get_DRAM_page_size()
		self.MSHR_entries = self.config.get_MSHR_entries()
		self.prefetch_in_page = self.config.get_prefetch_in_page()
		self.prefetcher_flows = self.config.get_prefetcher_flows()
		self.dispatch_width = self.config.get_dispatch_width()
		self.DRAM_latency_with_tag = self.config.get_DRAM_latency_with_tag()
		self.LLC_miss_cost = self.config.get_LLC_miss_cost()
		self.LLC_size = self.config.get_LLC_size()
		self.bus_transfer_cycles = self.config.get_bus_transfer_cycles()

		# stats
		self.total_strides = 0
		self.total_no_strides = 0
		self.total_random_strides = 0
		self.total_randomly_placed_misses = 0
		self.total_ss_misses = 0

		self.debug_printer = Debug_Printer(self.output_dir, benchmark, "debug_mlp")

		self.debug = debug

		self.run_avg_MLP = 1
		self.run_avg_prefetched = 0
		self.run_avg_prefetched_extrapolated = 0

	def calculate_stride_misses(self, stride, refs):
		# number of refs == number of reuses, meaning that if we have 2 refs, we actually saw three memory accesses by that PC
		# calculate no cachelines referenced
		# stride is 0, always the same address is referenced
		if stride == 0:
			return [0] * refs
		else:
			if stride < self.cacheline_size:
				stride_pattern_misses = []
				# put start of the stride pattern at half the cacheline size (on average, this should be the most correct)
				cacheline = stride + self.cacheline_size / 2
				next_cacheline = self.cacheline_size
				for r in range(0, refs):
					if cacheline >= next_cacheline:
						stride_pattern_misses.append(1)
						next_cacheline += self.cacheline_size
					else:
						stride_pattern_misses.append(0)
					cacheline += stride
			else:
				stride_pattern_misses = [1] * refs
			return stride_pattern_misses

	def calculate_misses_PC_stride(self, stride_distr):
		stride_distr = sorted(stride_distr)
		# we have no stride, only one reference
		if len(stride_distr) == 0:
			return ("NO_STRIDE", [False], [1])
		elif len(stride_distr) == 1:
			stride_miss_pattern = [1] + self.calculate_stride_misses(stride_distr[0][0], stride_distr[0][1])
			if stride_distr[0][0] > self.DRAM_page_size:
				if self.prefetch_in_page:
					return ("STRIDE", [False] * (stride_distr[0][1] + 1), stride_miss_pattern)
				else:
					prefetchable = [False] + [bool(p) for p in stride_miss_pattern[1:]]
					return ("STRIDE", prefetchable, stride_miss_pattern)
			else:
				prefetchable = [False] + [bool(p) for p in stride_miss_pattern[1:]]
				return ("STRIDE", prefetchable, stride_miss_pattern)
		else:
			# find strides with biggest reference count
			stride_distr = sorted(stride_distr, key=lambda s: s[1], reverse=True)
			references = sum(ref for _,ref in stride_distr)

			# 1 stride + possible outliers
			# stride is regular, but there outliers (more than 60% of the references should fall under one stride)
			biggest_1 = stride_distr[:1]
			if float(biggest_1[0][1]) / references >= 0.60:
				stride_miss_pattern = [1] + self.calculate_stride_misses(biggest_1[0][0], biggest_1[0][1])
				# check if stride within page boundaries
				if biggest_1[0][0] < self.DRAM_page_size:
					prefetchable = [False]
					prefetchable += [bool(p) for p in stride_miss_pattern[1:]]
				else:
					if self.prefetch_in_page:
						prefetchable = [False] * (references + 1)
					else:
						# big stride, so certainly not within one cache line
						prefetchable = [bool(p) for p in stride_miss_pattern]
				# random strides miss
				stride_miss_pattern += [1] * (references - biggest_1[0][1])
				prefetchable += [False] * (references - biggest_1[0][1])
				return ("STRIDE", prefetchable, stride_miss_pattern)

			# 2 strides + possible outliers
			# stride is regular, but there are 2 strides
			# more than 70% of the references should fall under at most 2 different strides
			biggest_2 = stride_distr[:2]
			biggest_2_refs = sum(ref for _,ref in biggest_2)
			if float(biggest_2_refs) / references >= 0.70:
				stride_miss_pattern = [1]
				prefetchable = [False]
				for stride,ref in biggest_2:
					current_stride_miss_pattern = self.calculate_stride_misses(stride, ref)
					if stride < self.DRAM_page_size:
						prefetchable += [bool(p) for p in current_stride_miss_pattern]
					else:
						if self.prefetch_in_page:
							prefetchable += [False] * ref
						else:
							prefetchable += [bool(p) for p in current_stride_miss_pattern]
					stride_miss_pattern += current_stride_miss_pattern
				# random strides miss
				stride_miss_pattern += [1] * (references - biggest_2_refs)
				prefetchable += [False] * (references - biggest_2_refs)
				return ("STRIDE", prefetchable, stride_miss_pattern)

			# stride is regular, but there are 3 strides
			# more than 80% of the references should fall under at most 3 different strides
			biggest_3 = stride_distr[:3]
			biggest_3_refs = sum(ref for _,ref in biggest_3)
			if float(biggest_3_refs) / references >= 0.80:
				stride_miss_pattern = [1]
				prefetchable = [False]
				for stride,ref in biggest_3:
					current_stride_miss_pattern = self.calculate_stride_misses(stride, ref)
					if stride < self.DRAM_page_size:
						prefetchable += [bool(p) for p in current_stride_miss_pattern]
					else:
						if self.prefetch_in_page:
							prefetchable += [False] * ref
						else:
							prefetchable += [bool(p) for p in current_stride_miss_pattern]
					stride_miss_pattern += current_stride_miss_pattern
				# random strides miss
				stride_miss_pattern += [1] * (references - biggest_3_refs)
				prefetchable += [False] * (references - biggest_3_refs)
				return ("STRIDE", prefetchable, stride_miss_pattern)

			# 4 strides + possible outliers
			# stride is regular, but there are 4 strides
			# more than 90% of the references should fall under at most 4 different strides
			biggest_4 = stride_distr[:4]
			biggest_4_refs = sum(ref for _,ref in biggest_4)
			if float(biggest_4_refs) / references >= 0.90:
				stride_miss_pattern = [1]
				prefetchable = [False]
				for stride,ref in biggest_4:
					current_stride_miss_pattern = self.calculate_stride_misses(stride, ref)
					if stride < self.DRAM_page_size:
						prefetchable += [bool(p) for p in current_stride_miss_pattern]
					else:
						if self.prefetch_in_page:
							prefetchable += [False] * ref
						else:
							prefetchable += [bool(p) for p in current_stride_miss_pattern]
					stride_miss_pattern += current_stride_miss_pattern
				# random strides miss
				stride_miss_pattern += [1] * (references - biggest_4_refs)
				prefetchable += [False] * (references - biggest_4_refs)
				return ("STRIDE", prefetchable, stride_miss_pattern)

			# more strides: stride is completely irregular
			return ("RANDOM_STRIDE", [False] * (references + 1), [1] * (references + 1))

	def expand_distr(self, distr):
		choose_from = []
		for reuse,refs in distr[1:]:
			for r in range(0, refs):
				choose_from.append(reuse)
		random.shuffle(choose_from)

		expanded_distr = [distr[0]]
		for reuse in choose_from:
			expanded_distr.append(expanded_distr[-1] + reuse)

		return expanded_distr

	def estimate_MLP(self, window_instrs, counter, load_dep_distr, pcs_rd_distr, pcs_stride_distr, exclusive_trace_miss_ratios, LLC_PC_miss_ratios, window_loads, trace_counter, cold_miss_distr, miss_ratios):
		# default values
		estimated_MLP, estimated_queuing_delay, succesfully_prefetched = 1, self.bus_transfer_cycles, 0

		if self.mlp_model == "cold":
			# using this method we cannot estimate the efficacy of a stride prefetcher
			estimated_MLP, estimated_queuing_delay = self.estimate_MLP_cold(cold_miss_distr, load_dep_distr, window_instrs, window_loads, miss_ratios, trace_counter)
		elif self.mlp_model == "stride":
			estimated_MLP, estimated_queuing_delay, succesfully_prefetched = self.estimate_MLP_stride(window_instrs, counter, load_dep_distr, pcs_rd_distr, pcs_stride_distr, exclusive_trace_miss_ratios, LLC_PC_miss_ratios, window_loads, trace_counter)
		else:
			# here we estimate the prefetcher to work as good for cold misses as for capacity misses
			estimated_MLP, estimated_queuing_delay, succesfully_prefetched = self.estimate_MLP_cold_stride(window_instrs, counter, load_dep_distr, pcs_rd_distr, pcs_stride_distr, exclusive_trace_miss_ratios, LLC_PC_miss_ratios, window_loads, trace_counter, cold_miss_distr, miss_ratios)

		return estimated_MLP, estimated_queuing_delay, succesfully_prefetched

	def estimate_MLP_cold(self, cold_miss_distr, load_dep_distr, window_instrs, window_loads, miss_ratios, trace_counter, stride_MLP = 0.0):
		total_robs = window_instrs / self.ROB_size
		LLC_miss_chance = miss_ratios[self.config.get_LLC_size()][0]

		if window_loads == 0 or LLC_miss_chance == 0:
			if stride_MLP == 0.0:
				return 1, self.bus_transfer_cycles
			else:
				return 1, self.bus_transfer_cycles, 1

		total_cold_miss_robs, cold_misses = 0, 0.0
		for cm in cold_miss_distr:
			cold_misses += cm[0] * cm[1]
			total_cold_miss_robs += cm[1]

		miss_chance_conflict = (window_loads * LLC_miss_chance - cold_misses) / window_loads
		if miss_chance_conflict < 0:
			miss_chance_conflict = 0

		average_loads_per_ROB = window_loads / total_robs

		# conflict miss MLP
		conflict_miss_MLP = 0
		for loads_on_path,freq in enumerate(load_dep_distr[1:]):
			dependent_MLP = (1 - LLC_miss_chance) ** loads_on_path * miss_chance_conflict * average_loads_per_ROB
			conflict_miss_MLP += freq * dependent_MLP
		conflict_miss_MLP = max(1, conflict_miss_MLP)

		# cold miss MLP
		cold_miss_MLP = 1
		if total_cold_miss_robs != 0:
			for loads_on_path,freq in enumerate(load_dep_distr[1:]):
				dependent_MLP = (1 - LLC_miss_chance) ** loads_on_path * cold_misses / total_cold_miss_robs
				cold_miss_MLP += freq * dependent_MLP

		prev_cs = 0
		exclusive_miss_ratios = {}
		for cs, miss_data in miss_ratios.iteritems():
			exclusive_miss_ratios[cs] = miss_data[0]
			if prev_cs != 0:
				exclusive_miss_ratios[prev_cs] -= miss_data[0]
			prev_cs = cs

		# if no stride_MLP was provided, we are using the pure cold MLP method, use a uniform number for conflict miss MLP
		if stride_MLP == 0.0:
			estimated_MLP = cold_misses / max(cold_misses, window_loads * LLC_miss_chance) * cold_miss_MLP + window_loads * miss_chance_conflict / max(cold_misses, window_loads * LLC_miss_chance) * conflict_miss_MLP

			scaling_factor_MSHR = self.scale_MLP_MSHR(window_loads, exclusive_miss_ratios, estimated_MLP, trace_counter)
			estimated_MLP *= scaling_factor_MSHR

			estimated_queuing_delay = self.estimate_queuing_delay(estimated_MLP)

			return estimated_MLP, estimated_queuing_delay
		else:
			scaling_factor_MSHR = self.scale_MLP_MSHR(window_loads, exclusive_miss_ratios, cold_miss_MLP, trace_counter)
			cold_miss_MLP *= scaling_factor_MSHR

			estimated_MLP = cold_misses / max(cold_misses, window_loads * LLC_miss_chance) * cold_miss_MLP + window_loads * miss_chance_conflict / max(cold_misses, window_loads * LLC_miss_chance) * stride_MLP
			estimated_queuing_delay = self.estimate_queuing_delay(estimated_MLP)

			if window_loads * miss_chance_conflict != 0:
				cold_miss_multiplier = max(cold_misses, window_loads * LLC_miss_chance) / (window_loads * miss_chance_conflict)
			else:
				cold_miss_multiplier = 1.0

			return estimated_MLP, estimated_queuing_delay, cold_miss_multiplier

	def estimate_MLP_stride(self, window_instrs, counter, load_dep_distr, pcs_rd_distr, pcs_stride_distr, exclusive_trace_miss_ratios, LLC_PC_miss_ratios, window_loads, trace_counter):
		if counter[2] == 0 or exclusive_trace_miss_ratios[self.LLC_size] == 0:
			estimated_MLP = self.run_avg_MLP
			estimated_queuing_delay = self.estimate_queuing_delay(self.run_avg_MLP)
			if counter[2] != 0:
				extrapolate_prefetched = float(self.run_avg_prefetched) / counter[2] * window_loads
			else:
				extrapolate_prefetched = self.run_avg_prefetched_extrapolated
			succesfully_prefetched = extrapolate_prefetched

			# should I modify the running averages?
			self.run_avg_MLP = self.alpha * 1 + (1 - self.alpha) * self.run_avg_MLP
			self.run_avg_prefetched = self.alpha * 0 + (1 - self.alpha) * self.run_avg_prefetched
			self.run_avg_prefetched_extrapolated = self.alpha * 0 + (1 - self.alpha) * self.run_avg_prefetched
		else:
			# place loads
			trace_loads, trace_load_addresses = self.place_loads_in_trace(counter[1], pcs_rd_distr, trace_counter)
			# place misses
			trace_misses, statstack_misses = self.place_misses_in_trace(counter[1], pcs_stride_distr, LLC_PC_miss_ratios, pcs_rd_distr, trace_loads, trace_counter)

			sum_trace_misses = sum([tm for tm,p in trace_misses])
			if round(sum_trace_misses) != round(statstack_misses):
				self.debug_printer.save_error_stats("Trace " + str(trace_counter) + ", we placed a different number of misses:\tTM:" + str(round(sum_trace_misses)) + "\tSS: " + str(round(statstack_misses)))
			self.total_ss_misses += statstack_misses

			trace_misses, succesfully_prefetched = self.remove_prefetchable_misses(trace_load_addresses, trace_misses)

			if sum_trace_misses > 0:
				estimated_MLP = self.estimate_MLP_window_stride(trace_loads, trace_misses, load_dep_distr, trace_counter)
				scaling_factor_MSHR = self.scale_MLP_MSHR(sum(trace_loads), exclusive_trace_miss_ratios, estimated_MLP, trace_counter)
				estimated_MLP *= scaling_factor_MSHR
			else:
				estimated_MLP = 1.0

			estimated_queuing_delay = self.estimate_queuing_delay(estimated_MLP)

			extrapolate_prefetched = float(succesfully_prefetched) / counter[2] * window_loads
			self.run_avg_MLP = self.alpha * estimated_MLP + (1 - self.alpha) * self.run_avg_MLP
			self.run_avg_prefetched = self.alpha * succesfully_prefetched + (1 - self.alpha) * self.run_avg_prefetched
			self.run_avg_prefetched_extrapolated = self.alpha * extrapolate_prefetched + (1 - self.alpha) * self.run_avg_prefetched

		return estimated_MLP, estimated_queuing_delay, succesfully_prefetched

	def estimate_MLP_cold_stride(self, window_instrs, counter, load_dep_distr, pcs_rd_distr, pcs_stride_distr, exclusive_trace_miss_ratios, LLC_PC_miss_ratios, window_loads, trace_counter, cold_miss_distr, miss_ratios):
		estimated_MLP_stride, estimated_queuing_delay_stride, succesfully_prefetched_stride = self.estimate_MLP_stride(window_instrs, counter, load_dep_distr, pcs_rd_distr, pcs_stride_distr, exclusive_trace_miss_ratios, LLC_PC_miss_ratios, window_loads, trace_counter)

		estimated_MLP, estimated_queuing_delay, cold_miss_multiplier = self.estimate_MLP_cold(cold_miss_distr, load_dep_distr, window_instrs, window_loads, miss_ratios, trace_counter, estimated_MLP_stride)

		return estimated_MLP, estimated_queuing_delay, int(succesfully_prefetched_stride * cold_miss_multiplier)

	def place_loads_in_trace(self, trace_length, pcs_rd_distr, trace_counter):
		# place loads
		trace_loads = [0] * trace_length
		trace_load_addresses = [0] * trace_length
		load_conflicts = []
		for pc,rd_distr in sorted(pcs_rd_distr.iteritems()):
			expanded_rd_distr = self.expand_distr(rd_distr)
			for rd in expanded_rd_distr:
				if trace_loads[rd] == 0:
					trace_loads[rd] = 1
					trace_load_addresses[rd] = pc
				else:
					load_conflicts.append(pc)

		# Adding load conflicts (due to not knowing the exact position) randomly to the trace_loads array.
		add_random_loads = len(load_conflicts)
		if add_random_loads > 0:
			zero_positions = [x for x,y in enumerate(trace_loads) if y == 0]
			while add_random_loads > 0:
				rnd = int(random.random() * len(zero_positions))
				trace_loads[zero_positions[rnd]] = 1
				trace_load_addresses[zero_positions[rnd]] = load_conflicts[len(load_conflicts) - add_random_loads]
				add_random_loads -= 1
				del zero_positions[rnd]

		if len(load_conflicts) > 0:
			self.debug_printer.save_log_stats("Trace: " + str(trace_counter))
			self.debug_printer.save_log_stats("Placed " + str(len(load_conflicts)) + " loads randomly for a total of " + str(sum(trace_loads)) + " loads! Load PCs were " + str(load_conflicts))

		return trace_loads, trace_load_addresses

	def place_misses_in_trace(self, trace_length, pcs_stride_distr, LLC_PC_miss_ratios, pcs_rd_distr, trace_loads, trace_counter):
		trace_misses = [[0, False]] * trace_length
		no_strides, no_no_strides, no_random_strides = 0, 0, 0
		statstack_misses, randomly_placed_misses = 0, 0
		succesfully_prefetched = 0

		for pc,stride_distr in sorted(pcs_stride_distr.iteritems()):
			# ignore the first entry in the array which is the first address referenced, this might help for prefetching later
			stride_distr = stride_distr[1:]
			stride, prefetchable, stride_misses = self.calculate_misses_PC_stride(stride_distr)

			misses_placed, miss_conflicts, too_few_stride_misses = 0, 0, 0
			PC_statstack_misses = int(round(LLC_PC_miss_ratios[pc][0] * LLC_PC_miss_ratios[pc][1]))
			statstack_misses += PC_statstack_misses

			if stride == "STRIDE":
				# if SS sees misses, the stride we see is for non-repeating addresses, hence every xth cacheline references is a new one and misses
				if PC_statstack_misses > 0:
					rd_distr = self.expand_distr(pcs_rd_distr[pc])
					assert(len(rd_distr) == len(stride_misses))
					assert(LLC_PC_miss_ratios[pc][1] == len(rd_distr))

					# Add all stride misses to the beginning of the stride pattern, this better reflects reality as it will be the first accesses of a repeating strided access pattern that will miss (at least for most benchmarks). Using the miss ratios like for random strides leads to severe underestimations of the MLP.
					miss_ratio = 1
					for i in range(0, len(stride_misses)):
						if stride_misses[i]:
						 	if misses_placed < PC_statstack_misses:
								if trace_misses[rd_distr[i]][0] > 0:
									miss_conflicts += 1
								else:
									trace_misses[rd_distr[i]] = [miss_ratio, prefetchable[i]]
								misses_placed += miss_ratio
							else:
								break

					# Because we append all strides together, it can happen that we're underestimating the actual number of misses (e.g. 2 strides of 8, a random stride, 2 strides of 8, can give more misses than 4 strides of 8 followed by a random: 16-24-32-48-120 results in two misses, while 16-24-120-128-136 results in three misses). This will be noticeable because the number of statstack misses is bigger than the number of misses we get by using the Statstack missrate for the accesses marked as a miss in the stride pattern. Place them randomly afterwards.
					if misses_placed < PC_statstack_misses:
						too_few_stride_misses += PC_statstack_misses - misses_placed

				no_strides += 1
			elif stride == "NO_STRIDE":
				if PC_statstack_misses > 0:
					location_pc = pcs_rd_distr[pc][0]

					miss_ratio = LLC_PC_miss_ratios[pc][0]
					if trace_misses[location_pc][0] > 0:
						if trace_misses[rd_distr[i]][0] < 1 - miss_ratio:
							trace_misses[rd_distr[i]][0] += miss_ratio
						else:
							miss_conflicts += 1
					else:
						trace_misses[location_pc] = [miss_ratio, False]
					misses_placed += miss_ratio

				no_no_strides += 1
			else:
				if PC_statstack_misses > 0:
					rd_distr = self.expand_distr(pcs_rd_distr[pc])
					assert(LLC_PC_miss_ratios[pc][1] == len(rd_distr))

					# We have no idea which of these completely random accesses will actually miss, use the ratio provided by statstack for all possible misses
					miss_ratio = LLC_PC_miss_ratios[pc][0]
					for i in range(0, len(rd_distr)):
						if trace_misses[rd_distr[i]][0] > 0:
							if trace_misses[rd_distr[i]][0] < 1 - miss_ratio:
								trace_misses[rd_distr[i]][0] += miss_ratio
							else:
								miss_conflicts += 1
						else:
							trace_misses[rd_distr[i]] = [miss_ratio, False]
						misses_placed += miss_ratio

				no_random_strides += 1

			# Adding miss conflicts (due to not knowing the exact position) randomly to the trace_misses array (but accordingly to the load array). Do the same for underestimation of the misses due to the usage of a stride distribution (see above)
			add_random_misses = miss_conflicts + too_few_stride_misses
			if add_random_misses > 0:
				randomly_placed_misses += add_random_misses * miss_ratio
				# find positions in trace_misses array where we can still place a miss (value == 0), provided there's a load on that position
				zero_positions = [w for (w,(x,y)),z in zip(enumerate(trace_misses), trace_loads) if x == 0 and z == 1]
				if len(zero_positions) < add_random_misses:
					self.debug_printer.save_error_stats("Trace " + str(trace_counter) + ", we have too few zero positions for adding random misses")
				else:
					while add_random_misses > 0:
						rnd = int(random.random() * len(zero_positions))
						trace_misses[zero_positions[rnd]] = [miss_ratio, False]
						add_random_misses -= 1
						del zero_positions[rnd]

		self.debug_printer.save_log_stats("Number of strided instructions: " + str(no_strides))
		self.debug_printer.save_log_stats("Number of single instructions: " + str(no_no_strides))
		self.debug_printer.save_log_stats("Number of random strided instructions: " + str(no_random_strides))
		self.debug_printer.save_log_stats("Placed " + str(randomly_placed_misses) + " misses randomly for a total of " + str(sum([miss for miss,pref in trace_misses])) + " misses")

		self.total_strides += no_strides
		self.total_no_strides += no_no_strides
		self.total_random_strides += no_random_strides
		self.total_randomly_placed_misses += randomly_placed_misses

		return trace_misses, statstack_misses

	def remove_prefetchable_misses(self, trace_loads_addresses, trace_misses):
		trace_length = len(trace_loads_addresses)

		plain_trace_misses = [0] * trace_length
		# check number of flows
		flows = deque(maxlen=self.prefetcher_flows)
		ind, succesfully_prefetched = 0, 0
		prefetchable = []
		# load address, (missrate, prefetchable)
		for tl, (tm_mr, tm_p) in zip(trace_loads_addresses, trace_misses):
			# can this load be prefetched (depends on prefetch attribute and whether it's still in the observed flows)?
			if tm_mr > 0:
				if not tm_p:
					plain_trace_misses[ind] = tm_mr
				else:
					if tl not in flows:
						plain_trace_misses[ind] = tm_mr
					elif self.prefetcher_enabled:
						assert(tm_mr == 1)
						prefetchable.append(ind)
					else:
						plain_trace_misses[ind] = tm_mr
			# only append flows for loads that at least reach the LLC
			if tm_mr > 0 and tl != 0 and not tl in flows:
				flows.append(tl)
			ind += 1

		# check timeliness, prefetch happens at the same moment as the previous load executed
		# model non-timeliness as lower missrate
		if len(prefetchable) > 0:
			# get boundaries where there's a DRAM access, this marks the potential start of a new ROB
			np_trace_misses = numpy.asarray(trace_misses)
			ROB_indices = numpy.where(np_trace_misses > 0)[0]
			ROB_starts = [ROB_indices[0]]
			for ind in ROB_indices:
				if ind >= ROB_starts[-1] + self.ROB_size:
					ROB_starts.append(ind)
			for ind in prefetchable:
				# prev_load_usage = trace_length - trace_loads_addresses[::-1].index(trace_loads_addresses[ind], trace_length - ind) - 1
				np_trace_loads_addresses = numpy.asarray(trace_loads_addresses)
				load_indices = list(numpy.where(np_trace_loads_addresses == trace_loads_addresses[ind])[0])
				load_indices = load_indices[:load_indices.index(ind)][::-1]
				prev_load_usage = load_indices[-1]
				for li in load_indices:
					if trace_misses[li][1]:
						prev_load_usage = li
						break
				load_ROB = bisect.bisect(ROB_starts, ind) - 1
				prev_load_ROB = bisect.bisect(ROB_starts, prev_load_usage) - 1
				# load that initiated prefetch happened in a previous ROB, prefetch will be done
				# either the ROBs are different or the distance is too big
				# the latter check is needed because the random placement of loads / misses can break the bisect stuff
				if load_ROB != prev_load_ROB or prev_load_usage + self.ROB_size <= ind:
					succesfully_prefetched += 1
				# load that initiated prefetch happened in the same ROB, prefetch will not be done in time, modify missrate
				else:
					# load_to_head = ind - prev_load_usage
					load_to_head = ind - ROB_starts[load_ROB]
					reach_cycles = float(load_to_head) / self.dispatch_width
					fraction_DRAM = reach_cycles / self.DRAM_latency_with_tag
					assert(1.0 - fraction_DRAM >= 0)
					plain_trace_misses[ind] = 1.0 - fraction_DRAM
					succesfully_prefetched += fraction_DRAM

		return plain_trace_misses, succesfully_prefetched

	def estimate_MLP_window_stride(self, trace_loads, trace_misses, load_dep_distr, trace_counter):
		mlp, miss_ROBs, counter = 0, 0, 0
		current_ROB_head = 0
		while current_ROB_head < len(trace_misses):
			# search the trace for the next ROB head (has to start with an LLC miss)
			if sum(trace_misses[current_ROB_head:]) == 0:
				break
			while trace_misses[current_ROB_head] == 0:
				current_ROB_head += 1

			# Take into account load misses depend on each other
			loads = sum(trace_loads[current_ROB_head:current_ROB_head + self.ROB_size])
			load_misses = float(sum(trace_misses[current_ROB_head:current_ROB_head + self.ROB_size]))
			if loads < load_misses:
				self.debug_printer.save_error_stats("Trace: " + str(trace_counter) + ", " + str(loads) + " < " + str(load_misses))
				loads = load_misses
			miss_ratio = load_misses / loads
			# calculate MLP taking into account dependences
			mlp += self.scale_MLP_dependences(load_dep_distr, miss_ratio, load_misses)

			current_ROB_head += self.ROB_size
			miss_ROBs += 1

		estimated_MLP = max(1, float(mlp) / miss_ROBs)

		return estimated_MLP

	def scale_MLP_dependences(self, load_dep_distr, miss_ratio, load_misses):
		estimated_MLP = 0
		for depending_on in range(1, len(load_dep_distr)):
			dependent_MLP = (1 - miss_ratio) ** (depending_on - 1) * load_misses
			estimated_MLP += load_dep_distr[depending_on] * dependent_MLP

		return estimated_MLP

	def scale_MLP_MSHR(self, loads, trace_level_miss_rates, estimated_MLP, trace_counter):
		if estimated_MLP == 0:
			return 1

		mshr_occupancy_time = 0
		cache_level_hits, cache_hit_cost = 0, 0
		for cs in sorted(trace_level_miss_rates.keys())[:-1]:
			cache_level_hits += trace_level_miss_rates[cs] * loads
			mshr_occupancy_time += trace_level_miss_rates[cs] * loads * self.config.get_cache_miss_cost(cs)
			cache_hit_cost += trace_level_miss_rates[cs] * loads * self.config.get_cache_miss_cost(cs)
		if cache_level_hits != 0:
			cache_hit_cost /= cache_level_hits

		scaling_factor_MSHR = 1
		# calculate scaling factor
		if cache_level_hits + estimated_MLP > self.MSHR_entries:
			scaling_factor_MSHR = 0
			self.debug_printer.save_log_stats("Trace: " + str(trace_counter) + ", scaled down MLP due to too many misses live in the ROB (" + str(estimated_MLP)  + ")")
			cache_down, cache_up = math.floor(cache_level_hits), math.ceil(cache_level_hits)
			mlp_down, mlp_up = math.floor(estimated_MLP), math.ceil(estimated_MLP)
			cache_frac, MLP_frac = math.modf(cache_level_hits)[0], math.modf(estimated_MLP)[0]

			if cache_down + mlp_down > self.MSHR_entries:
				scaling_factor_MSHR_down_down = self.calculate_rounded_MSHR_scaling_factor(cache_down, mlp_down, cache_hit_cost)
				scaling_factor_MSHR += (1 - cache_frac) * (1 - MLP_frac) * scaling_factor_MSHR_down_down

			if cache_down + mlp_up > self.MSHR_entries:
				scaling_factor_MSHR_down_up = self.calculate_rounded_MSHR_scaling_factor(cache_down, mlp_up, cache_hit_cost)
				scaling_factor_MSHR += (1 - cache_frac) * MLP_frac * scaling_factor_MSHR_down_up

			if cache_up + mlp_down > self.MSHR_entries:
				scaling_factor_MSHR_up_down = self.calculate_rounded_MSHR_scaling_factor(cache_up, mlp_down, cache_hit_cost)
				scaling_factor_MSHR += cache_frac * (1 - MLP_frac) * scaling_factor_MSHR_up_down

			if cache_up + mlp_up > self.MSHR_entries:
				scaling_factor_MSHR_up_up = self.calculate_rounded_MSHR_scaling_factor(cache_up, mlp_up, cache_hit_cost)
				scaling_factor_MSHR += cache_frac * MLP_frac * scaling_factor_MSHR_up_up

		assert scaling_factor_MSHR <= 1.0

		return scaling_factor_MSHR

	def calculate_rounded_MSHR_scaling_factor(self, rounded_cache_hits, rounded_MLP, cache_hit_cost):
		if rounded_MLP == 0:
			return 0

		events = rounded_cache_hits + rounded_MLP
		slots_filled_LLC = max(self.MSHR_entries - rounded_MLP, 0)
		slots_filled_DRAM = max(self.MSHR_entries - rounded_cache_hits, 0)
		slots_filled = slots_filled_LLC + slots_filled_DRAM
		slots_to_fill = int(self.MSHR_entries - slots_filled)
		P_c = (rounded_cache_hits - max(self.MSHR_entries - rounded_MLP, 0)) / (events - slots_filled)
		P_DRAM = (rounded_MLP - max(self.MSHR_entries - rounded_cache_hits, 0)) / (events - slots_filled)

		assert P_c + P_DRAM == 1.0

		MLP = 0.0
		for i in range(0, slots_to_fill + 1):
			multiplier = math.factorial(slots_to_fill) / (math.factorial(i) * math.factorial(slots_to_fill - i))
			chance = P_c ** i * P_DRAM ** (slots_to_fill - i)
			state_chance = multiplier * chance
			T_MSHR_free = ((slots_filled_LLC + i) * cache_hit_cost + (slots_filled_DRAM + slots_to_fill - i) * self.LLC_miss_cost) / self.MSHR_entries - self.MSHR_entries / events * self.ROB_size / self.dispatch_width
			# if events resolve faster than the time it takes to get to the next event, this time will be negative
			T_MSHR_free = max(0, T_MSHR_free)
			DRAM_MSHR = self.MSHR_entries - (max(self.MSHR_entries - rounded_MLP, 0) + i)
			MLP += state_chance * (DRAM_MSHR + (rounded_MLP - DRAM_MSHR) * (self.LLC_miss_cost - T_MSHR_free) / self.LLC_miss_cost)

		scaling_factor_MSHR = MLP / rounded_MLP

		return scaling_factor_MSHR

	def estimate_queuing_delay(self, mlp):
		if self.queue_model == "MLP":
			queue_delay_down, queue_delay_up = 0.0, 0.0
			mlp_down, mlp_up = int(mlp), int(mlp) + 1
			for m in range(0, mlp_down):
				queue_delay_down += self.bus_transfer_cycles * (m + 1) -  min(self.bus_transfer_cycles * m, self.ROB_size / mlp_down / self.dispatch_width * m)
			for m in range(0, mlp_up):
				queue_delay_up += self.bus_transfer_cycles * (m + 1) -  min(self.bus_transfer_cycles * m, self.ROB_size / mlp_up / self.dispatch_width * m)
			fract_mlp = math.modf(mlp)[0]
			queue_delay = (1 - fract_mlp) * queue_delay_down + fract_mlp * queue_delay_up

			return queue_delay / mlp
		else:
		 	return 0.0

	def get_overall_stats(self):
		return self.total_strides, self.total_no_strides, self.total_random_strides, self.total_randomly_placed_misses, self.total_ss_misses
