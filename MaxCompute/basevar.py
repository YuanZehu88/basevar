#!/usr/bin/env python

#coding:utf-8
from odps.udf import annotate
from odps.udf import BaseUDTF
from odps.distcache import get_cache_archive

from mpileup import first_base
from algorithm import strand_bias
from basetype import CommonParameter
from basetype import BaseType

# for import scipy
def include_package_path(res_name):
    import os, sys
    archive_files = get_cache_archive(res_name)
    dir_names = sorted([os.path.dirname(os.path.normpath(f.name)) for f in archive_files
                       if '.dist_info' not in f.name], key=lambda v: len(v))
    sys.path.append(os.path.dirname(dir_names[0]))

@annotate("string,string,string,string,string->string")
class BaseVar(BaseUDTF):

    def __init__(self, cmm=CommonParameter()):
        self.cmm = cmm
        if not cmm.debug:
            include_package_path('scipy.zip')

    def process(self, mode, chrid, pos, base_ref, one):
        tokens = one.split('\t')
        sample_count = len(tokens) / 3
        print '%s processing %s %s %s, %s samples' % (mode, chrid, pos, base_ref, sample_count)

        bases = ['N'] * sample_count
        quals = [ord('!') - 33] * sample_count
        strands = ['.'] * sample_count
        indels = []

        for i in xrange(0, sample_count):
            b = tokens[i * 3]
            q = tokens[i * 3 + 1]
            s = tokens[i * 3 + 2]
            indel = []
            # if self.cmm.verbose:
            #     print 'sample %7d\t[%s] [%s] [%s]' % (i, b, q, s),

            if b != '0' and q != '*':
                strand, base, qual, indel = first_base(
                    base_ref, q, s, is_scan_indel=self.cmm.scan_indel)
                bases[i] = base
                quals[i] = ord(qual) - 33
                strands[i] = strand
                indels.extend(indel)
            #     if self.cmm.verbose:
            #         print '\t->\t[%s] [%s] [%s]\tindel %s' % (base, qual, strand, str(indels))
            # else:
            #     if self.cmm.verbose:
            #         print

        # TODO: seems unnecessary
        # if BaseVarSingleProcess.total_subsamcol:
        #     for k, b in enumerate(bases):
        #         if k not in BaseVarSingleProcess.total_subsamcol:
        #             # set un-selected bases to be 'N' which
        #             # will be filted
        #             bases[k] = 'N'
        # # ACGT count and mark the refbase
        # if not base_ref:
        #     # mark '*' if coverage is 0
        #     base_ref = '*'

        if mode == 'coverage':
            self.forward(self._out_cvg_line(chrid, pos, base_ref, bases, strands, indels))
        elif mode == 'vcf':
            bt = BaseType(base_ref.upper(), bases, quals, cmm=self.cmm)
            bt.lrt()
            if len(bt.alt_bases()) > 0:
                self.forward(self._out_vcf_line(chrid, pos, base_ref,
                                                bases, strands, bt))
        else:
            raise Exception('unknown mode %s' % mode)

    def _out_cvg_line(self, chrid, position, ref_base, sample_base,
                      strands, indels):
        # TODO
        self.total_subsamcol = None

        # coverage info for each position
        base_depth = {b: 0 for b in self.cmm.BASE}
        for k, b in enumerate(sample_base):

            if self.total_subsamcol and k not in self.total_subsamcol:
                # set un-selected bases to be 'N' which will be filted later
                sample_base[k] = 'N'
                continue

            # ignore all bases('*') which not match ``cmm.BASE``
            if b in base_depth:
                base_depth[b] += 1

        # deal with indels
        indel_dict = {}
        for ind in indels:
            indel_dict[ind] = indel_dict.get(ind, 0) + 1

        indel_string = ','.join([k + ':' + str(v)
                                 for k, v in indel_dict.items()]) if indel_dict else '.'

        fs, ref_fwd, ref_rev, alt_fwd, alt_rev = 0, 0, 0, 0, 0
        if sample_base:
            base_sorted = sorted(base_depth.items(),
                                 lambda x, y: cmp(x[1], y[1]),
                                 reverse=True)

            b1, b2 = base_sorted[0][0], base_sorted[1][0]
            fs, ref_fwd, ref_rev, alt_fwd, alt_rev = strand_bias(
                ref_base, [b1 if b1 != ref_base.upper() else b2],
                sample_base, strands)

        return '\t'.join([chrid, str(position), ref_base, str(sum(base_depth.values()))] + [str(base_depth[b]) for b in self.cmm.BASE] + [indel_string]) + '\t' + str(fs) + '\t' + ','.join(map(str, [ref_fwd, ref_rev, alt_fwd, alt_rev]))

    def _out_vcf_line(self, chrid, position, ref_base, sample_base,
                      strands, bt):
        #
        alt_gt = {b:'./'+str(k+1) for k,b in enumerate(bt.alt_bases())}
        samples = []

        for k, b in enumerate(sample_base):

            # For sample FORMAT
            if b != 'N':
                # For the base which not in bt.alt_bases()
                if b not in alt_gt: alt_gt[b] = './.'
                gt = '0/.' if b==ref_base.upper() else alt_gt[b]

                samples.append(gt+':'+b+':'+strands[k]+':'+
                               str(round(bt.qual_pvalue[k], 6)))
            else:
                samples.append('./.') ## 'N' base

        # Strand bias by fisher exact test
        # Normally you remove any SNP with FS > 60.0 and an indel with FS > 200.0
        fs, ref_fwd, ref_rev, alt_fwd, alt_rev = strand_bias(
            ref_base, bt.alt_bases(), sample_base, strands)

        # base=>[AF, allele depth]
        af = {b:['%f' % round(bt.depth[b]/float(bt.total_depth), 6),
                 bt.depth[b]] for b in bt.alt_bases()}

        info = {'CM_DP': str(int(bt.total_depth)),
                'CM_AC': ','.join(map(str, [af[b][1] for b in bt.alt_bases()])),
                'CM_AF': ','.join(map(str, [af[b][0] for b in bt.alt_bases()])),
                'CM_EAF': ','.join(map(str, [bt.eaf[b] for b in bt.alt_bases()])),
                'FS': str(fs),
                'SB_REF': str(ref_fwd)+','+str(ref_rev),
                'SB_ALT': str(alt_fwd)+','+str(alt_rev)}

        return '\t'.join([chrid, str(position), '.', ref_base,
                         ','.join(bt.alt_bases()), str(bt.var_qual()),
                         '.' if bt.var_qual() > self.cmm.QUAL_THRESHOLD else 'LowQual',
                         ';'.join([k+'='+v for k, v in sorted(
                            info.items(), key=lambda x:x[0])]),
                            'GT:AB:SO:BP'] + samples)

# for local test
if __name__ == '__main__':
    import sys
    sys.path.append('.')
    if len(sys.argv) < 3:
        print 'usage: %s vcf|coverage input_wide_table_file' % sys.argv[0]
        sys.exit(1)

    mode = sys.argv[1]
    cmm = CommonParameter()
    cmm.debug = True
    basevar = BaseVar(cmm)
    with open(sys.argv[2]) as f:
        for l in f:
            token = l.split(',', 3)
            token[-1] = token[-1].rstrip('\n')
            basevar.process(mode, token[0], token[1], token[2], token[3])