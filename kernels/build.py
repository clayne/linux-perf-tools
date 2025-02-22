#!/usr/bin/env python3
# Copyright (c) 2020-2024, Intel Corporation
# Authors: Ahmad Yasin, Sinduri Gundu
#
#   This program is free software; you can redistribute it and/or modify it under the terms and conditions of the
# GNU General Public License, version 2, as published by the Free Software Foundation.
#   This program is distributed in the hope it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

import argparse, os, subprocess, sys

assert sys.version_info.major >=3, "Python version 3.0 or higher is required."

cwd = os.getcwd()
sys.path.append(cwd[:cwd.rfind('kernels')]) #Add directory containing pmu.py to the path
from pmu import goldencove_on, server, cpu_pipeline_width
from common import exe_cmd

parser = argparse.ArgumentParser(
            prog='build.py',
            description='Generates kernel source code and builds them'
            )
parser.add_argument('--CC', default='gcc -g -O2', help='compiler and flags', required=False)
parser.add_argument('--GEN', type=int, default=1, help='1 = generate kernel source code; 0 = skip this step; Default = 1', required=False)
parser.add_argument('--PY', default='python3', help='Python version', required=False)
parser.add_argument('--RF', type=int, default=0, help='1 = generate rfetch kernels; 0 = skip this step; Default = 1', required=False)
args = parser.parse_args()

kernels = []
pipelineWidth = cpu_pipeline_width()

#generate source code with gen-kernel script.
#print command to screen
def gen_kernel(params, filename):
    gen_kernel_command = '{python} ./gen-kernel.py {params}'.format(python=args.PY, params=params)
    exe_cmd(gen_kernel_command, redir_out=' > '+filename+'.c', debug=True)
    kernels.append(filename)

def build_kernel(source, output=None, flags=''):
    if output is None:
        output = source
    build_command = '{CC} {flags} {source}.c -o {output}'.format(CC=args.CC, flags=flags, source=source, output=output)
    exe_cmd(build_command, debug=True)

if args.GEN:
    gen_kernel("jumpy-seq -n 13 -i JMP -a 15", 'jumpy13b15') 
    gen_kernel("jumpy-seq -n 13 -i JMP -a 13", 'jumpy13b13')
    gen_kernel("jumpy-seq -n 9 -i JMP -a 17", 'itlb-miss-stlb-hit')

    subprocess.run('{CC} -S jumpy5p14.c'.format(CC=args.CC), shell=True)
    kernels.append("jumpy5p14")

    gen_kernel("-i 'addps %xmm1,%xmm2' 'vsubps %ymm1,%ymm2,%ymm3' -n10", 'sse2avx')

    gen_kernel("-i NOP#{nopCount} 'test %rax,%rax' 'jle Lbl_end' -n 1 -a 6 --init-regs rax".format(nopCount=(pipelineWidth-3)), 'peak'+str(pipelineWidth)+'wide')
    gen_kernel("jumpy-seq -i NOP JMP -a3 -n30", 'dsb-jmp')
    gen_kernel("jumpy-seq -i JG -a 6 -n 20000", 'jcc20k')
    gen_kernel("jumpy-random -a 6 -i JMP -n 1024", 'rfetch64k')

    if args.RF:
        gen_kernel("jumpy-random -a 5 -i NOP5#30 JMP -n 19661", 'rfetch3m')
        gen_kernel("jumpy-random -a 5 -i NOP5#56 JMP -n 10923", 'rfetch3m-ic')

    for x in ['add', 'mul']:
        gen_kernel("-i 'v{x}pd %ymm@,%ymm@,%ymm@' -r16 -n1 --reference MGM".format(x=x), 'fp-{x}-bw'.format(x=x))
        gen_kernel("-i 'v{x}pd %ymm@-1,%ymm@,%ymm@' -r16 -n10 --reference MGM".format(x=x), 'fp-{x}-lat'.format(x=x))
        if server():
            gen_kernel("-i 'v{x}pd %zmm0,%zmm1,%zmm2' 'v{x}pd %zmm3,%zmm4,%zmm5' NOP 'mov (%rsp),%rbx' -n1".format(x=x), 'fp-{x}-512'.format(x=x))

    gen_kernel("-i 'vdivps %ymm@,%ymm@,%ymm@' -r3 -n1", 'fp-divps')
    gen_kernel("-i 'vfmadd132pd %ymm10,%ymm11,%ymm11' 'vfmadd132ps %ymm12,%ymm13,%ymm13' 'vaddpd %xmm0,%xmm0,%xmm0' 'vaddps %xmm1,%xmm1,%xmm1' 'vsubsd %xmm2,%xmm2,%xmm2' 'vsubss %xmm3,%xmm3,%xmm3' -n1 --reference 'ICL-PMU'", 'fp-arith-mix')
    gen_kernel("-i 'xor %eax,%eax' 'xor %ecx,%ecx' cpuid -n1", 'cpuid')
    
    gen_kernel("-i NOP#2 'mov 0x0(%rsp),%r12' 'test %r12,%r12' 'jg Lbl_end' -n 106", 'ld-cmp-jcc-3i')
    gen_kernel("-i NOP#2 'cmpq $0x0,0x0(%rsp)' 'jg Lbl_end' -n 106", 'ld-cmp-jcc-2i-imm')
    gen_kernel("-i NOP#2 'cmpq %r12,0x0(%rsp)' 'jg Lbl_end' -n 106 -p 'movq $0x0,%r12'", 'ld-cmp-jcc-2i-reg')
    gen_kernel("-i 'mov 0x0(%rsp),%r12' 'test %r12,%r12' 'jg Lbl_end' 'inc %rsp' 'dec %rsp' -n 1", 'ld-cmp-jcc-3i-inc')
    gen_kernel("-i 'cmpq $0x0,0x0(%rsp)' 'jg Lbl_end' 'inc %rsp' 'dec %rsp' -n 1", 'ld-cmp-jcc-2i-imm-inc')
    gen_kernel("-i 'cmpq %r12,0x0(%rsp)' 'jg Lbl_end' 'inc %r12' 'dec %r12' -p 'movq $0x0,%r12' -n 1", 'ld-cmp-jcc-2i-reg-inc')
    gen_kernel("-p 'mov %rsp,%rdx' 'sub $0x40000,%rdx' -i 'cmpl $0,0x40000(,%rdx,1)' -n 100", 'cmp0-mem-index')
    gen_kernel("-i 'vshufps $0xff,%ymm0,%ymm1,%ymm2' 'vshufps $0xff,%ymm3,%ymm4,%ymm5' NOP 'mov (%rsp),%rbx' 'test %rax, %rax' 'jle Lbl_end' 'inc %rcx' --init-regs rax", 'vshufps')
    gen_kernel("-i 'vpshufb %ymm0,%ymm1,%ymm2' 'vpshufb %ymm3,%ymm4,%ymm5' NOP 'mov (%rsp),%rbx' 'test %rax, %rax' 'jle Lbl_end' 'inc %rcx' --init-regs rax", 'vpshufb')
    gen_kernel("-i 'mov 0x0(%rsp),%r12' 'add %r13,%r12' NOP -n 14", 'ld-op-nop')
    gen_kernel("-i 'mov %r13,%r12' 'add %r14,%r12' NOP -n 14", 'mov-op-nop')
    gen_kernel("-i 'mov 0x0(%rsp),%r12' NOP 'add %r13,%r12' -n 14", 'ld-nop-op')
    gen_kernel("-i 'mov %r13,%r12' NOP 'add %r14,%r12' -n 14", 'mov-nop-op')
    gen_kernel("-i 'incq (%rsp,%rdx,1)' 'decq (%rsp,%rdx,1)' -n16", 'incdec-mrn-cancel')
    gen_kernel("-i 'incq (%rsp,1)' 'decq (%rsp,1)' -n16", 'incdec-mrn')
    gen_kernel("-i 'movq (%rsp,%rdx,1), %rcx' 'addq $1, (%rsp,%rdx,1)' -n16" , 'ldst-mrn-cancel')
    gen_kernel("-i 'movq (%rsp,1), %rcx' 'addq $1, (%rsp,1)' -n16", 'ldst-mrn')
    gen_kernel("-i 'movups (%rsp),%xmm1' 'andps %xmm2, %xmm1' NOP -n 14", 'v-ld-op-nop')
    gen_kernel("-i 'movdqa %xmm1,%xmm2' 'andps %xmm3, %xmm2' NOP -n 14", 'v-mov-op-nop')
    gen_kernel("-i 'movups (%rsp),%xmm1' NOP 'andps %xmm2, %xmm1' -n 14", 'v-ld-nop-op')
    gen_kernel("-i 'movdqa %xmm1,%xmm2' NOP 'andps %xmm3, %xmm2' -n 14", 'v-mov-nop-op')
    gen_kernel("-i 'cvtsd2si %xmm0,%r8d' -n64 ",'v2i')
    gen_kernel("-i 'comiss 0x100(%rsp),%xmm0' -n64 ",'i2v')
    gen_kernel("-i 'movw $0x1, %ax' -n4000 ",'lcp')
    gen_kernel("-i 'Lbl_head:' 'add $1, %r9' 'mov %r9, %r8' 'and $0xf, %r8' 'cmp $1, %r8' 'jz Lbl_head' 'cmp $2, %r8' 'jz Lbl_head' "
               "'cmp $3, %r8' 'jz Lbl_head' 'cmp $4, %r8' 'jz Lbl_head' 'cmp $5, %r8' 'jz Lbl_head' 'cmp $6, %r8' 'jz Lbl_head' "
               "'cmp $7, %r8' 'jz Lbl_head' 'sub $1, %r9' -n1 --modify-regs", 'loop-jccx7')
    gen_kernel("-i 'Lbl_head:' 'add $1, %r9' 'mov %r9, %r8' 'and $0xf, %r8' 'cmp $1, %r8' 'jz Lbl_head' 'cmp $2, %r8' 'jz Lbl_head' "
               "'cmp $3, %r8' 'jz Lbl_head' 'cmp $4, %r8' 'jz Lbl_head' 'cmp $5, %r8' 'jz Lbl_head' 'cmp $6, %r8' 'jz Lbl_head' "
               "'cmp $7, %r8' 'jz Lbl_head' 'cmp $8, %r8' 'jz Lbl_head' 'sub $1, %r9' -n1 --modify-regs", 'loop-jccx8')
    gen_kernel("-i 'Lbl_head:' 'add $1, %r9' 'mov %r9, %r8' 'and $0xf, %r8' 'cmp $1, %r8' 'jz Lbl_head' 'cmp $2, %r8' 'jz Lbl_head' "
               "'cmp $3, %r8' 'jz Lbl_head' 'cmp $4, %r8' 'jz Lbl_head' 'cmp $5, %r8' 'jz Lbl_head' 'cmp $6, %r8' 'jz Lbl_head' "
               "'cmp $7, %r8' 'jz Lbl_head' 'cmp $8, %r8' 'jz Lbl_head' 'cmp $9, %r8' 'jz Lbl_head' "
               "'sub $1, %r9' -n1 --modify-regs", 'loop-jccx9')
    kernels.append("memcpy")
    kernels.append("pagefault")
    kernels.append("tripcount-mean")
    kernels.append("store_fwd_block")

    if args.RF > 1:
        exe_cmd("wget https://raw.githubusercontent.com/facebookresearch/DCPerf/refs/heads/main/packages/django_workload/templates/gen_icache_buster.py")

#kernels.append('cond_jmp')
print(kernels)

for kernel in kernels:
    build_kernel(kernel)

#Special Builds
build_kernel('callchain', flags='-O0 -fno-inline')
build_kernel('false-sharing', flags='-O0 -pthread')
build_kernel('cond_jmp', flags='-O0')
if goldencove_on():
    build_kernel('tpause', flags='-march=native')# requires newer GCC and binutils
build_kernel('tpause', output='rdtsc', flags='-march=native -DRDTSC_ONLY')

