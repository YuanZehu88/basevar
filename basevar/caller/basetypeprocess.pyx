# cython: profile=True
"""
This is a Process module for BaseType by BAM/CRAM

"""
import os
import sys
import time

from basevar.io.fasta import FastaFile

from basevar.log import logger
from basevar import utils

from basevar.caller.variantcaller import output_header
from basevar.caller.variantcaller cimport variants_discovery
from basevar.caller.variantcaller cimport variant_discovery_in_regions
from basevar.caller.batchcaller cimport create_batchfiles_in_regions

cdef bint REMOVE_BATCH_FILE = True

cdef class BaseVarProcess:
    """
    simple class to repesent a single BaseVar process.
    """
    def __cinit__(self, samples, align_files, ref_file, regions, out_vcf_file=None,
                  out_cvg_file=None, cache_dir=None, options=None):
        """Constructor.

        Store input file, options and output file name.

        Parameters:
        ===========
            samples: list like
                A list of sample id

            regions: 2d-array like, required
                    It's region info , format like: [[chrid, start, end], ...]
        """
        self.samples = samples

        self.align_files = align_files
        self.fa_file_hd = FastaFile(ref_file, ref_file + ".fai")

        self.out_vcf_file = out_vcf_file
        self.out_cvg_file = out_cvg_file

        self.options = options
        self.cache_dir = cache_dir

        self.regions = regions
        self.dict_regions = utils.regions2dict(regions)

        # loading population group
        # group_id => [a list samples_index]
        self.popgroup = {}
        if options.pop_group_file and len(options.pop_group_file):
            self.popgroup = utils.load_popgroup_info(self.samples, options.pop_group_file)

    def run(self):
        # self.run_variant_discovery_in_regions()  # do not create batch files
        self.run_variant_discovery_by_batchfiles()
        return

    cdef void run_variant_discovery_by_batchfiles(self):

        VCF = open(self.out_vcf_file, "w") if self.out_vcf_file else None
        CVG = open(self.out_cvg_file, "w")
        output_header(self.fa_file_hd.filename, self.samples, self.popgroup, CVG, out_vcf_handle=VCF)

        if self.options.smartrerun:
            utils.safe_remove(utils.get_last_modification_file(self.cache_dir))

        cdef long int region_boundary_start
        cdef long int region_boundary_end
        cdef int sample_num = len(self.samples)
        cdef list total_batch_files = []
        cdef bint is_empty = True
        for chrid, regions in sorted(self.dict_regions.items(), key=lambda x: x[0]):
            start_time = time.time()

            tmp_region = []
            for p in regions:
                tmp_region.extend(p)

            tmp_region = sorted(tmp_region)
            # get region boundary and set the coordinate to be 0-base
            region_boundary_start = max(0, tmp_region[0] - 1)
            region_boundary_end = min(tmp_region[-1] - 1, self.fa_file_hd.get_reference_length(chrid) - 1)

            # set cache for fa sequence, this could make the program much faster
            # And remember that ``fa_file_hd`` is 0-base system
            self.fa_file_hd.set_cache_sequence(
                chrid,
                max(0, region_boundary_start - 5 * self.options.r_len),
                min(region_boundary_end + 5 * self.options.r_len, self.fa_file_hd.get_reference_length(chrid) - 1)
            )

            batchfiles = create_batchfiles_in_regions(chrid,
                                                      regions,
                                                      region_boundary_start, # 0-base
                                                      region_boundary_end, # 0-base
                                                      self.align_files,
                                                      self.fa_file_hd,
                                                      self.samples,
                                                      self.cache_dir,
                                                      self.options)

            logger.info("Batchfiles in %s:%s-%s for %d samples done, %d seconds elapsed." % (
                chrid, region_boundary_start+1, region_boundary_end, sample_num, time.time() - start_time))

            start_time = time.time()
            logger.info("**************** variants discovery process ****************")
            try:
                _is_empty = variants_discovery(chrid, batchfiles, self.popgroup, self.options.min_af,
                                               CVG, VCF)
            except Exception, e:
                logger.error("Variants discovery in region %s:%s-%s. Error: %s" % (
                    chrid, region_boundary_start+1, region_boundary_end+1, e))
                sys.exit(1)

            if not _is_empty:
                is_empty = False

            # collect together will be convenient when we want to clear up these temporary files.
            total_batch_files += batchfiles
            logger.info("Running variants_discovery in %s:%s-%s done, %d seconds elapsed.\n" % (
                chrid, region_boundary_start+1, region_boundary_end, time.time() - start_time))

        CVG.close()
        if VCF:
            VCF.close()

        self.fa_file_hd.close()

        if is_empty:
            logger.warning("\n***************************************************************************\n"
                           "[WARNING] No reads are satisfy with the mapping quality (>=%d) in all of your\n"
                           "input files. We get nothing in %s \n\n" % (self.options.mapq, self.out_cvg_file))
            if VCF:
                logger.warning("and %s " % self.out_vcf_file)

        if REMOVE_BATCH_FILE:

            for f in total_batch_files:
                os.remove(f)

            try:
                os.removedirs(self.cache_dir)
            except OSError:
                logger.warning("Directory not empty: %s, please delete it by yourself\n" % self.cache_dir)

        # double check
        name = self.out_cvg_file + ".PROCESS.AND_VCF_DONE_SUCCESSFULLY"
        with open(name, "w") as OUT:
            OUT.write("The process done.\n")

        return

    ##################################################
    cdef void run_variant_discovery_in_regions(self):
        """Run the process of calling variant without creating batch files.
        This function will hit A BIG IO problem when we need to read huge number of BAM files.
        """
        start_time = time.time()
        cdef bint is_empty
        try:
            is_empty = variant_discovery_in_regions(
                self.fa_file_hd,
                self.align_files,
                self.regions,
                self.samples,
                self.popgroup,
                self.out_cvg_file,
                self.out_vcf_file,
                self.options
            )

        except Exception, e:
            logger.error("Error happen in run_variant_discovery_in_regions(): %s" % e)
            sys.exit(1)

        logger.info("Running variant_discovery_in_regions for %s done, %d seconds elapsed." % (
                self.out_cvg_file+".[and.vcf]", time.time() - start_time))

        if is_empty:
            logger.warning("\n***************************************************************************\n"
                           "[WARNING] No reads are satisfy with the mapping quality (>=%d) in all of your\n"
                           "input files. We get nothing in %s \n\n" % (self.options.mapq, self.out_cvg_file))
            if self.out_vcf_file:
                logger.warning("and %s " % self.out_vcf_file)

        name = self.out_cvg_file + ".PROCESS.AND_VCF_DONE_SUCCESSFULLY"
        with open(name, "w") as OUT:
            OUT.write("The process done.\n")

        return
