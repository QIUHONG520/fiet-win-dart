// fiet-win-dart: CodeAnalyzer crash isolation for Windows.
//
// fler-dart 在 Android 上用 sigaction/sigsetjmp 把 CodeAnalyzer 的进程级崩溃
// （SIGSEGV/SIGBUS…）降级为「只导出不反汇编」。Windows 没有 POSIX 信号语义，
// 这里用 MSVC 结构化异常（SEH）实现同等降级：Dart VM 快照解析/反汇编遇到坏数据
// 时触发 AV，SEH 捕获后返回非 0，调用方跳过反汇编继续导出对象池/类/方法。
//
// 注意：
//  * 本文件必须用「关闭 C++ 异常」的选项编译（/EHs-c-），否则 MSVC 会报
//    C2712（函数含 __try 时不能有需要 unwind 的对象）。
//  * 崩溃后 CodeAnalyzer 的 C++ 对象析构不一定执行（栈已损坏），这里故意
//    leak CodeAnalyzer，避免在异常落点再次崩溃；DLL 设计为「一次分析一个进程/
//    进程内复用但只损失一次分析」，泄漏量等价一次分析。
//  * Dart isolate 状态在崩溃后不可信：调用方不会调用 app.ExitScope()（与 fler
//    Android 的降级路径一致，blutter 出口按 GetAnalyzedData()==null 自动退化）。
#include "pch.h"

#include "DartApp.h"
#include "CodeAnalyzer.h"

#include <new>

#if defined(_WIN32)

namespace {
volatile LONG g_last_seh_code = 0;

const char* sehCodeName(DWORD code) {
    switch (code) {
        case EXCEPTION_ACCESS_VIOLATION: return "ACCESS_VIOLATION";
        case EXCEPTION_ILLEGAL_INSTRUCTION: return "ILLEGAL_INSTRUCTION";
        case EXCEPTION_INT_DIVIDE_BY_ZERO: return "INT_DIVIDE_BY_ZERO";
        case EXCEPTION_STACK_OVERFLOW: return "STACK_OVERFLOW";
        case EXCEPTION_IN_PAGE_ERROR: return "IN_PAGE_ERROR";
        case EXCEPTION_PRIV_INSTRUCTION: return "PRIV_INSTRUCTION";
        case EXCEPTION_ARRAY_BOUNDS_EXCEEDED: return "ARRAY_BOUNDS_EXCEEDED";
        case EXCEPTION_FLT_DIVIDE_BY_ZERO: return "FLT_DIVIDE_BY_ZERO";
        default: return "SEH";
    }
}
}  // namespace

extern "C" LONG fler_last_seh_code() { return g_last_seh_code; }

extern "C" const char* fler_seh_code_name() {
    return sehCodeName(static_cast<DWORD>(g_last_seh_code));
}

// 返回 0 = 分析正常完成；-1 = 硬件异常（已降级）；-2 = 内存分配失败。
extern "C" int fler_run_code_analysis_guarded(void* app_ptr) {
    DartApp* app = static_cast<DartApp*>(app_ptr);
    CodeAnalyzer* ca = nullptr;
    g_last_seh_code = 0;
    __try {
        ca = new (std::nothrow) CodeAnalyzer(*app);
        if (ca == nullptr) return -2;
        ca->AnalyzeAll();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_last_seh_code = GetExceptionCode();
        // 故意不 delete：崩溃时 ca 的内部状态/栈不可信，析构可能二次崩溃。
        return -1;
    }
    delete ca;
    return 0;
}

#else

extern "C" LONG fler_last_seh_code() { return 0; }
extern "C" const char* fler_seh_code_name() { return "n/a"; }
extern "C" int fler_run_code_analysis_guarded(void* app) {
    (void)app;
    return -1;
}

#endif  // _WIN32
