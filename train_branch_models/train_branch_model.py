#!/usr/bin/python

import os, sys, subprocess, time, pdb
from optparse import OptionParser
import numpy as np

sys.path.insert(0, os.path.abspath(".."))
import aif_lib.stream_reader

def create_entropy_generator(root_dir, compressed):
	entropy_files = []
	for root,dirs,files in os.walk(root_dir):
		for f in files:
			if "entropy." in f:
				entropy_files.append(os.path.join(root, f))

	entropy_reader = aif_lib.stream_reader.Stream_Reader(entropy_files, "BRANCH", compressed)

	entropy_generator = entropy_reader.iter_in_place()

	return entropy_generator

def read_entropy(entropy_generator, entropy_type, IP_bits, BHR_size):
	entropy_window = next(entropy_generator)

	# we have to check up to three different windows, because the local, global and tour window are saved subsequently
	if entropy_window.type != entropy_type:
		entropy_window = next(entropy_generator)
		if entropy_window.type != entropy_type:
			entropy_window = next(entropy_generator)

	branches = entropy_window.branches

	if entropy_window.type != entropy_type:
		print "Needed entropy type was not found in file!"
		sys.exit(2)

	for ip in entropy_window.ips:
		if ip.bits == IP_bits:
			for bhr,entropy in zip(ip.bhr_bits, ip.entropy):
				if bhr == BHR_size:
					return (entropy, branches)
			# if we execute the following lines of code, something went wrong
			print "Required BHR size not found in entropy files, you need to reprofile for a BHR up to " + str(BHR_size) + "!"
			sys.exit(3)
		else:
			continue

	# if we execute the following lines of code, something went wrong
	print "Required IP bits not found in entropy files, you need to reprofile for IP bits up to " + str(IP_bits) + "!"
	sys.exit(4)

def read_missrate_file(options):
	# read missrate
	f = open(options.missrates_file, "r")
	missrate_lines = f.readlines()
	f.close()

	missrates = {}
	for line in missrate_lines:
		if len(line) > 1:
			if line.startswith("Benchmark"):
				missrates[line.split(":")[1].strip()] = []
				benchmark = line.split(":")[1].strip()
			elif line.startswith("Type (l,g,t)"):
				missrates[benchmark].append(line.split(":")[1].strip())
			elif line.startswith("IP (bits)"):
				missrates[benchmark].append(int(line.split(":")[1]))
			elif line.startswith("BHR (bits)"):
				missrates[benchmark].append(int(line.split(":")[1]))
			elif line.startswith("Missrate (%)"):
				missrates[benchmark].append(float(line.split(":")[1]))

	return missrates

def check_input(options, missrate_benchmarks):
	# check if results and missrate root are aligned in terms of contained benchmarks
	valid_results_benchmark = []
	for d in os.listdir(options.results_root):
		if os.path.exists(os.path.join(options.results_root, d, "entropy.0")):
			valid_results_benchmark.append(d)

	if set(valid_results_benchmark) != set(missrate_benchmarks):
		print "The lists of valid benchmarks in the results root and missrates root are not the same: " + str(list(set(valid_results_benchmark).symmetric_difference(set(missrate_benchmarks))))
		print "Check both directories and rerun this tool!"
		sys.exit(1)

def main():
	parser = OptionParser()

	parser.add_option("-r", "--results", action="store", dest="results_root", help="Specify the root directory for the entropy files.")
	parser.add_option("-m", "--missrates", action="store", dest="missrates_file", help="Specify the file containing missrates per benchmark specified in results_root.")
	parser.add_option("-c", "--compressed", action="store", dest="compressed", help="Specify whether the entropy files were compressed.", type="int", default=True)

	(options, args) = parser.parse_args()

	if not options.results_root or not options.missrates_file:
	    parser.error("All available options need to be specified")

	missrates = read_missrate_file(options)
	check_input(options, missrates.keys())

	entropy_arr, missrate_arr = [], []
	for benchmark in os.listdir(options.results_root):
		if os.path.exists(os.path.join(options.results_root, benchmark, "entropy.0")):
			# read entropy
			missrate = missrates[benchmark]

			root_dir = os.path.join(options.results_root, benchmark)
			entropy_generator = create_entropy_generator(root_dir, bool(options.compressed))

			benchmark_entropy = []
			while True:
				try:
					# missrate[0] -> type, missrate[1] -> IP bits, missrate[2] -> BHR
					entropy, branches = read_entropy(entropy_generator, missrate[0], missrate[1], missrate[2])
					benchmark_entropy.append((entropy, branches))
				except StopIteration:
					break

			# calculate average entropy
			avg_entropy, total_branches = 0, 0
			for entropy, branch in benchmark_entropy:
				avg_entropy += entropy * branch
				total_branches += branch
			avg_entropy /= total_branches

			entropy_arr.append(avg_entropy)
			missrate_arr.append(missrate[3])

	a, b = np.polyfit(entropy_arr, missrate_arr, 1)

	print str(a) + "\t" + str(b)

if __name__ == "__main__":
	main()
