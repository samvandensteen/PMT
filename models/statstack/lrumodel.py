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
#			Andreas Sandberg, Uppsala University
#  Copyright: 2016, Ghent University

import histogram, missratio

def lru_sdist(rdist_hist, boundary = False):
    rdist_pdf   = histogram.Pdf(rdist_hist)
    rdist_rcdf  = histogram.Cdf_r(rdist_hist)
    rdist_sdist = {}

    for rdist, rcdf in rdist_rcdf:
        if len(rdist_sdist) == 0:
            prev_rdist = rdist
            prev_sdist = rdist
            rdist_sdist[rdist] = rdist
        else:
            if boundary:
                prev_sdist += (rdist - prev_rdist - 1) * rcdf + rcdf / (1.0 - rdist_pdf[prev_rdist])
            else:
                prev_sdist += (rdist - prev_rdist) * rcdf

            prev_rdist = rdist
            rdist_sdist[rdist] = prev_sdist

    return rdist_sdist

def sdist_hist(rdist_histograms, _type='rw', boundary = False):
    sdist_hist = {}

    #the mapping from reuse distances to stack distances is always built
    #from the full reuse distance histogram.
    rdist_sdist_map = lru_sdist(rdist_histograms['rw_rdist_hist'], boundary)

    for (rdist, count) in rdist_histograms['rw_rdist_hist'].items():
        sdist = int(round(rdist_sdist_map[rdist]))
        sdist_hist[sdist] = sdist_hist.get(sdist, 0) + count

        if _type == 'rw':
            pass
        elif _type == 'r':
            sdist_hist[sdist] -= rdist_histograms['wr_rdist_hist'].get(rdist, 0)
        elif _type == 'w':
            sdist_hist[sdist] -= rdist_histograms['rd_rdist_hist'].get(rdist, 0)
        else:
            raise Exception("Unknown sample type")

    return sdist_hist

def sdist_hist_PC(rdist_histograms, _type='rw', boundary = False):
    sdist_hist = {}

    for PC, rdist in rdist_histograms['rw_rdist_hist'].iteritems():
        sdist_hist[PC] = {}
        #the mapping from reuse distances to stack distances is always built
        #from the full reuse distance histogram.
        rdist_sdist_map = lru_sdist(rdist, boundary)

        for (rdist, count) in rdist.items():
            sdist = int(round(rdist_sdist_map[rdist]))
            sdist_hist[PC][sdist] = sdist_hist[PC].get(sdist, 0) + count

            if _type == 'rw':
                pass
            elif _type == 'r':
                # might be we don't need to subtract anything
                if PC in rdist_histograms['wr_rdist_hist']:
                    sdist_hist[PC][sdist] -= rdist_histograms['wr_rdist_hist'][PC].get(rdist, 0)
            elif _type == 'w':
                # might be we don't need to subtract anything
                if PC in rdist_histograms['rd_rdist_hist']:
                    sdist_hist[PC][sdist] -= rdist_histograms['rd_rdist_hist'][PC].get(rdist, 0)
            else:
                raise Exception("Unknown sample type")

    return sdist_hist

def miss_ratio(rdist_histograms, _type='rw', boundary = False):
    tmp_sdist_hist = sdist_hist(rdist_histograms, _type, boundary)
    rdist_histograms['sdist_hist'] = tmp_sdist_hist
    sdist_hist_items = tmp_sdist_hist.items()
    sdist_hist_items.sort(lambda (k0, v0), (k1, v1): cmp(k0, k1))

    ref_count  = sum(rdist_histograms['rw_rdist_hist'].values())

    if _type == 'rw':
        pass
    elif _type == 'r':
        wr_count = sum(rdist_histograms['wr_rdist_hist'].values())
        ref_count -= wr_count
    elif _type == 'w':
        rd_count = sum(rdist_histograms['rd_rdist_hist'].values())
        ref_count -= rd_count
    else:
        raise Exception("Unknown sample type")

    miss_count = ref_count
    miss_ratio = []

    if ref_count < 0:
        raise Exception("negative ref_count")
    elif ref_count == 0:
        return None, None

    for sdist, count in sdist_hist_items:
        miss_ratio.append((sdist, float(miss_count) / ref_count))
        miss_count -= count

    return missratio.MissRatio(miss_ratio), ref_count

def miss_ratio_range(rdist_histograms, cache_size_range, _type='rw', boundary = False):
    mr, ref_count = miss_ratio(rdist_histograms, _type, boundary)

    if mr is None:
        return None, None
    mr_out = []
    for cache_size in cache_size_range:
        mr_out.append((cache_size, mr[cache_size]))
    return missratio.MissRatio(mr_out), ref_count
