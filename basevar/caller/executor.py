"""
This module will contain all the executor steps of BaseVar.

We have many important modules in BaseVar while this one is
the lord to rule them all, in a word, it's "The Ring".

``BaseVar.py`` is "Sauron", and this module could just be called by it.
"""
from __future__ import division

import os
import sys
import argparse
import time

from pysam import FastaFile, AlignmentFile, TabixFile

from . import utils
from .fusion import Fusion
from .basetypebam import BaseVarMultiProcess as BamBaseVarMultiProcess
from .basetypefusion import BaseVarFusionMultiProcess
from .coverageprocess import BaseVarMultiProcess as CvgBaseVarMultiProcess
# from .vqsr import vqsr


class BaseTypeBamRunner(object):

    def __init__(self, cmm=utils.CommonParameter()):
        """init function
        """
        optp = argparse.ArgumentParser()
        optp.add_argument('basetype')
        optp.add_argument('-I', '--aligne-file-list', dest='infilelist', metavar='Bamfiles', default='',
                          help='BAM/CRAM file list, one line per file.')
        optp.add_argument('-R', '--reference', dest='referencefile', metavar='Reference_fasta',
                          help='Input reference fasta file.', default='')
        optp.add_argument('-O', '--outprefix', dest='outprefix', metavar='VCF_Prefix',
                          default='out', help='The prefix of output files. [out]')

        optp.add_argument('-L', '--positions', metavar='positions',type=str, dest='positions', default='',
                          help='skip unlisted positions (chrid pos). -L and --region could be provided '
                               'simultaneously. [None]')
        optp.add_argument('--region', metavar='chr:start-end', type=str, dest='region', default='',
                          help='Skip positions which not in these regions. Comma delimited list of regions '
                               '(chr:start-end). Could be a file contain the regions. This parameter could '
                               'be provide with -L simultaneously')

        # The number of output subfiles
        optp.add_argument('--batch-count', dest='batchcount', metavar='NUM', type=int, default=1000,
                          help='Number of samples in a batch file')

        optp.add_argument('--nCPU', dest='nCPU', metavar='Int', type=int, default=1,
                          help='Number of processer to use. [1]')
        optp.add_argument('-m', '--min_af', dest='min_af', type=float, metavar='float',
                          help='Setting prior precision of MAF and skip uneffective caller positions. Usually '
                               'you can set it to be min(0.001, 100/x), x is the number of your input BAM files.'
                               '[min(0.001, 100/x, cmm.MINAF)]. Probably you donot need to care about this parameter.')

        # special parameter for calculating specific population allele frequence
        optp.add_argument('--pop-group', dest='pop_group_file', metavar='Group-List-File', type=str,
                          help='Calculating the allele frequency for specific population.')

        optp.add_argument('--filename-has-samplename', dest='filename_has_samplename', type=bool, default=False,
                          help="Sample id should be the first element in filename and been separated by '.' . "
                               "This will save a lot of time if you have thousands of bamfiles. [False]")

        # special parameter to limit the function of BaseType
        optp.add_argument('--justdepth', dest='justdepth', metavar='bool', type=bool, default=False,
                          help='Just output the depth information for each position [False]')

        opt = optp.parse_args()
        self.opt = opt

        if len(sys.argv) == 2 and len(opt.infilelist) == 0:
            optp.error('[ERROR] Missing bamfile.\n')

        if len(opt.referencefile) == 0:
            optp.error('[ERROR] Missing reference fasta file.\n')

        # Loading positions or load all the genome regions
        self.regions = utils.load_target_position(opt.referencefile,
                                                  opt.positions,
                                                  opt.region)

        # Get all the input alignement files
        self.alignefiles = utils.load_file_list(opt.infilelist)

        # setting the precision of MAF
        self.cmm = cmm
        if self.opt.min_af is None:
            self.opt.min_af = min(100.0/len(self.alignefiles), 0.001, self.cmm.MINAF)

        self.cmm.MINAF = self.opt.min_af
        sys.stderr.write('[INFO] Finish loading parameters and input file '
                         'list %s\n' % time.asctime())

        # loading all the sample id from aligne_files
        # ``samples_id`` has the same size and order as ``aligne_files``
        self.sample_id = self._load_sample_id_from_bam(filename_has_samplename=opt.filename_has_samplename)

    def _load_sample_id_from_bam(self, filename_has_samplename=True):
        """loading sample id in BAM/CRMA files from RG tag"""

        sys.stderr.write('[INFO] Start loading all samples\' id from alignment files\n')
        if filename_has_samplename:
            sys.stderr.write('[INFO] loading samples\' id from filename because you '
                             'set "--filename-has-samplename True"\n')
        sample_id = []
        for i, al in enumerate(self.alignefiles):

            if i % 1000 == 0:
                sys.stderr.write("[INFO] loading %d/%d alignment files ... %s\n" %
                                 (i+1, len(self.alignefiles), time.asctime()))

            if filename_has_samplename:
                filename = os.path.basename(al)

                # sample id should be the first element separate by ".",
                # e.g: "CL100045504_L02_61.sorted.rmdup.realign.BQSR.bam", "CL100045504_L02_61" is sample id.
                sample_id.append(filename.split(".")[0])

            else:

                # This situation will take a very long time to get sampleID from BAM header.
                bf = AlignmentFile(al)
                if 'RG' not in bf.header:
                    sys.stderr.write('[ERROR] Bam file format error: missing @RG in the header.\n')
                    bf.close()
                    sys.exit(1)

                sample_id.append(bf.header['RG'][0]['SM'])
                bf.close()

        sys.stderr.write('[INFO] Finish load all %d samples\' ID '
                         'from RG tag\n\n' % len(sample_id))
        return sample_id

    def run(self):
        """
        Run variant caller
        """
        sys.stderr.write('[INFO] Start call variants by BaseType ... %s\n' % time.asctime())

        # Always create process manager even if nCPU==1, so that we can
        # listen signals from main thread
        regions_for_each_process = [[] for _ in range(self.opt.nCPU)]
        if len(self.regions) < self.opt.nCPU:
            # We cut the region into pieces to fit nCPU if regions < nCPU
            for chrid, start, end in self.regions:
                delta = int((end-start+1) / self.opt.nCPU)
                if delta == 0:
                    delta = 1

                for i, pos in enumerate(xrange(start-1, end, delta)):
                    s = pos + 1 if pos + 1 < end else end
                    e = pos + delta if pos + delta < end else end

                    regions_for_each_process[i % self.opt.nCPU].append([chrid, s, e])

        else:
            for i, region in enumerate(self.regions):
                regions_for_each_process[i % self.opt.nCPU].append(region)

        out_vcf_names = set()
        out_cvg_names = set()

        processes = []
        for i in range(self.opt.nCPU):
            sub_cvg_file = self.opt.outprefix + '_temp_%s' % i + '.cvg.tsv'
            out_cvg_names.add(sub_cvg_file)

            if not self.opt.justdepth:
                sub_vcf_file = self.opt.outprefix + '_temp_%s' % i + '.vcf'
                out_vcf_names.add(sub_vcf_file)
            else:
                sub_vcf_file = None

            sys.stderr.write('[INFO] Process %d/%d output to temporary files:'
                             '[%s, %s]\n' % (i+1, self.opt.nCPU, sub_vcf_file,
                                             sub_cvg_file))

            processes.append(BamBaseVarMultiProcess(self.opt.referencefile,
                                                    self.alignefiles,
                                                    self.opt.pop_group_file,
                                                    regions_for_each_process[i],
                                                    self.sample_id,
                                                    batchcount=self.opt.batchcount,
                                                    out_cvg_file=sub_cvg_file,
                                                    out_vcf_file=sub_vcf_file,
                                                    cmm=self.cmm))

        for p in processes:
            p.start()

        # listen for signal while any process is alive
        while True in [p.is_alive() for p in processes]:
            try:
                time.sleep(1)

            except KeyboardInterrupt:
                sys.stderr.write('KeyboardInterrupt detected, terminating '
                                 'all processes...\n')
                for p in processes:
                    p.terminate()

                sys.exit(1)

        # Make sure all process are finished
        for p in processes:
            p.join()

        # Final output file name
        out_cvg_file = self.opt.outprefix + '.cvg.tsv'  # position coverage
        utils.merge_files(out_cvg_names, out_cvg_file, is_del_raw_file=True)

        if not self.opt.justdepth:
            out_vcf_file = self.opt.outprefix + '.vcf'
            utils.merge_files(out_vcf_names, out_vcf_file, is_del_raw_file=True)

        return


class BaseTypeFusionRunner(object):
    def __init__(self, cmm=utils.CommonParameter()):
        """init function
        """
        optp = argparse.ArgumentParser()
        optp.add_argument('basetypefusion')
        optp.add_argument('-I', '--fusion-file-list', dest='infilelist', metavar='FILE',
                          help='Fusion file list, one line per file.', default='')
        optp.add_argument('-R', '--reference', dest='referencefile', metavar='FILE',
                          help='Input reference fasta file.', default='')
        optp.add_argument('-O', '--outprefix', dest='outprefix', metavar='FILE',
                          default='out', help='The prefix of output files. [out]')

        optp.add_argument('-L', '--positions', metavar='FILE', dest='positions',
                          help='skip unlisted positions (chr pos). [None]', default='')
        optp.add_argument('--region', metavar='chr:start-end', dest='region',
                          help='Skip position which not in these regions. Comma delimited '
                               'list of regions (chr:start-end). Could be a file contain the '
                               'regions.', default='')

        optp.add_argument('--nCPU', dest='nCPU', metavar='INT', type=int,
                          help='Number of processer to use. [1]', default=1)
        optp.add_argument('-m', '--min_af', dest='min_af', type=float, metavar='MINAF',
                          help='By setting min AF to skip uneffective caller positions '
                               'to accelerate program speed. Usually you can set it to '
                               'be min(0.001, 100/x), x is the size of your population.'
                               '[min(0.001, 100/x)]')

        # special parameter for calculating specific population allele frequence
        optp.add_argument('--pop-group', dest='pop_group_file', metavar='FILE', type=str,
                          help='Calculating the allele frequency for specific population.')

        # special parameter to limit the function of BaseType
        optp.add_argument('--justdepth', dest='justdepth', type=bool,
                          help='Just output the depth information for each position [False]',
                          default=False)

        opt = optp.parse_args()
        self.opt = opt

        if len(sys.argv) == 2 and len(opt.infilelist) == 0:
            optp.error('[ERROR] Missing bamfile.\n')

        if len(opt.referencefile) == 0:
            optp.error('[ERROR] Missing reference fasta file.\n')

        # Loading positions if not provid we'll load all the genome
        self.regions = utils.load_target_position(opt.referencefile, opt.positions,
                                                  opt.region)

        # Get all the input align fusion files
        self.fusionfiles = utils.load_file_list(opt.infilelist)

        self.cmm = cmm
        if self.opt.min_af is None:
            self.opt.min_af = min(100.0/len(self.fusionfiles), 0.001, self.cmm.MINAF)

        # reset threshold of min allele frequence threshold by sample size
        self.cmm.MINAF = self.opt.min_af

        sys.stderr.write('[INFO] Finish loading parameters and input file '
                         'list %s\n' % time.asctime())

        # loading all the sample id from aligne_files
        # ``samples_id`` has the same size and order as ``aligne_files``
        self.sample_id = self._load_sample_id()

    def _load_sample_id(self):
        """loading sample id in BAM/CRMA files from RG tag"""

        sys.stderr.write('[INFO] Start loading all samples\' id from alignment files\n')
        # loading sample'id from the header of fusion files
        sample_id = []
        for i, f in enumerate(self.fusionfiles):

            tf = TabixFile(f)
            try:
                # get sample ID: '##RG\tSM:SAMPLE_ID'
                header = [h for h in tf.header if h.startswith('##RG\tSM:')][0]
                sample_id.append(header.split(':')[-1])
                tf.close()

            except IndexError:

                sys.stderr.write('[ERROR] File header has no sample tag mark '
                                 'by "SM:", Please check %s!' % f)
                tf.close()
                sys.exit(1)

        sys.stderr.write('[INFO] Finish load all %d samples\' ID '
                         'from RG tag\n\n' % len(sample_id))
        return sample_id

    def run(self):
        """
        Run variant caller
        """
        sys.stderr.write('[INFO] Start call variants by BaseType ... %s\n' %
                         time.asctime())

        # Always create process manager even if nCPU==1, so that we can
        # listen for signals from main thread
        regions_for_each_process = [[] for _ in range(self.opt.nCPU)]
        if len(self.regions) < self.opt.nCPU:
            # We cut the region into pieces to fit nCPU if regions < nCPU
            for chrid, start, end in self.regions:
                delta = int((end-start+1) / self.opt.nCPU)
                if delta == 0:
                    delta = 1

                for i, pos in enumerate(xrange(start-1, end, delta)):
                    s = pos + 1 if pos + 1 < end else end
                    e = pos + delta if pos + delta < end else end

                    regions_for_each_process[i % self.opt.nCPU].append([chrid, s, e])

        else:
            for i, region in enumerate(self.regions):
                regions_for_each_process[i % self.opt.nCPU].append(region)

        out_vcf_names = set()
        out_cvg_names = set()

        processes = []
        for i in range(self.opt.nCPU):
            sub_cvg_file = self.opt.outprefix + '_temp_%s' % i + '.cvg.tsv'
            out_cvg_names.add(sub_cvg_file)

            if not self.opt.justdepth:
                sub_vcf_file = self.opt.outprefix + '_temp_%s' % i + '.vcf'
                out_vcf_names.add(sub_vcf_file)
            else:
                sub_vcf_file = None

            sys.stderr.write('[INFO] Process %d/%d output to temporary files:'
                             '[%s, %s]\n' % (i+1, self.opt.nCPU, sub_vcf_file,
                                             sub_cvg_file))

            processes.append(BaseVarFusionMultiProcess(self.opt.referencefile,
                                                       self.fusionfiles,
                                                       self.opt.pop_group_file,
                                                       regions_for_each_process[i],
                                                       self.sample_id,
                                                       out_cvg_file=sub_cvg_file,
                                                       out_vcf_file=sub_vcf_file,
                                                       cmm=self.cmm))

        for p in processes:
            p.start()

        # listen for signal while any process is alive
        while True in [p.is_alive() for p in processes]:
            try:
                time.sleep(1)

            except KeyboardInterrupt:
                sys.stderr.write('KeyboardInterrupt detected, terminating '
                                 'all processes...\n')
                for p in processes:
                    p.terminate()

                sys.exit(1)

        # make sure all process are finished
        for p in processes:
            p.join()

        # Final output file name
        out_cvg_file = self.opt.outprefix + '.cvg.tsv'  # position coverage
        utils.merge_files(out_cvg_names, out_cvg_file, is_del_raw_file=True)

        if not self.opt.justdepth:
            out_vcf_file = self.opt.outprefix + '.vcf'
            utils.merge_files(out_vcf_names, out_vcf_file, is_del_raw_file=True)

        return


class FusionRunner(object):

    def __init__(self):
        """
        init function
        """
        optp = argparse.ArgumentParser()

        optp.add_argument('fusion')
        optp.add_argument('-I', '--inputfile', dest='inbamfile', metavar='FILE',
                          help='BAM/CRAM file list, one line per file.', default='')

        optp.add_argument('-R', '--reference', dest='referencefile', metavar='FILE',
                          help='Input reference fasta file.', default='')

        optp.add_argument('-O', '--outputfile', dest='outfile', metavar='FILE',
                          default='out.fusion', help='Output fusion file. [out.fusion]')

        opt = optp.parse_args()
        self.opt = opt

        if len(sys.argv) == 2 and len(opt.infilelist) == 0:
            optp.error('[ERROR] Missing input BAM/CRAM file.\n')

        if len(opt.referencefile) == 0:
            optp.error('[ERROR] Missing reference fasta file.\n')

    def run(self):

        # Get alignment sample ID
        bf = AlignmentFile(self.opt.inbamfile)
        sample_id = bf.header['RG'][0]['SM']
        bf.close()

        callfusion = Fusion(self.opt.referencefile, self.opt.inbamfile)
        with open(self.opt.outfile, 'w') as OUT:

            OUT.write('##fileformat=Fusion_v1.0 and the coordinate is 0-base system\n')
            OUT.write('##RG\tSM:%s\n' % sample_id)
            OUT.write('\t'.join(['#CHROM', 'START', 'END', 'TYPE', 'MAPQ',
                                 'SO', 'Read_POS', 'BASE_QUAL']) + '\n')
            for fusion in callfusion.generate_fusion():

                info = '\t'.join(map(str, [fusion.chrid,
                                           fusion.start,
                                           fusion.end,
                                           fusion.alt,
                                           fusion.mapq,
                                           fusion.strand_orientation,
                                           fusion.read_first_position,
                                           fusion.base_quality]
                                     )
                                 )

                OUT.write(info+'\n')


# class VQSRRuner(object):
#     """Runner for VQSR"""
#     def __init__(self):
#         """Init function"""
#         self.vqsr = vqsr
#         return
#
#     def run(self):
#         self.vqsr.main(self.vqsr.cmdopts())
#
#         return


class CoverageRunner(object):

    def __init__(self, cmm=utils.CommonParameter()):
        """init function
        """
        optp = argparse.ArgumentParser()
        optp.add_argument('coverage')
        optp.add_argument('-o', '--outprefix', dest='outprefix', metavar='FILE',
                          default='out', help='The prefix of output files. [out]')
        optp.add_argument('-l', '--aligne-file-list', dest='infilelist', metavar='FILE',
                          help='Input alignmernt file list.', default='')
        optp.add_argument('-r', '--reference', dest='referencefile', metavar='FILE',
                          help='Input reference fasta file.', default='')

        optp.add_argument('-L', '--positions', metavar='FILE', dest='positions',
                          help='skip unlisted positions (chr pos)', default='')
        optp.add_argument('-R', '--regions', metavar='chr:start-end', dest='regions',
                          help='skip positions not in (chr:start-end)', default='')

        optp.add_argument('--nCPU', dest='nCPU', metavar='INT', type=int,
                          help='Number of processer to use. [1]', default=1)

        opt = optp.parse_args()
        self.opt = opt
        self.cmm = cmm

        if len(sys.argv) == 2 and len(opt.infilelist) == 0:
            optp.error('[ERROR] At least input one mpileup file.\n')

        if len(opt.referencefile) == 0:
            optp.error('[ERROR] Missing reference fasta file.\n')

        # Loading positions if not provid we'll load all the genome
        self.regions = self._loading_position(opt.positions, opt.regions)

        # Get all the input alignement files
        self.alignefiles = utils.load_file_list(opt.infilelist)
        sys.stderr.write('[INFO] Finish loading parameters and input file '
                         'list %s\n' % time.asctime())

    def _loading_position(self, posfile, regionfile):

        # Loading positions
        _sites = utils.get_list_position(posfile) if posfile else {}

        if len(regionfile):

            region = utils.get_region_fromfile(regionfile)
            for chrid, start, end in region:

                if chrid not in _sites:
                    _sites[chrid] = []

                _sites[chrid].append([start, end])

        # merge and sorted the regions
        # [[chrid1, start1, end1], [chrid2, start2, end2], ...]
        regions = []
        for chrid, v in sorted(_sites.items(), key=lambda x: x[0]):
            for start, end in utils.merge_region(v):
                regions.append([chrid, start, end])

        # load all the genome if no position or regions provide
        if not regions:

            sys.stderr.write('[WARNINGS] Program will load all the genome cause '
                             'there is not any positions and regions provided.\n')
            fa = FastaFile(self.opt.referencefile)
            regions = [[ci, 1, fa.get_reference_length(ci)]
                       for ci in fa.references]
            fa.close()

        return regions

    def run(self):
        """
        Run variant caller
        """
        sys.stderr.write('[INFO] Start call varaintis by BaseType ... %s\n' %
                         time.asctime())

        # Always create process manager even if nCPU==1, so that we can
        # listen for signals from main thread
        regions_for_each_process = [[] for _ in range(self.opt.nCPU)]
        if len(self.regions) < self.opt.nCPU:
            # We cut the region evenly to fit nCPU if regions < nCPU
            for chrid, start, end in self.regions:
                delta = int((end-start+1) / self.opt.nCPU)
                if delta == 0:
                    delta = 1

                for i, pos in enumerate(xrange(start-1, end, delta)):
                    s = pos + 1 if pos + 1 < end else end
                    e = pos + delta if pos + delta < end else end

                    regions_for_each_process[i % self.opt.nCPU].append([chrid, s, e])

        else:
            for i, region in enumerate(self.regions):
                regions_for_each_process[i % self.opt.nCPU].append(region)

        out_cvg_names = set()
        processes = []
        for i in range(self.opt.nCPU):
            sub_cvg_file = self.opt.outprefix + '_temp_%s' % i + '.cvg.tsv'

            out_cvg_names.add(sub_cvg_file)
            processes.append(CvgBaseVarMultiProcess(self.opt.referencefile,
                                                    self.alignefiles,
                                                    sub_cvg_file,
                                                    regions_for_each_process[i],
                                                    cmm=self.cmm))

        for p in processes:
            p.start()

        # listen for signal while any process is alive
        while True in [p.is_alive() for p in processes]:
            try:
                time.sleep(1)

            except KeyboardInterrupt:
                sys.stderr.write('KeyboardInterrupt detected, terminating '
                                 'all processes...\n')
                for p in processes:
                    p.terminate()

                sys.exit(1)

        # make sure all process are finished
        for p in processes:
            p.join()

        # Final output file name
        out_cvg_file = self.opt.outprefix + '.cvg.tsv'  # position coverage
        utils.merge_files(out_cvg_names, out_cvg_file, is_del_raw_file=True)

        return


class MergeRunner(object):
    """Runner for merging files"""
    def __init__(self):
        """init function"""
        optp = argparse.ArgumentParser()
        optp.add_argument('merge')
        optp.add_argument('-l', '--file-list', dest='infilelist', metavar='FILE',
                          help='The input files\' list.', default='')
        optp.add_argument('-o', '--outfile', dest='outfile', metavar='FILE', default='out',
                          help='The prefix of output files. [out]')

        opt = optp.parse_args()
        self.opt = opt

        if len(sys.argv) == 2 and len(opt.infilelist) == 0:
            optp.error('[ERROR] At least one input file.\n')

        # Load all files
        self.files = []
        if opt.infilelist:
            self.files.extend(utils.load_file_list(opt.infilelist))

    def run(self):
        utils.merge_files(self.files, self.opt.outfile)

        return


class NearbyIndelRunner(object):
    """Add Nearby Indel density and type information for each variants of VCF"""
    def __init__(self):
        """init function"""
        optp = argparse.ArgumentParser()
        optp.add_argument('nbi')
        optp.add_argument('-i', '--in-vcf-file', dest='in_vcf_file', metavar='FILE',
                          help='The input vcf files', default='')
        optp.add_argument('-c', '--in-cvg-file', dest='in_cvg_file', metavar='FILE',
                          help='Input coverage file which has indel information',
                          default='')
        optp.add_argument('-d', '--nearby-distance-around-indel',
                          dest='nearby_dis_around_indel',
                          help='The distance around indel. [16]', default=16)

        opt = optp.parse_args()
        opt.nearby_dis_around_indel = int(opt.nearby_dis_around_indel)
        self.opt = opt

        if len(sys.argv) == 2 and (len(opt.in_vcf_file) == 0 or len(opt.in_cvg_file) == 0):
            optp.error('[ERROR] At least one input file.\n')

        sys.stderr.write('[INFO] Parameters: python %s nbi' 
                         '\n\t-i %s'
                         '\n\t-c %s'
                         '\n\t-d %d' % (sys.argv[0],
                                        opt.in_vcf_file,
                                        opt.in_cvg_file,
                                        opt.nearby_dis_around_indel)
                         )

    def run(self):

        from .other import NearbyIndel

        nbi = NearbyIndel(self.opt.in_vcf_file,
                          self.opt.in_cvg_file,
                          nearby_distance=self.opt.nearby_dis_around_indel)
        nbi.run()

        return self
