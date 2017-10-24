This is the Processor Modeling Tool.

Dependencies:
	Google Protobuf 3.0
	Python 2.x

Build:
	./build_tool (point to profiler_root which contains the necessary proto files)

Run:
	./evaluate_bandwidth.py -h
	./evaluate_model.py <-i | --input> <-o | --output> <-b | --benchmarks> [-c | --config] [-m | --mlp] [-p | --parallel] [-a | --argument] [--statstack] [--queuing] [--prefetch] [--cpi-stack]

Contact:
	sam.vandensteen@ugent.be
