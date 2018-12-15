"""
This is the main program of BaseVar. It's the toppest layer of
BaseVar's tool sets.

Autor: Shujia Huang
Date: 2016-10-06 16:38:00
"""
import sys
import time

from datetime import datetime


def fusion():
    from caller.executor import FusionRunner
    cf = FusionRunner()
    cf.run()

    return


def basetype():
    from caller.executor import BaseTypeBamRunner
    bt = BaseTypeBamRunner()
    bt.run()

    return


def fusionbasetype():
    from caller.executor import BaseTypeFusionRunner
    ft = BaseTypeFusionRunner()
    ft.run()

    return


# def vqsr():
#     from caller.executor import VQSRRuner
#     vq = VQSRRuner()
#     vq.run()
#
#     return


def nearby_indel():

    from caller.executor import NearbyIndelRunner
    nbi = NearbyIndelRunner()
    nbi.run()

    return


def merge():
    from caller.executor import MergeRunner

    mg = MergeRunner()
    mg.run()

    return


def coverage():
    from caller.executor import CoverageRunner
    cvg = CoverageRunner()
    cvg.run()

    return


def main():

    START_TIME = datetime.now()

    runner = {'fusion': fusion,
              'basetype': basetype,
              'fusionbasetype': fusionbasetype,
              'merge': merge,
              'coverage': coverage,
              'nbi': nearby_indel,
              # 'VQSR': vqsr
              }

    if len(sys.argv) == 1 or (sys.argv[1] not in runner):
        sys.stderr.write('[Usage] python %s [option]\n\n' % sys.argv[0])
        sys.stderr.write('\n\t'.join(['Option:'] + runner.keys()) + '\n\n')
        sys.exit(1)

    command = sys.argv[1]
    runner[command]()

    elasped_time = datetime.now() - START_TIME
    sys.stderr.write('** %s done at %s, %d seconds elapsed **\n' % (command, time.asctime(), elasped_time.seconds))
    sys.stderr.write('>> For the flowers bloom in the desert <<\n')


if __name__ == '__main__':
    main()
