cdef force_str(object s, encoding=*)
cdef charptr_to_str(const char *s, encoding=*)
# cdef charptr_to_str_w_len(const char* s, size_t n, encoding=*)
cdef bytes force_bytes(object s, encoding=*)
cdef bytes encode_filename(object filename)
