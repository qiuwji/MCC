#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MCC 命令行编译器
用法: ./mcc <源文件路径> <目标路径> [游戏版本(默认1.21)]

示例:
    ./mcc demo.mcc ./my_datapack 1.21.4
    ./mcc skills.mcc ./output
    python3 mcc.py src/main.mcd ./dist 1.20.5
"""

import sys
import os
from pathlib import Path

# 确保能导入同级目录的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from write_datapack import DatapackWriter
except ImportError as e:
    print(f"错误: 无法导入 MCC 编译模块: {e}")
    print("请确保此脚本与 write_datapack.py 等模块位于同一目录")
    sys.exit(1)


def print_usage():
    print(__doc__)
    print("\n参数说明:")
    print("  source   - MCC 源文件路径 (.mcc)")
    print("  target   - 数据包输出目录路径")
    print("  version  - 游戏版本号 (可选,默认 1.21) 低于1.20版本不可用, 1.20未经过测试")
    print("             支持: 1.20.5, 1.21, 1.21.4 等")


def main():
    args = sys.argv[1:]

    # 参数检查
    if len(args) < 2:
        print_usage()
        sys.exit(1)

    source_file = args[0]
    target_path = args[1]
    mc_version = args[2] if len(args) > 2 else "1.21"

    # 验证源文件
    source_path = Path(source_file)
    if not source_path.exists():
        print(f"✗ 错误: 源文件不存在: {source_file}")
        sys.exit(1)

    if not source_path.is_file():
        print(f"✗ 错误: 源路径不是文件: {source_file}")
        sys.exit(1)

    # 推断命名空间（默认使用文件名，不含扩展名）
    namespace = source_path.stem

    # 配置
    config = {
        "namespace": namespace,
        "mc_version": mc_version,
        "description": f"Compiled by MCC from {source_path.name}",
        "overwrite": True  # 覆盖已有输出目录
    }

    print(f"[MCC] 开始编译...")
    print(f"  源文件: {source_path.absolute()}")
    print(f"  输出到: {Path(target_path).absolute()}")
    print(f"  游戏版本: {mc_version}")
    print(f"  命名空间: {namespace}")
    print()

    try:
        # 创建编译器并执行
        writer = DatapackWriter(target_path, config)
        writer.compile_source(source_file)
        writer.write()

        print(f"\n✓ 编译成功!")
        print(f"  数据包位置: {Path(target_path).absolute()}")
        print(f"  加载命令: /datapack enable file/{Path(target_path).name}")

    except Exception as e:
        print(f"\n✗ 编译失败!")
        print(f"  错误: {str(e)}")

        # 调试模式显示堆栈
        if os.environ.get("MCC_DEBUG"):
            import traceback
            traceback.print_exc()

        sys.exit(1)


if __name__ == "__main__":
    main()