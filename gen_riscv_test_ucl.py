#!/usr/bin/env python3
# TODO make each test case a separate file

"""
Generates a uclid module from a corresponding elf file form riscv-tests.
"""

from collections import defaultdict
from dataclasses import dataclass
from io import StringIO
import os
import re
import subprocess
import textwrap

OBJDUMP = "riscv64-unknown-elf-objdump"
# Exactly 8 hex digits, followed by a colon, then instruction hex, then the rest
TEXT_LINE_RE = re.compile("^([0-9a-f]{8}):\s+([0-9a-f]{8})\s+(.*)$")
TEXT_LABEL_RE = re.compile("^([0-9a-f]{8}) <([a-zA-Z][_0-9a-zA-Z]*)>:")
# This output comes from objdump -s instead of objdump -D
DATA_LINE_RE = re.compile("([0-9a-f]{8})\s+" * 5)

@dataclass
class ImemEntry:
    byte_addr: int
    inst_str: str
    comment: str

    def to_assume(self) -> str:
        inst_pc = "0x{:X}bv30".format(self.byte_addr >> 2)
        inst_hex = "0x" + self.inst_str.upper() + "bv32"
        return f"assume (imem[{inst_pc}] == {inst_hex}); // {self.byte_addr:X}: {self.comment}"

def parse_elf(elf_path):
    print("parsing file:", elf_path)
    text_p = subprocess.run([OBJDUMP, "-D", elf_path], stdout=subprocess.PIPE, check=True)
    reader = StringIO(text_p.stdout.decode("utf-8"))
    curr_section = ""
    curr_label = ""
    has_data = False
    # Each section that represents a test case gets its own file
    tests = defaultdict(list)
    start_insts = []
    fail_insts = []
    pass_insts = []
    fail_addr = None
    pass_addr = None
    pass_ecall_addr = None
    for line in reader.readlines():
        stripped = line.strip()
        if stripped.startswith("Disassembly of section "):
            # Last token is section name, which has a colon on the end
            curr_section = stripped.split()[-1][:-1]
        elif curr_section == ".text.init":
            m = re.match(TEXT_LINE_RE, stripped)
            m2 = re.match(TEXT_LABEL_RE, stripped)
            if m:
                inst_comment = m.group(3).strip().replace("\t", " ").replace(",", ", ")
                new_entry = ImemEntry(int(m.group(1), 16), m.group(2).upper(), inst_comment)
                if curr_label.startswith("test_"):
                    tests[curr_label].append(new_entry)
                elif curr_label == "fail":
                    fail_insts.append(new_entry)
                elif curr_label == "pass":
                    pass_insts.append(new_entry)
                    if new_entry.inst_str == "00000073":
                        pass_ecall_addr = new_entry.byte_addr
            elif m2:
                label_addr_i = int(m2.group(1), 16)
                new_label = m2.group(2)
                # Skip over labels like "linkaddr" and "target" that appear mid-test
                if new_label.startswith("test_"):
                    curr_label = m2.group(2)
                elif new_label == "pass":
                    pass_addr = label_addr_i
                    curr_label = new_label
                elif new_label == "fail":
                    fail_addr = label_addr_i
                    curr_label = new_label
        elif curr_section == ".data":
            has_data = True            
    assert fail_addr is not None, "Could not find <fail> label"
    assert pass_addr is not None, "Could not find <pass> label"
    assert pass_addr is not None, "Could not find ecall instruction in <pass> label"
    reader.close()
    # For some reason objdump -D doesn't show all data, so we need to do a second pass
    data_lines = []
    if has_data:
        data_p = subprocess.run([OBJDUMP, "-s", "-j", ".data", elf_path], stdout=subprocess.PIPE, check=True)
        started_data = False
        reader = StringIO(data_p.stdout.decode("utf-8"))
        for line in reader.readlines():
            stripped = line.strip()
            if stripped.startswith("Contents of section .data"):
                started_data = True
            elif started_data:
                m = re.match(DATA_LINE_RE, stripped)
                if m:
                    starting_addr_i = int(m.group(1), 16) >> 2
                    words = ["0x" + m.group(i).upper() + "bv32" for i in range(2, 6)]
                    for i, data in enumerate(words):
                        data_lines.append(f"assume (cpu_0.dmem[0x{'{:X}'.format(starting_addr_i + i)}bv30] == {data});")
        reader.close()
    tcount = len(tests)
    PC_START = 0x80000000
    for i, (t, t_entries) in enumerate(tests.items()):
        first_addr = t_entries[0].byte_addr
        # If necessary, add jump instruction to reach first test
        if first_addr != PC_START:
            j_dist = first_addr - PC_START
            j_inst = "{:05X}06F".format(j_dist << 8)
            t_entries.insert(0, ImemEntry(PC_START, j_inst, f"j {first_addr:X} (AUTOMATICALLY INSERTED)"))
        # If this is not the last test, add jump instruction to reach <pass> label
        if i != tcount - 1:
            # Add new j instruction 1 after the last instruction in the test
            new_j_pc = t_entries[-1].byte_addr + 4
            j_dist = pass_addr - new_j_pc
            j_inst = "{:05X}06F".format(j_dist << 8)
            t_entries.append(ImemEntry(new_j_pc, j_inst, f"j {pass_addr:X} <pass> (AUTOMATICALLY INSERTED)"))
        tlines = [e.to_assume() for e in t_entries] + ["// <fail>"] + [e.to_assume() for e in fail_insts] + ["// <pass>"] + [e.to_assume() for e in pass_insts]
        last_pass_inst_loc = "0x{:X}bv30".format(pass_insts[-1].byte_addr >> 2)
        tlines.append("// unimp instructions - these should cause X_INVALID_INST if hit")
        tlines.append(
            f"assume (forall (a : mem_word_addr_t) :: (a < IMEM_PC_START || a > {last_pass_inst_loc}) ==> imem[a] == instructions.UNIMP);"
        )
        # If this is not the last test (which is right before fail/pass), also add a bunch of unimps
        if i != tcount - 1:
            tlines.append(
                    f"assume (forall (a : mem_word_addr_t) :: (a > 0x{t_entries[-1].byte_addr >> 2:X}bv30 && a < 0x{fail_addr >> 2:X}bv30) ==> imem[a] == instructions.UNIMP);"
            )
        if data_lines:
            tlines.append("// Data segment")
            tlines.extend(data_lines)
        init_block = '\n'.join(tlines)
        expected_epc = f"0x{pass_ecall_addr:X}bv32"
        # Add an arbitrary number of cycles to make sure the program actually exits (some have loops, so we can't depend
        # on the number of instructions)
        last_step = len(t_entries) + max(len(fail_insts), len(pass_insts)) + 5
        s = textwrap.dedent(f"""\
            // AUTOGENERATED FROM {elf_path} BY {__file__}
            // ({i + 1} of {tcount})
            module main {{
                type * = common.*;
                define * = common.*;
                type * = instructions.*;
                const * = cpu.*;

                var imem : mem_t;
                var step : integer;

                instance cpu_0 : cpu (imem : (imem));

                init {{
{textwrap.indent(init_block, ' ' * 20)}
                    step = 0;
                }}

                next {{
                    next (cpu_0);
                    step' = step + 1;
                }}

                // All tests are ended with an ECALL invocation
                // TODO run BMC to check LTL properties
                // property[LTL] eventually_exits: G(F(cpu_0.exception.cause == X_ECALL && cpu_0.regfile[registers.a0] == 0bv32));
                // No exception occurred until the <pass> ecall instruction was reached
                invariant no_exception: (cpu_0.exception.cause == X_NONE || (cpu_0.exception.cause == X_ECALL && cpu_0.regfile[registers.a0] == 0bv32 && cpu_0.exception.epc == {expected_epc}));
                // At the end of the simulation, the program exited via <pass> ecall
                invariant exits_ecall: ((step == {last_step}) ==> (cpu_0.exception.cause == X_ECALL && cpu_0.regfile[registers.a0] == 0bv32 && cpu_0.exception.epc == {expected_epc}));

                control {{
                    vobj = bmc_noLTL({last_step});
                    check;
                    print_results;
                    vobj.print_cex(cpu_0.pc, cpu_0.exception, cpu_0.regfile, cpu_0.dmem);
                }}
            }}""")
        os.makedirs(os.path.join("autogen-riscv-tests", os.path.basename(elf_path)), exist_ok=True)
        with open(os.path.join("autogen-riscv-tests", os.path.basename(elf_path), t + ".ucl"), "w") as f:
            f.write(s)

if __name__ == "__main__":
    for file in os.listdir("riscv-tests"):
        filename = os.fsdecode(file)
        if filename.startswith("rv32ui-p-") and "." not in filename:
            parse_elf(os.path.join("riscv-tests", filename))

