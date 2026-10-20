#!/usr/bin/env python3
"""Prepare a worawit/blutter checkout for building the fiet-win-dart engine.

Derived from QIUHONG520/fler-dart scripts/build-dartvm.sh (pinned blutter commit
4a60ac648bf448c5a7596437243bcd0b9376fdf0). Only source patches required for the
wrapper/DLL build are applied here; Android/NDK-specific steps are not.

The patch set is idempotent and one tree supports multiple Dart versions through
a compile-time feature macro (BLUTTER_DART_3_13_SINGLE_SNAPSHOT, set by CMake):

  1. DartApp.h: fler_libs()/fler_native_lib() accessors (direct in-memory export)
  2. DartDumper.h: FlPoolDescription() wrapper
  3. FridaWriter.cpp: tolerant frida.template.js copy
  4. CodeAnalyzer*: write-barrier false-positive ASSERT -> InsnException guard
  5. patches/patch-blutter-robust.py (bounds checks / per-function recovery /
     Dart 2.14-3.12 compatibility)
  6. DartLoader.cpp: Dart_ExitIsolate before Dart_ShutdownIsolate (VM reuse)
  7. Dart VM CMake template: MSVC /Zc:preprocessor /utf-8
  8. Dart >=3.13 "single snapshot": OBJECT_STORE_STUB_CODE_LIST was removed;
     predefined stubs are only exposed via dart::StubCode. DartStub enum and
     DartApp::loadStubs get a conditional branch while <=3.12 keeps the old one.

Usage: python scripts/prepare_blutter.py <blutter_dir>
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROBUST_PATCH = os.path.join(HERE, "patches", "patch-blutter-robust.py")
EXPECTED_COMMIT = "4a60ac648bf448c5a7596437243bcd0b9376fdf0"


def log(msg):
    print(f"[prepare_blutter] {msg}", flush=True)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def patch_dartapp_h(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "DartApp.h")
    s = read(path)
    if "fler_libs" not in s:
        accessor = (
            "\n\t// fler-dart: accessors for direct in-memory DB export\n"
            "\tconst std::vector<DartLibrary*>& fler_libs() const { return libs; }\n"
            "\tDartLibrary* fler_native_lib() { return &nativeLib; }\n\n"
        )
        needle = "\nprivate:\n"
        assert needle in s, "DartApp.h private: marker not found"
        write(path, s.replace(needle, accessor + needle, 1))
        log("DartApp.h: accessors added")
    elif "fler_native_lib" not in s:
        needle = "\tconst std::vector<DartLibrary*>& fler_libs() const { return libs; }"
        write(path, s.replace(needle, needle + "\n\tDartLibrary* fler_native_lib() { return &nativeLib; }", 1))
        log("DartApp.h: fler_native_lib() added")
    else:
        log("DartApp.h: already patched")


def patch_dartdumper_h(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "DartDumper.h")
    s = read(path)
    if "FlPoolDescription" in s:
        log("DartDumper.h: already patched")
        return
    wrapper = (
        "\n\t// fler-dart: expose pool description for direct in-memory DB export\n"
        "\tstd::string FlPoolDescription(intptr_t offset, bool simpleForm = true) {\n"
        "\t\treturn getPoolObjectDescription(offset, simpleForm);\n"
        "\t}\n\n"
    )
    needle = "\nprivate:\n"
    assert needle in s, "DartDumper.h private: marker not found"
    write(path, s.replace(needle, wrapper + needle, 1))
    log("DartDumper.h: FlPoolDescription() added")


def patch_fridawriter(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "FridaWriter.cpp")
    s = read(path)
    if "fler-dart tolerant template" in s:
        log("FridaWriter.cpp: already patched")
        return
    old = (
        'std::filesystem::copy_file(FRIDA_TEMPLATE_DIR "/frida.template.js", filename, '
        "std::filesystem::copy_options::overwrite_existing);"
    )
    new = (
        "// fler-dart tolerant template copy: missing template no longer crashes\n"
        "std::error_code _ec;\n"
        'std::filesystem::copy_file(FRIDA_TEMPLATE_DIR "/frida.template.js", filename,\n'
        "    std::filesystem::copy_options::overwrite_existing, _ec);"
    )
    assert old in s, "FridaWriter.cpp copy_file pattern not found"
    write(path, s.replace(old, new))
    log("FridaWriter.cpp: tolerant template copy applied")


def patch_write_barrier(blutter_dir):
    root = os.path.join(blutter_dir, "blutter", "src")
    count = 0
    for name in ("CodeAnalyzer.cpp", "CodeAnalyzer_arm64.cpp"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        out = []
        changed = False
        for line in read(path).splitlines(True):
            if "CSREG_DART_HEAP" in line and re.search(r"\b(?:ASSERT|RELEASE_ASSERT|FATAL)\s*\(", line):
                indent = line[: len(line) - len(line.lstrip())]
                out.append(indent + 'throw InsnException("write barrier register mismatch", insn); // fler-dart wb-guard\n')
                count += 1
                changed = True
            else:
                out.append(line)
        if changed:
            write(path, "".join(out))
    log(f"write-barrier assertion guards added: {count}")


def patch_robust(blutter_dir):
    root = os.path.join(blutter_dir, "blutter", "src")
    if not os.path.isfile(ROBUST_PATCH):
        raise SystemExit(f"missing {ROBUST_PATCH}")
    log("applying patch-blutter-robust.py ...")
    subprocess.run([sys.executable, ROBUST_PATCH, root], check=True)


def patch_dartloader(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "DartLoader.cpp")
    if not os.path.isfile(path):
        log("DartLoader.cpp not found, skip")
        return
    s = read(path)
    if "fler-dart isolate-detach" in s:
        log("DartLoader.cpp: already patched")
        return
    old = "\t\tDart_ShutdownIsolate();"
    if old not in s:
        log("WARN: DartLoader shutdown target not found")
        return
    new = (
        "\t\t// fler-dart isolate-detach: detach before shutdown so the thread\n"
        "\t\t// can create the next isolate when the App reuses this IO thread.\n"
        "\t\tDart_ExitIsolate();\n"
        "\t\tDart_ShutdownIsolate();"
    )
    write(path, s.replace(old, new, 1))
    log("DartLoader.cpp: isolate detach added")



def patch_dartvm_cpp20(blutter_dir):
    """MSVC 需要 C++20 才能编译 Dart 2.14 等旧 SDK（designated initializers 等）。

    Dart 3.11+ 的 SDK 自己声明 c++20；更老版本源码里 run_clang_tidy.dart 给的
    标准可能是 c++17，MSVC 严格模式下会报 C7555。这里在 Windows 上统一提到 20。
    """
    path = os.path.join(blutter_dir, "dartvm_fetch_build.py")
    if not os.path.isfile(path):
        log("dartvm_fetch_build.py not found, skip c++20 patch")
        return
    s = read(path)
    old = '        cpp_std = "17" if pos == -1 else content[pos+8:pos+10]'
    new = (old
           + '\n        # FIET Windows patch: MSVC needs C++20 for designated initializers'
           + '\n        # in older Dart VM sources (e.g. message_snapshot.cc in Dart 2.14).'
           + '\n        if os.name == "nt":'
           + '\n            cpp_std = "20"')
    if 'FIET Windows patch: MSVC needs C++20' in s:
        log("dartvm_fetch_build.py: c++20 patch already present")
        return
    if old not in s:
        log("WARN: dartvm_fetch_build.py cpp_std line not found")
        return
    write(path, s.replace(old, new, 1))
    log("dartvm_fetch_build.py: c++20 forced on Windows")


def patch_dartvm_cmake_template(blutter_dir):
    path = os.path.join(blutter_dir, "scripts", "CMakeLists.txt")
    s = read(path)
    changed = False
    if "/Zc:preprocessor" not in s:
        s = s.replace("/Oy /GR- /EHs-c-", "/Oy /GR- /EHs-c- /Zc:preprocessor", 1)
        changed = True
    if "/utf-8" not in s:
        s = s.replace("/Zc:preprocessor", "/Zc:preprocessor /utf-8", 1)
        changed = True
    if changed:
        write(path, s)
        log("Dart VM CMake template: MSVC /Zc:preprocessor /utf-8 added")
    else:
        log("Dart VM CMake template: already patched")


# ─── Dart 3.13+ single-snapshot support ───────────────────────────────────────
DART_STUB_313_ENUM = """	enum Kind : int32_t {
#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
		// Dart 3.13 "single snapshot": predefined stubs moved from ObjectStore to
		// dart::StubCode (VM_STUB_CODE_LIST is the single source of truth and
		// also expands VM_TYPE_TESTING_STUB_CODE_LIST). Keep the historic
		// `name##Stub` spelling because CodeAnalyzer compares against these kinds.
#define DO(name) name ## Stub,
		VM_STUB_CODE_LIST(DO)
#undef DO
#else
#define DO(member, name) name ## Stub,
		OBJECT_STORE_STUB_CODE_LIST(DO)
#undef DO
#endif
		BuildNonGenericMethodExtractorStub,
		BuildGenericMethodExtractorStub,
#if !defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
#define DO(name) name ## VMStub,
		VM_STUB_CODE_LIST(DO)
#undef DO
#endif
		SharedStub,
		AllocateUserObjectStub,
		TypeCheckStub,
		UnknownStub,
	};"""

DART_STUB_313_LOADSTUBS = """#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
	// Dart 3.13 single-snapshot: all predefined stubs are VM stubs exposed by
	// dart::StubCode; there are no isolate-specific "_iso_stub_" ObjectStore
	// copies anymore, so the ObjectStore loop is skipped and throw comes from
	// StubCode as well.
	(void)ptr;
	(void)store;
	code = dart::StubCode::Throw();
	throwStubAddr = code.EntryPoint();

#define DO(name) {\\
		const auto& stubCode = dart::StubCode::name(); \\
		ep_addr = stubCode.EntryPoint() - base(); \\
		if (stubs.contains(ep_addr)) { \\
			ASSERT(stubs[ep_addr]->Name() == #name); \\
		} else { \\
			stub = new DartStub(stubCode.ptr(), DartStub::name ## Stub, ep_addr, stubCode.Size(), #name); \\
			stubs[ep_addr] = stub; \\
			auto it = functions.find(ep_addr); \\
			if (it != functions.end()) { \\
				auto dartFn = it->second; \\
				std::erase(dartFn->Class().functions, dartFn); \\
				functions.erase(it); \\
			} \\
		} \\
	}
	VM_STUB_CODE_LIST(DO);
#undef DO
#else"""


def patch_dart313_stub_support(blutter_dir):
    src = os.path.join(blutter_dir, "blutter", "src")
    stub_h = os.path.join(src, "DartStub.h")
    app_cpp = os.path.join(src, "DartApp.cpp")

    s = read(stub_h)
    if "BLUTTER_DART_3_13_SINGLE_SNAPSHOT" not in s:
        start = s.index("\tenum Kind : int32_t {")
        end = s.index("\n\t};", start) + len("\n\t};")
        write(stub_h, s[:start] + DART_STUB_313_ENUM + s[end:])
        log("DartStub.h: Dart 3.13 single-snapshot enum branch added")
    else:
        log("DartStub.h: Dart 3.13 branch already present")

    s = read(app_cpp)
    if "BLUTTER_DART_3_13_SINGLE_SNAPSHOT" in s:
        log("DartApp.cpp: Dart 3.13 branch already present")
        return
    start_marker = "\t// Note: some stub might contain multiple of duplicated stubs"
    end_marker = "\tVM_STUB_CODE_LIST(DO);\n#undef DO"
    start = s.index(start_marker)
    end = s.index(end_marker, start) + len(end_marker)
    old_block = s[start:end]
    write(app_cpp, s[:start] + DART_STUB_313_LOADSTUBS + "\n" + old_block + "\n#endif" + s[end:])
    log("DartApp.cpp: conditional Dart 3.13 loadStubs branch added")


def patch_dart313_api_changes(blutter_dir):
    """Dart 3.13 API/layout changes beyond the stub lists.

    3.13 "single snapshot" also changed:
      * snapshot symbols: kVm*/kIsolate*AsmSymbol -> kSnapshotData/TextAsmSymbol
        (libapp.so carries one data+text pair only)
      * Dart_InitializeParams: vm_snapshot_data/instructions removed (snapshot is
        passed to Dart_CreateIsolateGroup instead)
      * AOT Closure layout: context / delayed_type_arguments fields removed
      * Code::operator=(const Code&) deleted (assign CodePtr instead)
    """
    src = os.path.join(blutter_dir, "blutter", "src")
    marker = "BLUTTER_DART_3_13_SINGLE_SNAPSHOT"

    # ── ElfHelper: snapshot symbol names + single-snapshot aliasing ──────────
    elf = os.path.join(src, "ElfHelper.cpp")
    s = read(elf)
    if "FLER_SNAPSHOT_DATA_SYM" not in s:
        # Replace the symbol tokens first, then add the macro definitions (doing it
        # the other way round would rewrite the definitions themselves into
        # self-referential macros).
        s = s.replace("kVmSnapshotDataAsmSymbol", "FLER_SNAPSHOT_DATA_SYM")
        s = s.replace("kVmSnapshotInstructionsAsmSymbol", "FLER_SNAPSHOT_TEXT_SYM")
        s = s.replace("kIsolateSnapshotDataAsmSymbol", "FLER_ISOLATE_DATA_SYM")
        s = s.replace("kIsolateSnapshotInstructionsAsmSymbol", "FLER_ISOLATE_TEXT_SYM")
        NL = chr(10)
        TAB = chr(9)
        defines = read(os.path.join(HERE, "patches", "dart313_elfhelper_macros.txt"))
        s = s.replace("#include <stdexcept>", defines + "#include <stdexcept>", 1)
        anchor = "if (vm_snapshot_data == nullptr)"
        block = (
            "#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)" + NL
            + TAB + "isolate_snapshot_data = vm_snapshot_data;" + NL
            + TAB + "isolate_snapshot_instructions = vm_snapshot_instructions;" + NL
            + "#endif" + NL
            + TAB + anchor
        )
        s = s.replace(TAB + anchor, block, 1)
        write(elf, s)
        log("ElfHelper.cpp: Dart 3.13 snapshot symbol mapping added")
    else:
        fixed = s
        for bad, good in (
            ("#define FLER_SNAPSHOT_DATA_SYM FLER_SNAPSHOT_DATA_SYM", "#define FLER_SNAPSHOT_DATA_SYM kVmSnapshotDataAsmSymbol"),
            ("#define FLER_SNAPSHOT_TEXT_SYM FLER_SNAPSHOT_TEXT_SYM", "#define FLER_SNAPSHOT_TEXT_SYM kVmSnapshotInstructionsAsmSymbol"),
            ("#define FLER_ISOLATE_DATA_SYM FLER_ISOLATE_DATA_SYM", "#define FLER_ISOLATE_DATA_SYM kIsolateSnapshotDataAsmSymbol"),
            ("#define FLER_ISOLATE_TEXT_SYM FLER_ISOLATE_TEXT_SYM", "#define FLER_ISOLATE_TEXT_SYM kIsolateSnapshotInstructionsAsmSymbol"),
        ):
            fixed = fixed.replace(bad, good)
        if fixed != s:
            write(elf, fixed)
            log("ElfHelper.cpp: repaired recursive symbol macro definitions")
        else:
            log("ElfHelper.cpp: Dart 3.13 mapping already present")

    # ── DartLoader: Dart_InitializeParams has no vm_snapshot_* in 3.13 ──────
    loader = os.path.join(src, "DartLoader.cpp")
    s = read(loader)
    if "Dart 3.13: snapshot moved" not in s:
        s = s.replace(
            "\tinit_params.vm_snapshot_data = vm_snapshot_data;\n"
            "\tinit_params.vm_snapshot_instructions = vm_snapshot_instructions;",
            """#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
\t// Dart 3.13: snapshot moved from Dart_InitializeParams to
\t// Dart_CreateIsolateGroup; nothing to set here.
\t(void)vm_snapshot_data;
\t(void)vm_snapshot_instructions;
#else
\tinit_params.vm_snapshot_data = vm_snapshot_data;
\tinit_params.vm_snapshot_instructions = vm_snapshot_instructions;
#endif""",
            1,
        )
        write(loader, s)
        log("DartLoader.cpp: Dart 3.13 initialize-params branch added")
    else:
        log("DartLoader.cpp: Dart 3.13 branch already present")

    # ── DartApp: Code::operator=(const Code&) is deleted in Dart 3.13 ──────
    app = os.path.join(src, "DartApp.cpp")
    s = read(app)
    if "dart::StubCode::Throw().ptr()" not in s:
        s = s.replace(
            "code = dart::StubCode::Throw();",
            "code = dart::StubCode::Throw().ptr();",
            1,
        )
        write(app, s)
        log("DartApp.cpp: throw stub assigned as CodePtr (Dart 3.13)")
    else:
        log("DartApp.cpp: throw stub already patched")

    # ── FridaWriter: closure context offset removed in Dart 3.13 ───────────
    frida = os.path.join(src, "FridaWriter.cpp")
    s = read(frida)
    if "contextOffset:-1" not in s:
        s = s.replace(
            'of << "contextOffset:" << AOT_Closure_context_offset << ",";',
            """#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
\t\t\t\tof << "contextOffset:-1,";
#else
\t\t\t\tof << "contextOffset:" << AOT_Closure_context_offset << ",";
#endif""",
            1,
        )
        write(frida, s)
        log("FridaWriter.cpp: Dart 3.13 closure context offset guarded")
    else:
        log("FridaWriter.cpp: Dart 3.13 already patched")

    # ── CodeAnalyzer_arm64: removed Closure field offsets -> sentinel ──────
    car = os.path.join(src, "CodeAnalyzer_arm64.cpp")
    s = read(car)
    if "FLER_DART_313_CLOSURE_SENTINEL" not in s:
        s = s.replace(
            "#include <unordered_set>",
            """#include <unordered_set>

#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
// FLER_DART_313_CLOSURE_SENTINEL: Dart 3.13 removed the AOT Closure
// context/delayed_type_arguments fields. These sentinel offsets never match a
// real LDUR displacement, so the two closure-prologue special cases below are
// skipped; all remaining analysis (classes/methods/strings/asm) continues.
#define AOT_Closure_context_offset (-9223372036854775807LL)
#define AOT_Closure_delayed_type_arguments_offset (-9223372036854775807LL)
#endif""",
            1,
        )
        write(car, s)
        log("CodeAnalyzer_arm64.cpp: Dart 3.13 closure offset sentinels added")
    else:
        log("CodeAnalyzer_arm64.cpp: Dart 3.13 sentinels already present")



def patch_dart313_type_tolerance(blutter_dir):
    """Dart 3.13 snapshots contain abstract-type class ids that this blutter
    revision does not model (its FindOrAdd ends in FATAL -> process abort).
    Map unknown ids to the dynamic type instead, keeping the analysis alive."""
    path = os.path.join(blutter_dir, "blutter", "src", "DartTypes.cpp")
    s = read(path)
    if "fler-dart: unknown abstract type" in s:
        log("DartTypes.cpp: Dart 3.13 type tolerance already present")
        return
    old = '\tFATAL("Invalid abstract type");'
    new = """#if defined(BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
\t// fler-dart: Dart 3.13 adds abstract-type kinds this blutter revision does
\t// not model; map them to dynamic instead of aborting the whole analysis.
\tstd::cerr << "fler-dart: unknown abstract type cid=" << abTypePtr.GetClassId()
\t          << " -> dynamic\\n";
\treturn FindOrAdd(dart::Type::dynamic_type().ptr());
#else
\tFATAL("Invalid abstract type");
#endif"""
    assert old in s, "DartTypes.cpp FATAL(Invalid abstract type) not found"
    write(path, s.replace(old, new, 1))
    log("DartTypes.cpp: Dart 3.13 unknown-type tolerance added")


def define_split_cfg_bail_macro(blutter_dir):
    """patch-blutter-robust.py replaces optional-recognizer look-ahead assertions
    with FLER_SPLIT_CFG_BAIL so the bail-out compiles in both void and
    value-returning functions (throwing is valid in any function; per-function
    recovery catches InsnException)."""
    path = os.path.join(blutter_dir, "blutter", "src", "CodeAnalyzer_arm64.cpp")
    s = read(path)
    if "#define FLER_SPLIT_CFG_BAIL" in s:
        log("CodeAnalyzer_arm64.cpp: split-CFG bail macro already present")
        return
    needle = "#include <unordered_set>"
    if needle not in s:
        return
    block = (
        needle
        + "\n\n"
        + "// fler-dart: robustness patches replace optional-recognizer look-ahead\n"
        + "// assertions with this bail-out. Throwing is valid in every recognizer\n"
        + "// (including void ones); per-function recovery catches InsnException.\n"
        + '#define FLER_SPLIT_CFG_BAIL throw InsnException("split-CFG recognizer bail", insn)'
    )
    write(path, s.replace(needle, block, 1))
    log("CodeAnalyzer_arm64.cpp: split-CFG bail macro added")


def fix_void_value_returns(blutter_dir):
    """Some blutter robustness patches replace look-ahead assertions with
    `return nullptr;`; inside void recognizers (e.g. handleFixedParameters) MSVC
    rejects that with C2562. Convert the invalid value-returns in that one void
    function to an InsnException (the per-function recovery handles exceptions)."""
    path = os.path.join(blutter_dir, "blutter", "src", "CodeAnalyzer_arm64.cpp")
    s = read(path)
    marker = "void FunctionAnalyzer::handleFixedParameters"
    if marker not in s:
        return
    start = s.index(marker)
    end = s.index("\n}\n", start)
    body = s[start:end]
    fixed = body.replace("return nullptr;", 'throw InsnException("split-CFG: expected LDR", insn);')
    if fixed == body:
        log("void-function value returns: nothing to fix")
        return
    write(path, s[:start] + fixed + s[end:])
    log("void-function value returns: handleFixedParameters fixed")


def check_commit(blutter_dir):
    try:
        out = subprocess.run(["git", "-C", blutter_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception as e:  # noqa: BLE001
        log(f"WARN: cannot read blutter HEAD ({e})")
        return
    log(f"blutter HEAD = {out}")
    if out != EXPECTED_COMMIT:
        log(f"WARN: expected {EXPECTED_COMMIT}; patches target that tree")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    blutter_dir = os.path.abspath(sys.argv[1])
    if not os.path.isdir(os.path.join(blutter_dir, "blutter", "src")):
        raise SystemExit(f"not a blutter checkout: {blutter_dir}")
    check_commit(blutter_dir)
    patch_dartapp_h(blutter_dir)
    patch_dartdumper_h(blutter_dir)
    patch_fridawriter(blutter_dir)
    patch_write_barrier(blutter_dir)
    patch_robust(blutter_dir)
    patch_dartloader(blutter_dir)
    patch_dartvm_cmake_template(blutter_dir)
    patch_dartvm_cpp20(blutter_dir)
    patch_dart313_stub_support(blutter_dir)
    patch_dart313_api_changes(blutter_dir)
    patch_dart313_type_tolerance(blutter_dir)
    define_split_cfg_bail_macro(blutter_dir)
    fix_void_value_returns(blutter_dir)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
