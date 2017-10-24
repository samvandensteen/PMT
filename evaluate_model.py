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

import os, getopt, sys, pdb, time, datetime, random, shutil, signal, subprocess
from in_out import Config, Constants, Data_Reader, Debug_Printer, Progress_Printer, Results_Printer
from models import Statstack, Base_Model, Branch_Model, Cache_Model, MLP_Model
from multiprocessing import Pool, Lock

#########################################
#			helper funtions				#
#########################################

def usage():
	print "./evaluate_model.py <-i | --input> <-o | --output> <-b | --benchmarks> [-c | --config] [-m | --mlp] [-p | --parallel] [-a | --argument] [--statstack] [--queuing] [--prefetch] [--cpi-stack]"
	print "-i | --input directory with data to calculate the model\n\tDEFAULT: current directory"
	print "-o | --output directory to put result files\n\tDEFAULT: current directory"
	print "-b | --benchmarks benchmarks for which to calculate the model\n\tDEFAULT: all spec train benchmarks (all inputs)"
	print "-c | --config processor configuration\n\tDEFAULT: config/nehalem.cfg"
	print "-m | --mlp choose which mlp algorithm to use\n\tvalid arguments: cold, stride, cold_stride\n\tDEFAULT: stride"
	print "-p | --parallel number of parallel threads allowed to calculate multiple benchmarks at the same time\n\tDEFAULT: 1"
	print "-a | --argument modify specific parameters from the processor configuration file\n\tEXAMPLE: -a L3/size=4194304"
	print "--statstack specify which statstack algorithm to use\n\toptions:old (fast, less accurate), new (slow, more accurate)\n\tDEFAULT: new"
	print "--queuing use a simple queuing model based on the MLP\n\toptions: MLP, None\n\tDEFAULT: MLP"
	print "--prefetch use stride prefetcher to eliminate some misses\n\tDEFAULT: disabled (no argument needed, using the flag => prefetcher enabled)"
	print "--cpi-stack plot a CPI stack using the model predictions\n\tRequires installation of python-matplotlib"
	print "Example:"
	print "./evaluate_model.py -c config/nehalem.cfg -i ~/profiled -o test -b gcc --mlp stride --statstack new -p 1 --cpi-stack"

def signal_handler():
	signal.signal(signal.SIGINT, signal.SIG_IGN)

def set_completed(result):
	global lock
	lock.acquire()
	global completed
	completed += 1
	lock.release()

def parse_command_line(constants):
	try:
		opts, args = getopt.getopt(sys.argv[1:], "c:i:o:b:m:s:p:a:h", ['config=', 'input=', 'output=', 'benchmarks=', 'mlp=', 'statstack=', 'parallel=', 'argument=', 'queuing', 'prefetch', 'cpi-stack', 'help'])
	except getopt.GetoptError, e:
		# print help information and exit:
		print e
		usage()

	for o, a in opts:
		if o in ("-c", "--config"):
			constants.processor_config = a
		elif o in ("-i", "--input"):
			constants.input_dir = os.path.abspath(os.path.join(constants.top_level_dir, a))
		elif o in ("-o", "--output"):
			constants.output_dir = os.path.abspath(os.path.join(constants.top_level_dir, a))
		elif o in ("-b", "--benchmarks"):
			constants.benchmarks = a.split(",")
		elif o in ("-m", "--mlp"):
			valid = ("cold", "stride", "cold_stride")
			if a not in valid:
				print "Not a valid value for the option mlp! Values can be " + str(valid)
				sys.exit(1)
			constants.mlp_model = a
		elif o in ("-s", "--statstack"):
			valid = ("old", "new")
			if a not in valid:
				print "Not a valid value for the option statstack! Values can be " + str(valid)
				sys.exit(1)
			constants.statstack = a
		elif o in ("-p", "--parallel"):
			constants.parallel = int(a)
		elif o in ("-a", "--argument"):
			# format is always:
			# structure/parameter=value
			structure = a.split('/')[0]
			parameter_value = a.split('/')[1]
			if not structure in constants.overwrite_config_parameters:
				constants.overwrite_config_parameters[structure] = {}
			constants.overwrite_config_parameters[structure][parameter_value.split("=")[0]] = parameter_value.split("=")[1]
		elif o in ("--queuing"):
			valid = ("MLP", "None")
			if a not in valid:
				print "Not a valid value for the option queuing! Values can be " + str(valid)
				sys.exit(1)
			constants.queue_model = a
		elif o in ("--prefetch"):
			constants.prefetch = True
		elif o in ("--cpi-stack"):
			constants.cpi_stack = True
		elif o in ("-h", "--help"):
			usage()
			sys.exit(0)

def make_results_dirs(constants):
	if not os.path.exists(constants.output_dir):
	    os.makedirs(constants.output_dir)
	else:
	    var = raw_input("Results directory exists, do you want to overwrite the results (y/n)? ")
	    if var == "y" or var == "Y" or var == "yes" or var == "YES":
	        for root,dirs,files in os.walk(constants.output_dir):
	            for f in files:
	                os.unlink(os.path.join(root, f))
	        for root,dirs,files in os.walk(constants.output_dir, topdown=False):
	            for d in dirs:
	                os.rmdir(os.path.join(root, d))
	    else:
	        print "Appending timestamp to leaf directory!"
	        ts = datetime.datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d_%H-%M-%S")
	        constants.output_dir = constants.output_dir + "_" + ts
	        os.makedirs(constants.output_dir)
	        print "Results directory is now " + constants.output_dir

def save_execution_information(constants):
	f = open(os.path.join(constants.output_dir, "exec.nfo"), "w+")

	# time
	ts = datetime.datetime.fromtimestamp(time.time()).strftime("%H-%M-%S %d-%m-%Y")
	f.write("Results generated at " + str(ts) + "\n")
	f.write("Complete command: " + " ".join(sys.argv[:]) + "\n")

	# git id (if git repo)
	f.write("Analysis info:\n")

	# path to scripts
	f.write("\tpath to PMT: " + str(os.getcwd()) + "\n")

	p = subprocess.Popen("git log --format=\"%H\" -n 1", shell = True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, err = p.communicate()
	f.write("\tgit id PMT: " + str(out) + "\n")

	if os.path.exists(os.path.join(constants.input_dir, "exec.nfo")):
		f_log = open(os.path.join(constants.input_dir, "exec.nfo"), "r")
		git_id_data = f_log.readlines()
		f_log.close()
		for line in git_id_data:
			if line.startswith("\tgit id"):
				f.write("\tgit id profiler: " + line.split(":")[1].strip() + "\n")

	# machine information (hostname, python version)
	f.write("Machine information:\n")

	p = subprocess.Popen("hostname", shell = True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, err = p.communicate()
	f.write("\thostname: " + str(out))

	f.write("\tpython version: " + str(sys.version).split()[0] + "\n")

	f.close()

def calculate_model(benchmark, constants, config):
	random.seed(0)

	cache_sizes = config.get_cache_sizes()
	cacheline_size = config.get_cacheline_size()
	ROB_size = config.get_ROB_size()
	physical_dispatch_width = config.get_dispatch_width()

	input_root = os.path.join(constants.input_dir, benchmark)
	data_reader = Data_Reader(input_root, config)

	base_model = Base_Model(constants, config, benchmark)
	cache_model = Cache_Model(constants, config, benchmark)
	branch_model = Branch_Model(constants, config, benchmark)
	mlp_model = MLP_Model(constants, config, benchmark)

	profiler_metadata, phase_bounds, window_bounds = data_reader.get_log_contents()

	# setup progress printer to log file
	progress_printer = Progress_Printer(len(window_bounds), log_file=os.path.join(constants.output_dir, benchmark, "log.out"))

	# execute statstack per benchmark
	# def __init__(self, input_root, benchmark, base_name, ss_version, _type, content)
	progress_printer.print_message("Executing preliminary Statstack work:")
	ss_data_load = Statstack(constants, benchmark, "data", "new", "sample", "data", profiler_metadata, progress_printer)
	ss_data_store = Statstack(constants, benchmark, "data", "new", "sample", "data", profiler_metadata, progress_printer)
	ss_trace = Statstack(constants, benchmark, "trace", "new", "trace", "data", profiler_metadata, progress_printer)
	ss_instr = Statstack(constants, benchmark, "instr", "new", "sample", "instr", profiler_metadata, progress_printer)
	ss_data_load_aligned_bursts = ss_data_load.align_bursts_windows(window_bounds)
	ss_data_store_aligned_bursts = ss_data_store.align_bursts_windows(window_bounds)
	ss_instr_aligned_bursts = ss_instr.align_bursts_windows(window_bounds)

	# make data structures
	global_D_eff, global_stats = [], []
	global_MLP, global_queuing_delay, global_prefetched, global_cache_misses, global_LLC_load_misses, global_trace_misses, global_DRAM = [], [], [], [], [], [], []
	global_base_component, global_dependence_component, global_port_component, global_unit_component, global_branch_component, global_I_cache_component, global_LLC_chain_component, global_DRAM_component, global_cycles, global_instructions, global_micro_ops = 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
	window_base_component, window_dependence_component, window_port_component, window_unit_component, window_branch_component, window_I_cache_component, window_LLC_chain_component, window_DRAM_component, window_window_cycles, window_instructions, window_micro_ops = [], [], [], [], [], [], [], [], [], [], []

	# loop over windows
	trace_counter = 0
	progress_printer.setup_progressbar(message = "\nCalculating model:")
	for window_instr, data_load_bursts, data_store_bursts, instr_bursts in zip(window_bounds, ss_data_load_aligned_bursts, ss_data_store_aligned_bursts, ss_instr_aligned_bursts):
		progress_printer.print_progress(trace_counter)

		# statstack, get stack distance histograms
		load_sd_hist = ss_data_load.get_sd_hists(_type='r', bursts = data_load_bursts)
		store_sd_hist = ss_data_store.get_sd_hists(_type='w', bursts = data_store_bursts)
		trace_sd_hist = ss_trace.get_sd_hists(_type='r', bursts = [trace_counter])
		instr_sd_hist = ss_instr.get_sd_hists(_type='r', bursts = instr_bursts)

		# transform sd hists to miss rates
		load_miss_ratios = ss_data_load.calculate_sample_miss_ratios(cache_sizes, load_sd_hist, cacheline_size)
		store_miss_ratios = ss_data_store.calculate_sample_miss_ratios(cache_sizes, store_sd_hist, cacheline_size)

		# interpolating load and store miss rates
		interpolated_load_miss_ratios = ss_data_load.interpolate_miss_ratios(window_instr, data_load_bursts, load_miss_ratios)
		interpolated_store_miss_ratios = ss_data_store.interpolate_miss_ratios(window_instr, data_store_bursts, store_miss_ratios)

		# trace_load_miss_ratios should already be aligned with the window boundaries of our instruction based samplers
		trace_load_miss_ratios = ss_trace.calculate_PC_miss_ratios(cache_sizes, trace_sd_hist, cacheline_size)

		# calculate instruction miss ratios
		instr_miss_ratios = ss_instr.calculate_sample_miss_ratios(cache_sizes, instr_sd_hist, cacheline_size)
		interpolated_instr_miss_ratios = ss_instr.interpolate_miss_ratios(window_instr, instr_bursts, instr_miss_ratios)

		# calculate the number DRAM accesses
		LLC_load_misses = interpolated_load_miss_ratios[config.get_LLC_size()][0] * interpolated_load_miss_ratios[config.get_LLC_size()][1]
		global_LLC_load_misses.append(LLC_load_misses)

		# calculate the overall number of cache accesses
		global_cache_misses.append([])
		for cache_size,lmr in sorted(interpolated_load_miss_ratios.iteritems(), key = lambda x: x[0]):
			global_cache_misses[-1].append(lmr[0] * lmr[1])
		for cache_size,smr in sorted(interpolated_store_miss_ratios.iteritems(), key = lambda x: x[0]):
			global_cache_misses[-1].append(smr[0] * smr[1])
		for cache_size,imr in sorted(interpolated_instr_miss_ratios.iteritems(), key = lambda x: x[0]):
			global_cache_misses[-1].append(imr[0] * imr[1])

		# calculate misses per level (but exclude misses that also miss in a lower level)
		exclusive_trace_miss_ratios, sum_loads = ss_trace.calculate_exclusive_miss_ratios(trace_load_miss_ratios)
		global_trace_misses.append(exclusive_trace_miss_ratios[config.get_LLC_size()] * sum_loads[config.get_LLC_size()])

		#############################
		# calculate cache component	#
		#############################
		# gather necessary variables
		L1D_load_hits = ss_data_load.interpolate_L1_hits(window_instr, data_load_bursts, load_miss_ratios[cache_sizes[0]])
		L1D_store_hits = ss_data_store.interpolate_L1_hits(window_instr, data_store_bursts, store_miss_ratios[cache_sizes[0]])
		load_misses, store_misses, instr_misses = {}, {}, {}
		for cache_size in cache_sizes:
			load_misses[cache_size] = interpolated_load_miss_ratios[cache_size][0] * interpolated_load_miss_ratios[cache_size][1]
			store_misses[cache_size] = interpolated_store_miss_ratios[cache_size][0] * interpolated_store_miss_ratios[cache_size][1]
			instr_misses[cache_size] = interpolated_instr_miss_ratios[cache_size][0] * interpolated_instr_miss_ratios[cache_size][1]
		cache_model.set_window_stats(L1D_load_hits, L1D_store_hits, load_misses, store_misses, instr_misses)

		# calculate I-cache component
		I_cache_component = cache_model.calculate_instruction_miss_penalty()

		############################
		# calculate base component #
		############################
		stats, dependences, uop_hist = data_reader.read_next_utrace()

		window_sample_rate = float(profiler_metadata["trace_window"]) / stats[0]
		micro_ops = stats[1] * window_sample_rate

		base_model.set_window_stats(stats, dependences, uop_hist, int(profiler_metadata["trace_window"]), cache_model.get_load_latency())
		base_model.calculate_base_performance()

		# calculate base component
		base_component,dependence_component,port_component,unit_component = base_model.calculate_base_component()

		##############################
		# calculate branch component #
		##############################
		entropy = data_reader.read_next_entropy_window()

		# calculate branch misses based on entropy
		branch_model.estimate_branch_misses(entropy)

		# gather variables needed to calculate the branch resolution time
		trace_uops = sum(uop_hist.values())
		average_instruction_latency = base_model.get_average_instruction_latency()
		path_lengths = base_model.get_path_lengths()
		independent_instructions = base_model.get_independent_instructions()

		# instruction trace can vary in length (e.g. not enough loads were see), window cannot
		branch_model.estimate_branch_resolution_time(trace_uops, average_instruction_latency, path_lengths, independent_instructions, window_sample_rate)

		# calculate branch component
		branch_component = branch_model.calculate_branch_component()

		######################################
		# calculate DRAM component using MLP #
		######################################
		# get MLP data for next window
		load_dependences, pcs_rds, pcs_strides = data_reader.read_next_MLP_window()
		cold_miss_distr = data_reader.read_next_cold_window()
		window_instr = window_instr[1] - window_instr[0]
		window_loads = interpolated_load_miss_ratios[config.get_LLC_size()][1]
		LLC_trace_miss_ratio = trace_load_miss_ratios[config.get_LLC_size()]

		# calculate MLP, queuing delay and prefetchable misses
		current_MLP, current_queue_delay, current_prefetched = mlp_model.estimate_MLP(window_instr, stats, load_dependences, pcs_rds, pcs_strides, exclusive_trace_miss_ratios, LLC_trace_miss_ratio, window_loads, trace_counter, cold_miss_distr, interpolated_load_miss_ratios)
		current_prefetched *= window_sample_rate

		# subtract prefetched misses since they won't cause an extra delay
		LLC_load_misses -= min(LLC_load_misses, current_prefetched)
		DRAM_component = LLC_load_misses / current_MLP * (config.get_DRAM_latency_with_tag() + current_queue_delay)

		# save a couple of numbers to write to files
		global_MLP.append(current_MLP)
		global_queuing_delay.append(current_queue_delay)
		global_prefetched.append(current_prefetched)
		global_DRAM.append(LLC_load_misses / current_MLP * (config.get_DRAM_latency_with_tag() + current_queue_delay))

		#################################
		# calculate LLC chain component #
		#################################
		D_eff = base_model.get_effective_dispatch_rates()
		# ignore the effective dispatch rate caused by dependencies since this is similar, do take into account lower dispatch rates due to issue stage contention
		LLC_chain_penalty = cache_model.estimate_LLC_penalty(min(D_eff.values()), path_lengths[ROB_size], load_dependences, trace_uops, window_sample_rate)

		#####################################
		# calculate window execution cycles #
		#####################################
		window_cycles = base_component + dependence_component + port_component + unit_component + branch_component + I_cache_component + LLC_chain_penalty + DRAM_component

		# add to global counters
		global_base_component += base_component
		global_dependence_component += dependence_component
		global_port_component += port_component
		global_unit_component += unit_component
		global_branch_component += branch_component
		global_I_cache_component += I_cache_component
		global_LLC_chain_component += LLC_chain_penalty
		global_DRAM_component += DRAM_component
		global_cycles += window_cycles
		global_instructions += window_instr
		global_micro_ops += micro_ops

		# save per window counters
		window_base_component.append(base_component)
		window_dependence_component.append(dependence_component)
		window_port_component.append(port_component)
		window_unit_component.append(unit_component)
		window_branch_component.append(branch_component)
		window_I_cache_component.append(I_cache_component)
		window_LLC_chain_component.append(LLC_chain_penalty)
		window_DRAM_component.append(DRAM_component)
		window_window_cycles.append(window_cycles)
		window_instructions.append(window_instr)
		window_micro_ops.append(micro_ops)

		global_D_eff.append(D_eff)

		trace_counter += 1

	global_strides, global_no_strides, global_random_strides, global_randomly_placed_misses, global_ss_misses = mlp_model.get_overall_stats()

	results_printer = Results_Printer(constants.input_dir, constants.output_dir, benchmark)

	# print cache miss debug stats
	debug_statstack_printer = Debug_Printer(constants.output_dir, benchmark, "debug_statstack")
	# create labels
	cache_labels = []
	for cache_size,lmr in sorted(interpolated_load_miss_ratios.iteritems(), key = lambda x: x[0]):
		cache_labels.append("Load " + str(cache_size / 1024) + "k")
	for cache_size,smr in sorted(interpolated_store_miss_ratios.iteritems(), key = lambda x: x[0]):
		cache_labels.append("Store " + str(cache_size / 1024) + "k")
	for cache_size,imr in sorted(interpolated_instr_miss_ratios.iteritems(), key = lambda x: x[0]):
		cache_labels.append("Instr " + str(cache_size / 1024) + "k")
	debug_string = "S" + "-S" * (len(cache_labels) - 1)
	debug_statstack_printer.save_debug_stats(cache_labels, global_cache_misses, debug_string)

	# print mlp debug stats
	debug_mlp_printer = Debug_Printer(constants.output_dir, benchmark, "debug_mlp")
	debug_string = "S-WA-S-S"
	debug_mlp_printer.save_debug_stats(["LLC load misses", "MLP", "prefetched", "queuing delay", "DRAM"], zip(global_LLC_load_misses, global_MLP, global_prefetched, global_queuing_delay, global_DRAM), debug_string)

	keys = ["Base", "Dependence", "Port", "Unit", "Branch", "I-cache", "LLC-chain", "DRAM", "Total", "Instructions", "Micro-Ops"]
	values = zip(window_base_component, window_dependence_component, window_port_component, window_unit_component, window_branch_component, window_I_cache_component, window_LLC_chain_component, window_DRAM_component, window_window_cycles, window_instructions, window_micro_ops)
	results_printer.save_window_stats(keys, values)

	values = [global_base_component, global_dependence_component, global_port_component, global_unit_component, global_branch_component, global_I_cache_component, global_LLC_chain_component, global_DRAM_component, global_cycles, global_instructions, global_micro_ops]
	results_printer.save_results(keys, values)

	results_printer.plot_cpi_stack(keys[:-3], [v / global_instructions for v in values[:-3]])

	progress_printer.close_log_file()

def main():
	global lock, completed

	# Make sure that we are operating in the directory of this file.
	os.chdir(os.path.dirname(os.path.abspath(__file__)))

	constants = Constants()
	constants.top_level_dir = os.getcwd()
	parse_command_line(constants)

	make_results_dirs(constants)
	save_execution_information(constants)

	config = Config(constants.processor_config, constants.overwrite_config_parameters, constants.output_dir)

	# no benchmarks were supplied, use all subdirectories in the input directory
	if constants.benchmarks == []:
		constants.benchmarks = os.listdir(constants.input_dir)
		# do ignore the sd_hists_new and sd_hist_old dir
		if "sd_hists_new" in constants.benchmarks:
			constants.benchmarks.remove("sd_hists_new")
		if "sd_hists_old" in constants.benchmarks:
			constants.benchmarks.remove("sd_hists_old")
		constants.benchmarks = sorted(constants.benchmarks, key=lambda s: s.lower())

	# NON-PARALLEL
	if constants.parallel == 1:
		for benchmark in constants.benchmarks:
			calculate_model(benchmark, constants, config)
	# PARALLEL
	else:
		lock = Lock()
		lock.acquire()
		completed = 0
		lock.release()

		process_pool = Pool(constants.parallel, signal_handler)
		for benchmark in constants.benchmarks:
			process_pool.apply_async(calculate_model, args=(benchmark, constants, config), callback=set_completed)

		try:
			while completed < len(constants.benchmarks):
				time.sleep(10)
		except KeyboardInterrupt:
			# forced termination
			print "\nKilling processes and cleaning up working directories!"

			process_pool.terminate()
			process_pool.join()

			shutil.rmtree(constants.output_dir)

			print ""

			sys.exit(1)
		else:
			# normal termination
			process_pool.close()
			process_pool.join()

if __name__ == '__main__':
	main()
