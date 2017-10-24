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

class Base_Model:
    def __init__(self, constants, config, benchmark):
        self.config = config
        self.ROB_size = config.get_ROB_size()
        self.physical_dispatch_width = config.get_dispatch_width()

        self.output_dir = constants.output_dir
        self.debug_printer = Debug_Printer(self.output_dir, benchmark, "debug_base")

        self.build_issue_stage()

    def build_issue_stage(self):
        self.instruction_latencies = {}
        for k,v in self.config.get_instruction_latencies().iteritems():
            self.instruction_latencies[k] = int(v)

        self.functional_units_per_port = {}
        self.available_ports_split = []
        for k,v in self.config.get_functional_units_ports().iteritems():
            if not k in self.functional_units_per_port:
                self.functional_units_per_port[k] = []
                for port in v.replace(" ", "").split("|"):
                    self.functional_units_per_port[k].append(port.replace(" ", "").split("&"))
                    for p in port.replace(" ", "").split("&"):
                        if not p in self.available_ports_split:
                            self.available_ports_split.append(p)
        self.available_ports_split = sorted(self.available_ports_split)

        self.functional_units_pipelined = {}
        for k,v in self.config.get_functional_unit_pipelined().iteritems():
            if v == "1":
                self.functional_units_pipelined[k] = True
            else:
                self.functional_units_pipelined[k] = False

        self.instruction_per_functional_unit = {}
        for k,v in self.config.get_instruction_functional_unit().iteritems():
            self.instruction_per_functional_unit[k] = v.replace(" ", "").split("|")

        self.instruction_per_port = {}
        for ins,functional_units in self.instruction_per_functional_unit.iteritems():
            self.instruction_per_port[ins] = []
            for fu_outer in functional_units:
                for fu_inner,ports in self.functional_units_per_port.items():
                    if fu_inner == fu_outer:
                        for port in ports:
                            self.instruction_per_port[ins].append(port)

    def set_window_stats(self, stats, dependences, uop_hist, window_instruction_length, load_latency):
        self.stats = stats
        self.dependences = dependences
        self.uop_hist = uop_hist
        self.micro_op_count = sum(self.uop_hist.itervalues())
        self.window_instruction_length = window_instruction_length
        # set this value calculated by using StatStack miss rate
        self.instruction_latencies["LOAD"] = load_latency

    def calculate_base_performance(self):
        self.interpolate_dependences()
        self.calculate_average_instruction_latency()
        self.calculate_independent_instructions()
        self.calculate_base_execution_rate()

    def calculate_independent_instructions(self):
        self.independent_instructions = {}
        # use critical path
        for rob, paths in self.interpolated_dependences.iteritems():
            CP_latency = paths[2] * self.average_instruction_latency
            self.independent_instructions[rob] = float(rob) / CP_latency

    def calculate_average_instruction_latency(self):
        self.average_instruction_latency = 0.0
        for uop,freq in self.uop_hist.iteritems():
            self.average_instruction_latency += float(freq) * self.instruction_latencies[uop]
        self.average_instruction_latency /= self.micro_op_count

    def interpolate_dependences(self):
        self.interpolated_dependences = {}
        # logarithmic fit ( a + b * ln(x) ) yields the best results compared to the real profiled results (but only if you fit point by point, not over all measurements)
        # initialize for the first profiled ROB (always = 1)
        self.interpolated_dependences[self.dependences[0][0]] = (self.dependences[0][1], self.dependences[0][2], self.dependences[0][3])
        # interpolate between profiled ROBs, initialize previous on smallest ROB profiled
        previous = self.dependences[0]
        for dep in self.dependences[1:]:
            y1_AP, y2_AP, x1, x2 = previous[1], dep[1], previous[0], dep[0]
            b_AP = (2 * (y1_AP * math.log(x1) + y2_AP * math.log(x2)) - (y1_AP + y2_AP) * (math.log(x1) + math.log(x2))) / (2 * (math.log(x1) ** 2 + math.log(x2) ** 2) - (math.log(x1) + math.log(x2)) ** 2)
            a_AP = (y1_AP + y2_AP - b_AP * (math.log(x1) + math.log(x2))) / 2

            y1_ABP, y2_ABP = previous[2], dep[2]
            b_ABP = (2 * (y1_ABP * math.log(x1) + y2_ABP * math.log(x2)) - (y1_ABP + y2_ABP) * (math.log(x1) + math.log(x2))) / (2 * (math.log(x1) ** 2 + math.log(x2) ** 2) - (math.log(x1) + math.log(x2)) ** 2)
            a_ABP = (y1_ABP + y2_ABP - b_ABP * (math.log(x1) + math.log(x2))) / 2

            y1_CP, y2_CP = previous[3], dep[3]
            b_CP = (2 * (y1_CP * math.log(x1) + y2_CP * math.log(x2)) - (y1_CP + y2_CP) * (math.log(x1) + math.log(x2))) / (2 * (math.log(x1) ** 2 + math.log(x2) ** 2) - (math.log(x1) + math.log(x2)) ** 2)
            a_CP = (y1_CP + y2_CP - b_CP * (math.log(x1) + math.log(x2))) / 2

            for r in range(previous[0] + 1, dep[0]):
                interp_AP = a_AP + b_AP * math.log(r)
                interp_ABP = a_ABP + b_ABP * math.log(r)
                interp_CP = a_CP + b_CP * math.log(r)
                self.interpolated_dependences[r] = (interp_AP, interp_ABP, interp_CP)

            self.interpolated_dependences[dep[0]] = (dep[1], dep[2], dep[3])
            previous = dep

    def calculate_base_execution_rate(self):
        self.functional_port_issue_rate = self.physical_dispatch_width
        self.functional_unit_issue_rate = self.physical_dispatch_width
        self.calculate_functional_port_rate()
        self.calculate_functional_unit_rate()

        self.effective_dispatch_rates = {"DISPATCH" : self.physical_dispatch_width, "DEPENDENCES" : self.independent_instructions[self.ROB_size], "FUNCTIONAL_PORT" : self.functional_port_issue_rate, "FUNCTIONAL_UNIT" : self.functional_unit_issue_rate}

        self.debug_printer.save_debug_stats_live((self.physical_dispatch_width, self.independent_instructions[self.ROB_size], self.functional_port_issue_rate, self.functional_unit_issue_rate))

    def calculate_functional_port_rate(self):
        cycles_per_unit = {}
        for k in self.functional_units_pipelined:
            cycles_per_unit[k] = 0
        for k,v in self.instruction_per_functional_unit.iteritems():
            # v is the functional unit
            # k is the actual category of the uop
            for fu in v:
                if self.functional_units_pipelined[fu]:
                    if k in self.uop_hist:
                        cycles_per_unit[fu] += self.uop_hist[k] * 1.0 / len(self.functional_units_per_port[fu]) / len(v)
                else:
                    if k in self.uop_hist:
                        cycles_per_unit[fu] += self.uop_hist[k] * float(self.instruction_latencies[k]) / len(self.functional_units_per_port[fu]) / len(v)
        self.functional_port_issue_rate = float(sum(self.uop_hist.itervalues())) / max(cycles_per_unit.itervalues())

    def calculate_functional_unit_rate(self):
        cycles_per_port_new = {}
        for k in self.available_ports_split:
            cycles_per_port_new[k] = 0

        # we assume optimal scheduling by first taking all the instructions that can be scheduled only on one port
        # we schedule the instructions with multiple ports on their optimal port
        # example: schedule 30 adds on port 0,1 and 5 with following 'activity factors'
        # P0: 5     P1: 10      P5: 15
        # 15 adds are scheduled on port 1, 10 adds on port 2 and 5 adds on port 3
        # P0: 20    P1: 20      P5: 20
        for ins,ports in sorted(self.instruction_per_port.iteritems(), key = lambda s: len(s[1])):
            if len(ports) == 1:
                for p_outer in ports:
                    for p_inner in p_outer:
                        if ins in self.uop_hist:
                            cycles_per_port_new[p_inner] += self.uop_hist[ins]
            else:
                already_scheduled = []
                for p_outer in ports:
                    already_scheduled.append([])
                    for p_inner in p_outer:
                        already_scheduled[-1].append([float(cycles_per_port_new[p_inner]), p_inner])
                already_scheduled = sorted(already_scheduled)

                if ins in self.uop_hist:
                    current_port, activity_to_schedule = 0, float(self.uop_hist[ins])
                else:
                    current_port, activity_to_schedule = 0, 0
                while activity_to_schedule > 0:
                    if len(already_scheduled) > current_port + 1:
                        can_schedule = (already_scheduled[current_port + 1][0][0] - already_scheduled[current_port][0][0]) * (current_port + 1)
                        if can_schedule <= activity_to_schedule:
                            for i in range(0, current_port + 1):
                                for j in range(0, len(already_scheduled[i])):
                                    already_scheduled[i][j][0] += can_schedule / (current_port + 1)
                            activity_to_schedule -= can_schedule
                        else:
                            for i in range(0, current_port + 1):
                                for j in range(0, len(already_scheduled[i])):
                                    already_scheduled[i][j][0] += activity_to_schedule / (current_port + 1)
                            activity_to_schedule = 0
                    else:
                        for i in range(0, current_port + 1):
                            for j in range(0, len(already_scheduled[i])):
                                already_scheduled[i][j][0] += activity_to_schedule / (current_port + 1)
                        activity_to_schedule = 0

                    current_port += 1

                for i in range(0, len(already_scheduled)):
                    for cycles,port in already_scheduled[i]:
                        cycles_per_port_new[port] = 0
                for i in range(0, len(already_scheduled)):
                    for cycles,port in already_scheduled[i]:
                        cycles_per_port_new[port] += cycles

        self.functional_unit_issue_rate =  float(sum(self.uop_hist.itervalues())) / max(cycles_per_port_new.itervalues())

    def get_average_instruction_latency(self):
        return self.average_instruction_latency

    def get_path_lengths(self):
        return self.interpolated_dependences

    def get_independent_instructions(self):
        return self.independent_instructions

    def get_effective_dispatch_rates(self):
        return self.effective_dispatch_rates

    def calculate_base_component(self):
        total_base_component = 0

        base_component = float(self.stats[1]) / self.stats[0] * self.window_instruction_length / self.effective_dispatch_rates["DISPATCH"]
        total_base_component += base_component

        dependence_component = max(0, float(self.stats[1]) / self.stats[0] * self.window_instruction_length / self.effective_dispatch_rates["DEPENDENCES"] - total_base_component)
        total_base_component += dependence_component

        port_component = max(0, float(self.stats[1]) / self.stats[0] * self.window_instruction_length / self.effective_dispatch_rates["FUNCTIONAL_PORT"] - total_base_component)
        total_base_component += port_component

        unit_component = max(0, float(self.stats[1]) / self.stats[0] * self.window_instruction_length / self.effective_dispatch_rates["FUNCTIONAL_UNIT"] - total_base_component)

        return base_component,dependence_component,port_component,unit_component
