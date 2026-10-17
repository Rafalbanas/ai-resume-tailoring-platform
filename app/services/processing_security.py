"""Kernel policy inherited by native parsers and Chromium subprocesses."""
import ctypes
import ctypes.util
import errno
import socket


def restrict_network():
    name = ctypes.util.find_library('seccomp')
    if not name:
        raise RuntimeError('libseccomp is required for isolated processing')
    lib = ctypes.CDLL(name, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    context = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW; libseccomp sets no_new_privs.
    if not context:
        raise RuntimeError('Cannot initialize processing sandbox')
    deny = 0x00050000 | errno.EPERM
    class Comparison(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint), ('a', ctypes.c_uint64), ('b', ctypes.c_uint64)]
    try:
        syscall = lib.seccomp_syscall_resolve_name(b'socket')
        for family in (socket.AF_INET, socket.AF_INET6, socket.AF_NETLINK):
            if lib.seccomp_rule_add(context, deny, syscall, 1, Comparison(0, 4, family, 0)) < 0:
                raise RuntimeError('Cannot restrict processing sockets')
        for name in ('ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd',
                     'bpf', 'perf_event_open', 'io_uring_setup', 'open_by_handle_at', 'mount', 'setns'):
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and lib.seccomp_rule_add(context, deny, number, 0) < 0:
                raise RuntimeError('Cannot restrict processing system calls')
        if lib.seccomp_load(context) < 0:
            raise RuntimeError('Cannot load processing sandbox')
    finally:
        lib.seccomp_release(context)
