#pragma once

// fusion-sim 对外 C API。
//
// C/C++ 调用方包含本头文件并链接动态库；Python/C#/其它框架加载动态库，
// 按同样的函数声明调用。

#include <stdint.h>

// 链接方式宏：
//   编译 DLL 本身        -> 定义 FUSION_BUILDING_DLL（dllexport）
//   调用方静态链接(.a)   -> 定义 FUSION_STATIC（无 dllimport，符号为普通定义）
//   调用方动态链接(.dll) -> 都不定义（dllimport）
#ifdef _WIN32
#  if defined(FUSION_BUILDING_DLL)
#    define FUSION_API __declspec(dllexport)
#  elif defined(FUSION_STATIC)
#    define FUSION_API
#  else
#    define FUSION_API __declspec(dllimport)
#  endif
#else
#  define FUSION_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// 不透明句柄：指向内部模拟器实例，调用方只持有、不解析。
typedef struct FusionSim FusionSim;

// 版本字符串（如 "0.1.0"）。返回静态字符串，调用方不得释放。
FUSION_API const char* fusion_version(void);

// 仅校验 scenario 文件合法性（不执行模拟）。
// 返回 1 表示合法，0 表示非法；非法时错误信息可通过 fusion_validate_error 取得。
FUSION_API int fusion_validate(const char* scenario_yaml_path);

// fusion_validate 失败时的错误信息。每次调用后用 fusion_free_string 释放。
FUSION_API char* fusion_validate_error(void);

// 从 scenario 文件创建模拟器实例（只解析 + 校验，不执行模拟）。
// 失败返回 NULL，错误信息通过 fusion_last_error 取得。
FUSION_API FusionSim* fusion_create(const char* scenario_yaml_path);

// 销毁实例并释放资源。传入 NULL 安全。
FUSION_API void fusion_destroy(FusionSim* sim);

// 导出任务图和配置快照，不执行模拟。out_dir 需要新建或为空。
// 返回 0 表示成功，非 0 表示失败（fusion_last_error 取错误）。
FUSION_API int fusion_export_trace(FusionSim* sim, const char* out_dir);

// 执行模拟并将结果 CSV 写入 out_dir，同名结果文件会被覆盖。
// 返回 0 表示成功，非 0 表示失败（fusion_last_error 取错误）。
// 允许重复调用：每次都会在同一 scenario 上重新推演一次。
FUSION_API int fusion_run_simulation(FusionSim* sim, const char* out_dir);

// 最近一次 create/validate/export_trace/run 的错误信息。返回值用
// fusion_free_string 释放。
FUSION_API char* fusion_last_error(void);

// 释放由本库返回的字符串（fusion_last_error / fusion_validate_error）。
FUSION_API void fusion_free_string(char* s);

// 模拟推演的时间长度（微秒）。run 之前调用返回 0。
FUSION_API uint64_t fusion_simulated_time_us(const FusionSim* sim);

// 最近一次 run 的墙钟耗时（秒）。run 之前调用返回 0。
FUSION_API double fusion_wall_clock_s(const FusionSim* sim);

#ifdef __cplusplus
}  // extern "C"
#endif
