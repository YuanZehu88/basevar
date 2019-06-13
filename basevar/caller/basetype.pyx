"""
This module contain functions of LRT and Base genotype.
"""
import itertools  # Use the combinations function

from scipy.stats.distributions import chi2

from basevar.caller.algorithm cimport EM
from basevar.utils import CommonParameter


cdef extern from "stdlib.h":
    # void *malloc(size_t)
    void *calloc(size_t, size_t)
    void free(void *)


cdef extern from "math.h":
    double exp(double)
    double round(double)
    double log(double)
    double log10(double)


cdef class BaseTuple:
    def __cinit__(self, int combination_num, int base_num):
        # initial the value
        self.combination_num = combination_num
        self.base_num = base_num
        self.base_comb_tuple = <char**>(calloc(combination_num, sizeof(char*)))
        assert self.base_comb_tuple != NULL, "Could not allocate memory for self.base_comb_tuple in BaseTuple."

        self.alleles_freq_list = <double**>(calloc(combination_num, sizeof(double*)))
        assert self.alleles_freq_list != NULL, (
            "Could not allocate memory for self.alleles_freq_list in BaseTuple.")

        cdef int i = 0
        for i in range(combination_num):
            self.base_comb_tuple[i] = <char*>(calloc(base_num, sizeof(char)))
            self.alleles_freq_list[i] = <double*>(calloc(base_num, sizeof(double)))

        self.sum_marginal_likelihood = <double*>(calloc(combination_num, sizeof(double)))
        assert self.sum_marginal_likelihood != NULL, (
            "Could not allocate memory for self.sum_marginal_likelihood in BaseTuple.")

    def __dealloc__(self):
        self.destory_tuple()

    cdef void destory_tuple(self):
        """Free memory"""
        cdef int index = 0
        if self.base_comb_tuple != NULL:
            for index in range(self.combination_num):
                if self.base_comb_tuple[index] != NULL:
                    free(self.base_comb_tuple[index])
                    self.base_comb_tuple[index] = NULL

                free(self.base_comb_tuple)
                self.base_comb_tuple = NULL

        if self.alleles_freq_list != NULL:
            index = 0
            for index in range(self.combination_num):
                if self.alleles_freq_list[index] != NULL:
                    free(self.alleles_freq_list[index])
                    self.alleles_freq_list[index] = NULL

                free(self.alleles_freq_list)
                self.alleles_freq_list = NULL

        if self.sum_marginal_likelihood != NULL:
            free(self.sum_marginal_likelihood)
            self.sum_marginal_likelihood = NULL


cdef class BaseType:

    def __cinit__(self, bytes ref_base, list bases, list quals, float min_af):

        """A class for calculate the base probability

        Parameters
        ----------

        ``ref_base``: A char, required
            The reference base

        ``bases``: A array like, required
            A list of base for samples.

        ``quals``: An array like, required
            Base quality for ``bases``. The same size with ``bases``
            Cause: The ``quals`` is an integer array which has be converted
                by phred-scale
        """
        self._ref_base = ref_base
        self._alt_bases = None
        self._var_qual = 0.0  # init the variant quality
        self.min_af = min_af
        self.depth = {b: 0 for b in CommonParameter.BASE}
        self.base_type_num = len(CommonParameter.BASE)

        # how many individual is in good base
        cdef int total_base_size = len(bases)
        cdef int i = 0
        self.good_individual_num = 0
        for i in range(total_base_size):
            if bases[i] != 'N' and bases[i][0] not in ['-', '+']:
                self.good_individual_num += 1

        # qual_pvalue has to be for all, because we'll use this outside.
        self.qual_pvalue = <double*>(calloc(total_base_size, sizeof(double)))
        assert self.qual_pvalue != NULL, "Could not allocate memory for qual_pvalue in BaseType"
        i = 0
        for i in range(total_base_size):
            self.qual_pvalue[i] = 1.0 - exp(CommonParameter.MLN10TO10 * quals[i])

        self.ind_allele_likelihood = <double*>(calloc(self.good_individual_num * self.base_type_num, sizeof(double)))
        assert self.ind_allele_likelihood != NULL, "Could not allocate memory for ind_allele_likelihood in BaseType"

        # set allele likelihood for each individual and get depth
        self._set_init_ind_allele_likelihood(bases, CommonParameter.BASE)
        self.total_depth = float(sum(self.depth.values()))

        # estimated allele frequency by EM and LRT
        self.af_by_lrt = {}

        return

    def __dealloc__(self):
        """
        Free memory
        """
        if self.ind_allele_likelihood != NULL:
            free(self.ind_allele_likelihood)

        if self.qual_pvalue != NULL:
            free(self.qual_pvalue)

    cdef void _set_init_ind_allele_likelihood(self, list ind_bases, list base_element):

        cdef int total_individual = len(ind_bases)
        cdef int i = 0
        cdef int j = 0
        cdef int k = 0
        for i in range(total_individual):

            # Individual likelihood for [A, C, G, T], one sample per row
            # ignore all the 'N' bases and indels.
            if ind_bases[i] != 'N' and ind_bases[i][0] not in ['-', '+']:

                for k in range(self.base_type_num):
                    if ind_bases[i] == base_element[k]:
                        self.ind_allele_likelihood[j * self.base_type_num + k] = self.qual_pvalue[i]
                    else:
                        self.ind_allele_likelihood[j * self.base_type_num + k] = (1.0 - self.qual_pvalue[i])/3

                # iteration good individual
                j += 1

                # record coverage for [ACGT]
                if ind_bases[i] in self.depth:
                    self.depth[ind_bases[i]] += 1

    cdef double* _set_allele_frequence(self, tuple bases):
        """
        init the base likelihood by bases

        ``bases``: a list like
        """
        # calloc will initial the allele_frequence to be 0.0 by default
        cdef double* allele_frequence = <double*>(calloc(self.base_type_num, sizeof(double)))
        assert allele_frequence != NULL, (
            "Could not allocate memory for allele_frequence in BaseType._set_allele_frequence")

        cdef bytes b
        cdef double total_depth = sum([self.depth[b] for b in bases])
        if total_depth > 0:
            for b in bases:
                allele_frequence[CommonParameter.BASE2IDX[b]] = self.depth[b] / total_depth

        return allele_frequence

    cdef BaseTuple _f(self, list bases, int n):
        """
        Calculate population likelihood for all the combination of bases

        Parameters
        ----------

        ``bases``: 1d array like
            A list of bases from [A, C, G, T]

        ``n``: Integer
            The combination number. n must less or equal
            to the length of ``bases``

        Return
        ------

        ``bc``: array=like, combination bases
        ``lr``: Likelihood of ``bc``

        Example
        -------

        >>> import itertools
        >>> bases = ['A', 'C', 'G', 'T']
        >>> bc=[i for i in itertools.combinations(bases,3)]
        >>> bc
        ... [('A', 'C', 'G'), ('A', 'C', 'T'), ('A', 'G', 'T'), ('C', 'G', 'T')]

        """
        cdef double* init_allele_frequecies = NULL
        cdef double* marginal_likelihood = NULL
        cdef double* expect_allele_freq = NULL

        cdef list base_combs_tuple = [x for x in itertools.combinations(bases, n)]
        cdef int comb_num = len(base_combs_tuple)

        # bc, lr, bp = [], [], []
        cdef BaseTuple base_tuple = BaseTuple(comb_num, n)
        cdef int bi = 0
        cdef int i = 0
        for i in range(comb_num):

            init_allele_frequecies = self._set_allele_frequence(base_combs_tuple[i])
            if self.sum_likelihood(init_allele_frequecies, self.base_type_num, False) == 0:
                free(init_allele_frequecies)
                continue

            # reset every time
            marginal_likelihood = <double*>(calloc(self.good_individual_num, sizeof(double)))
            expect_allele_freq = <double*>(calloc(self.base_type_num, sizeof(double)))

            EM(init_allele_frequecies,
               self.ind_allele_likelihood,
               marginal_likelihood, # update every loop
               expect_allele_freq,  # update every loop
               self.good_individual_num,
               self.base_type_num,
               100,  # EM iter_num
               0.001) # EM epsilon

            # bc.append(base_combs[i])
            bi = 0
            for bi in range(base_tuple.base_num):  # `base_tuple.base_num is equal with 'n'`
                # each element is single base
                base_tuple.base_comb_tuple[i][bi] = ord(base_combs_tuple[i][bi])

            # Todo: Should we use log10 function instead of using log or not? check it carefully!
            # sum the marginal likelihood
            base_tuple.alleles_freq_list[i] = expect_allele_freq
            base_tuple.sum_marginal_likelihood[i] = self.sum_likelihood(
                marginal_likelihood, self.good_individual_num, True)

            free(marginal_likelihood)
            free(init_allele_frequecies)

        return base_tuple

    cdef list _char_convert_to_list(self, char* data, int n):

        cdef list lst=[]
        cdef int i
        for i in range(n):
            lst.append(chr(data[i]))

        return lst

    cdef double sum_likelihood(self, double* data, int num, bint is_log):
        cdef double s = 0.0
        cdef int i = 0
        for i in range(num):
            if is_log:
                s += log(data[i])
            else:
                s += data[i]

        # a double-type value
        return s

    cdef bint lrt(self, list specific_base_comb):
        """The main function. likelihood ratio test.

        Parameter:
            ``specific_base_comb``: list like
                Calculating LRT for specific base combination
        """
        if self.total_depth == 0:
            return False

        cdef list bases = []
        if specific_base_comb:
            bases = [b for b in specific_base_comb
                     if self.depth[b] / self.total_depth >= self.min_af]
        else:
            bases = [b for b in CommonParameter.BASE
                     if self.depth[b] / self.total_depth >= self.min_af]

        cdef int bases_num = len(bases)
        if bases_num == 0:
            return False

        # init. Base combination will just be the ``bases`` if specific_base_comb
        cdef BaseTuple the_base_tuple = self._f(bases, bases_num)
        cdef double* base_frq = the_base_tuple.alleles_freq_list[0]
        cdef double lr_alt = the_base_tuple.sum_marginal_likelihood[0]

        cdef double chi_sqrt_value = 0
        cdef double* lrt_chivalue = NULL
        cdef int n
        cdef int i_min
        for n in range(1, len(bases))[::-1]:  # From complex to simple

            the_base_tuple = self._f(bases, n)
            lrt_chivalue = NULL
            lrt_chivalue = self.calculate_chivalue(lr_alt, the_base_tuple.sum_marginal_likelihood,
                                                   the_base_tuple.combination_num)

            i_min = self.find_argmin(lrt_chivalue, the_base_tuple.combination_num)
            lr_alt = the_base_tuple.sum_marginal_likelihood[i_min]
            chi_sqrt_value = lrt_chivalue[i_min]

            # Take the null hypothesis and continue
            if chi_sqrt_value < CommonParameter.LRT_THRESHOLD:
                # Todo: may happen a bug? becuase `bases` will be changed here everytime! Confirm on 2019-06-13 and it's not bug!

                bases = self._char_convert_to_list(the_base_tuple.base_comb_tuple[i_min], the_base_tuple.base_num)
                base_frq = the_base_tuple.alleles_freq_list[i_min]

            # Take the alternate hypothesis
            else:
                break

        # clear the_base_tuple
        the_base_tuple.destory_tuple()

        if lrt_chivalue != NULL:
            free(lrt_chivalue)

        self._alt_bases = [b for b in bases if b != self._ref_base]
        self.af_by_lrt = {b: "%.6f" % round(base_frq[CommonParameter.BASE2IDX[b]])
                          for b in bases if b != self._ref_base}
        base_frq = NULL

        # Todo: improve the calculation method for var_qual
        if len(self._alt_bases):

            r = self.depth[bases[0]] / self.total_depth
            if len(bases) == 1 and self.total_depth > 10 and r > 0.5:
                # mono-allelelic
                self._var_qual = 5000.0

            else:
                chi_prob = chi2.sf(chi_sqrt_value, 1)
                # self._var_qual = "%.2f" % round(-10 * log10(chi_prob)) if chi_prob > 0 else 10000.0
                self._var_qual = round(-10 * log10(chi_prob)) if chi_prob > 0 else 10000.0

            if self._var_qual == 0:
                # _var_qual will been setted as -0.0 instand of 0.0 if it's 0,
                # and I don't know why it's so weird!
                self._var_qual = 0.0

        return True

    cdef double* calculate_chivalue(self, double lr_alt, double* lr_null, int comb_num):

        cdef double* chi_value = <double*>(calloc(comb_num, sizeof(double)))
        cdef int i = 0
        for i in range(comb_num):
            chi_value[i] = 2 * (lr_alt - lr_null[i])

        return chi_value

    cdef int find_argmin(self, double* data, int comb_num):
        """Return indices of the minimum values along the given axis of `data`. """
        cdef int i = 0
        cdef int index = 0
        cdef double min_value = data[index]
        for i in range(1, comb_num):
            if data[i] < min_value:
                index = i
                min_value = data[i]

        return index

    def ref_base(self):
        return self._ref_base

    def alt_bases(self):
        return self._alt_bases

    def var_qual(self):
        return self._var_qual

    def debug(self):
        print(self.ref_base(), self.alt_bases(),
              self.var_qual(), self.depth, self.af_by_lrt)