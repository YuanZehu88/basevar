"""
Package for parsing bamfile
Author: Shujia Huang
Date : 2016-07-19 14:14:21
"""
import sys

from . import utils


def fetch_base_by_position(position, sample_info, iter_tokes, fa):
    """
    """
    base_quals = []
    bases = []
    strands = []
    mapqs = []
    read_pos_rank = []

    for i, sample_pos_line in enumerate(sample_info):

        bs, qs, strand, mapq, rpr, sample_info[i] = seek_position(position, sample_pos_line, iter_tokes[i], fa)

        bases.append(bs)
        base_quals.append(qs)
        strands.append(strand)
        mapqs.append(mapq)
        read_pos_rank.append(rpr)

    return bases, base_quals, strands, mapqs, read_pos_rank


def seek_position(target_pos, sample_pos_line, sample_iter, fa):
    """Get mapping info for specific position.

    `fa`: Use for scanning indels
    """
    base, strand, qual, rpr, mapq = 'N', '.', 0, 0, 0  # Init
    if sample_pos_line:

        if sample_pos_line.pos < target_pos:

            pos = sample_pos_line.pos
            while pos < target_pos:

                sample_pos_line = utils.fetch_next(sample_iter)
                if sample_pos_line:
                    pos = sample_pos_line.pos
                else:
                    # hit the end of file, break the loop.
                    break

        # sample_pos_line may hit the end of file
        if sample_pos_line and sample_pos_line.pos == target_pos:
            base, strand, qual, mapq, rpr = first_base(sample_pos_line, sample_pos_line.pos, fa)

    return base, qual, strand, mapq, rpr, sample_pos_line


def scan_indel(read, target_pos, fa):
    """Just scanning indel from pysam's pileups object.

    `target_pos`: 0-base
    `fa`: for fetch sequence from reference

    The cigar string order in the array is "MIDNSHP=X" followed by a
    field for the NM tag. If the NM tag is not present, this
    field will always be 0.

        +-----+--------------+-----+
        |M    |BAM_CMATCH    |0    |
        +-----+--------------+-----+
        |I    |BAM_CINS      |1    |
        +-----+--------------+-----+
        |D    |BAM_CDEL      |2    |
        +-----+--------------+-----+
        |N    |BAM_CREF_SKIP |3    |
        +-----+--------------+-----+
        |S    |BAM_CSOFT_CLIP|4    |
        +-----+--------------+-----+
        |H    |BAM_CHARD_CLIP|5    |
        +-----+--------------+-----+
        |P    |BAM_CPAD      |6    |
        +-----+--------------+-----+
        |=    |BAM_CEQUAL    |7    |
        +-----+--------------+-----+
        |X    |BAM_CDIFF     |8    |
        +-----+--------------+-----+
        |B    |BAM_CBACK     |9    |
        +-----+--------------+-----+
        |NM   |NM tag        |10   |
        +-----+--------------+-----+

    If no cigar string is present, empty arrays will be archived.
    """
    target_indx = 0
    for i, (cigar_type, cigar_len) in enumerate(read.alignment.cigar):
        # If the cigar string is : 20M2I13M
        # then alignment.cigar is: [(0, 20), (1, 2), (0, 13)]
        # and alignment.blocks looks like: [(1121815, 1121835), (1121835, 1121848)].
        # But we should find the position of Insertion, which is the next one.

        if cigar_type in [3,4,5,6]:  # 'SHPN'
            continue

        # mapping
        if cigar_type == 0:
            _, map_end = read.alignment.blocks[target_indx]

            # map_end is 1-base and target_pos is 0-base
            if map_end == target_pos + 1:
                target_indx += 1  # +1 Get the index of indel in alignment.cigar
                break
            else:
                # +1 and continue
                target_indx += 1

    cigar_type, cigar_len = read.alignment.cigar[target_indx]
    if cigar_type == 1:  # Insertion

        qpos = read.query_position + 1
        indel = '+' + read.alignment.query_sequence[qpos:qpos+cigar_len]
    elif cigar_type == 2:  # Deletion

        tpos = target_pos + 1
        indel = '-' + fa[tpos:tpos+cigar_len]
    else:
        # Must just be 1 or 2
        sys.stderr.write("[ERROR] Wrong Indel CIGAR number %s %s %s %s (at) %s\n" %
                         (read.alignment.cigarstring, read.alignment.cigar,
                          read.alignment.blocks, read.alignment.cigar[target_indx],
                          read.alignment))
        sys.exit(1)

    return indel if indel else 'N'


def first_base(sample_pos_line, position, fa):
    """Just get first alignement base for each sample.
    """
    base, strand, qual, rpr, mapq = 'N', '.', 0, 0, 0  # Init
    for read in [al for al in sample_pos_line.pileups if al.alignment.mapq >= 30]:
        # skip read which mapping quality less then 30

        strand = '-' if read.alignment.is_reverse else '+'
        mapq = read.alignment.mapq
        if read.indel:
            base = scan_indel(read, position, fa)
            break

        elif not read.is_del and not read.is_refskip:
            # skip the base which base_quality < 20
            # if read.alignment.query_qualities[read.query_position] < 20:
            #     continue

            rpr = read.query_position + 1
            base = read.alignment.query_sequence[read.query_position]

            # Todo: much faster than `read.alignment.qqual[read.query_position]`
            #  and I don't know why.
            qual = read.alignment.query_qualities[read.query_position]

            # Just get the first one and skip other reads which covereds this position,
            # no matter the first one it's indel or not.
            break

    return base, strand, qual, mapq, rpr
