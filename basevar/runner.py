"""
This is the main program of BaseVar. It's the toppest layer of
BaseVar's tool sets.

Autor: Shujia Huang
Date: 2016-10-06 16:38:00
"""
import argparse
import sys
import time

from basevar.log import logger
from caller.launch import BaseTypeRunner
from basevar.utils import do_cprofile


def parser_commandline_args():
    desc = "BaseVar: A python software for calling population variants for ultra low pass " \
           "whole genome sequencing data."

    cmdparse = argparse.ArgumentParser(description=desc)
    commands = cmdparse.add_subparsers(dest="command", title="BaseVar Commands")

    basetype_cmd = commands.add_parser('basetype', help='Variants Caller')
    basetype_cmd.add_argument('-I', '--input', dest='input', metavar='BAM/CRAM', action='append', default=[],
                              help='BAM/SAM/CRAM file containing reads. This argument could be specified at '
                                   'least once.')
    basetype_cmd.add_argument('-L', '--align-file-list', dest='infilelist', metavar='BamfilesList',
                              help='list of input BAM/CRAM filenames, one per line')
    basetype_cmd.add_argument('-R', '--reference', dest='referencefile', metavar='Reference_fasta', required=True,
                              help='Input reference fasta file.')

    basetype_cmd.add_argument('-q', dest='mapq', metavar='INT', type=int, default=10,
                              help='Only include reads with mapping quality >= INT. [10]', required=False)
    basetype_cmd.add_argument("-b", dest="min_base_qual", action='store', type=int, default=20,
                              help="Minimum allowed base-calling quality. Any bases with qual below "
                                   "this are ignored in SNP-calling. [20]", required=False)

    basetype_cmd.add_argument('--output-vcf', dest='outvcf', type=str,
                              help='Output VCF file. If not provide will skip variants discovery and just output '
                                   'position coverage file which filename is provided by --output-cvg.')
    basetype_cmd.add_argument('--output-cvg', dest='outcvg', type=str, required=True,
                              help='Output position coverage file.')

    basetype_cmd.add_argument('--positions', metavar='position-list-file', type=str, dest='positions',
                              help='skip unlisted positions one per row. The position format in the file could '
                                   'be (chrid pos) and (chrid start end) in mix. This parameter could be used '
                                   'with --regions simultaneously.')
    basetype_cmd.add_argument('--regions', metavar='chr:start-end', type=str, dest='regions', default='',
                              help='Skip positions which not in these regions. This parameter could be a list of '
                                   'comma deleimited genome regions(e.g.: chr:start-end,chr:start-end) or a file '
                                   'contain the list of regions. This parameter could be used with --positions '
                                   'simultaneously')

    # The number of output subfiles
    basetype_cmd.add_argument('-B', '--batch-count', dest='batch_count', metavar='INT', type=int, default=500,
                              help='INT simples per batchfile. [500]')
    basetype_cmd.add_argument('--nCPU', dest='nCPU', metavar='INT', type=int, default=1,
                              help='Number of processer to use. [1]')
    basetype_cmd.add_argument('-m', '--min-af', dest='min_af', type=float, metavar='float', default=0.001,
                              help='Setting prior precision of MAF and skip uneffective caller positions. Usually '
                                   'you can set it to be min(0.001, 100/x), x is the number of your input BAM files.'
                                   'Probably you don\'t hava to take care about this parameter.')

    basetype_cmd.add_argument('--pop-group', dest='pop_group_file', metavar='GroupListFile', type=str,
                              help='Calculating the allele frequency for specific population.')

    basetype_cmd.add_argument('--filename-has-samplename', dest='filename_has_samplename', action='store_true',
                              help="If the name of bamfile is something like 'SampleID.xxxx.bam', "
                                   "you can set this parameter to save a lot of time during get the "
                                   "sample id from BAM header.")

    # special parameter for calculating specific population allele frequence
    basetype_cmd.add_argument("--max-read-length", dest="r_len", action='store', type=int, default=150,
                              help="Maximum read length. [150]")

    basetype_cmd.add_argument("--max_reads", dest="max_reads", action='store', type=float, default=5000000,
                              help="Maximium coverage in window. [5000000]")
    basetype_cmd.add_argument("--compress-reads", dest="is_compress_read", type=int, default=0,
                              help="If this is set to 1, then all reads will be compressed, and decompressd on demand. "
                                   "This will slow things down, but reduce memory usage. [0]")
    basetype_cmd.add_argument("--qual_bin_size", dest="qual_bin_size", type=int, action='store', default=1,
                              help="This sets the granularity used when compressing quality scores. "
                                   "If > 1 then quality compression is lossy. [1]")

    basetype_cmd.add_argument("--trim-overlapping", dest="trim_overlapping", action='store_true',
                              help="If setted, overlapping paired reads have overlap set to qual 0.")
    basetype_cmd.add_argument("--trim-soft-clipped", dest="trim_soft_clipped", action='store_true',
                              help="If setted, then sets to qual 0 any soft clipped parts of the read.")
    basetype_cmd.add_argument("--filter-duplicates", dest="filter_duplicates", action='store', type=int, default=1,
                              help="If set to 1, duplicate reads will be removed based on the read-pair start and "
                                   "end. [1]", required=False)
    basetype_cmd.add_argument("--filter-reads-with-unmapped-mates", dest="filter_reads_with_unmapped_mates",
                              action='store', type=int, default=1, required=False,
                              help="If set to 1, reads with un-mapped mates will be removed. [1]")
    basetype_cmd.add_argument("--filter-reads-with-distant-mates", dest="filter_reads_with_distant_mates",
                              help="If set to 1, reads with mates mapped far away will be removed. [1]",
                              action='store', type=int, default=1, required=False)
    basetype_cmd.add_argument("--filter-read-pairs-with-small-inserts", dest="filter_read_pairs_with_small_inserts",
                              help="If set to 1, read pairs with insert sizes < one read length will be removed. [1]",
                              action='store', type=int, default=1, required=False)

    basetype_cmd.add_argument('--smart-rerun', dest='smartrerun', action='store_true',
                              help='Rerun process by checking batchfiles.')

    basetype_cmd.add_argument("--verbosity", dest="verbosity", action='store', type=int, default=1,
                              help="Level of logging(1,3). [1]")

    # VQSR commands
    vqsr_cmd = commands.add_parser('VQSR', help='Variants quality recalibrate.')
    vqsr_cmd.add_argument('-I', '--input', dest='vcf_infile', metavar='VCF', required=True,
                          help='Input VCF file.')
    vqsr_cmd.add_argument('-T', '--Train', dest='train_data', metavar='VCF', required=True,
                          help='Traning data set at true category.')
    vqsr_cmd.add_argument('-O', '--output', dest='output_vcf_file_name', metavar='VCF', type=str, required=True,
                          help='Output VCF file after VQSR.')

    # ApplyVQSR commands
    apply_vqsr_cmd = commands.add_parser('ApplyVQSR', help='Apply a score cutoff to filter variants based '
                                                           'on the truth sensitivity level.')
    apply_vqsr_cmd.add_argument('-I', '--input', dest='vcf_infile', metavar='VCF', required=True, help='Input VCF file.')
    apply_vqsr_cmd.add_argument('-O', '--output', dest='output_vcf_file_name', metavar='VCF', type=str, required=True,
                                help='Output filtered and recalibrated VCF file in which each variant is '
                                     'annotated with its VQSLOD. Required')
    apply_vqsr_cmd.add_argument('--ts', dest='truth_sensitivity_level', metavar='float', type=float, default=0.95,
                                help='The truth sensitivity level at which to start filtering. default=0.95')

    # Merge files
    merge_cmd = commands.add_parser('merge', help='Merge bed/vcf files')
    merge_cmd.add_argument('-I', '--input', dest='input', metavar='FILE', action='append', default=[],
                           help='Input files. This argument could be specify at least once')
    merge_cmd.add_argument('-L', '--file-list', dest='infilelist', metavar='FILE', help='Input files\' list.')
    merge_cmd.add_argument('-O', '--outputfile', dest='outputfile', metavar='FILE', required=True,
                           help='Output file')

    return cmdparse.parse_args()


@do_cprofile("./basetype.prof", is_do_profiling=True, stdout=True)
def basetype(args):
    if args.outcvg and not args.outvcf:
        sys.stderr.write("***************************************************\n"
                         "********************* WARNING *********************\n"
                         "***************************************************\n"
                         ">>>     You have just setted `--output-cvg`     <<<\n"
                         ".. Program will just output coverage information ..\n"
                         "***************************************************\n\n")

    if args.smartrerun:
        sys.stderr.write("************************************************\n"
                         "******************* WARNING ********************\n"
                         "************************************************\n"
                         ">>>>>>>> You have setted `smart rerun` <<<<<<<<<\n"
                         "Please make sure all the parameters are the same\n"
                         "with your previous commands.\n"
                         "************************************************\n\n")

    # Make sure you have set at least one bamfile.
    if not args.input and not args.infilelist:
        sys.stderr.write("[ERROR] Missing input BAM/CRAM files.\n\n")
        sys.exit(1)

    # The main function
    bt = BaseTypeRunner(args)
    is_success = bt.basevar_caller()
    # is_success = bt.basevar_caller_singleprocess()  # Just for cProfile and optimization testing

    return is_success


def vqsr(args):
    from basevar.caller.launch import VQSRRunner

    vqsr_runner = VQSRRunner(args)
    vqsr_runner.run()

    return True


def apply_vqsr(args):
    from basevar.caller.launch import ApplyVQSRRunner
    apply_vqsr_runner = ApplyVQSRRunner(args)
    apply_vqsr_runner.run()

    return True


def merge(args):
    from basevar.caller.launch import MergeRunner

    mg = MergeRunner(args)
    return mg.run()


def main():
    start_time = time.time()
    runner = {
        'basetype': basetype,
        'VQSR': vqsr,
        'ApplyVQSR': apply_vqsr,
        'merge': merge,
    }

    args = parser_commandline_args()
    logger.info("... %s starting ...\n" % args.command)

    is_success = runner[args.command](args)
    if is_success:
        logger.info('%s done, %d seconds elapsed.\n' % (
            args.command, time.time() - start_time))
    else:
        logger.error("Catch some exception, so \"%s\" is not done, %d seconds elapsed\n" % (
            args.command, time.time() - start_time))
        sys.exit(1)

    return

