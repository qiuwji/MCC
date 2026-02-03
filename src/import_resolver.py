"""
Import Resolver - 最小可行模块化系统
支持相对路径导入和名称过滤
"""
import os
from pathlib import Path
from typing import List, Set, Dict, Optional, Any

from ast_nodes import ImportStmt, Program, FuncDecl, StructDecl
from parser import parse


class ImportResolver:
    """简单导入解析器 - 方案A实现"""

    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path).resolve()
        self.loaded_modules: Set[str] = set()  # 防止循环导入
        self.all_functions: Dict[str, FuncDecl] = {}
        self.all_structs: Dict[str, StructDecl] = {}
        self.import_order: List[str] = []  # 记录加载顺序

    def resolve_program(self, program: Program) -> Program:
        """
        解析程序中的所有导入，合并AST
        返回合并后的新Program
        """
        new_stmts = []

        for stmt in program.stmts:
            if isinstance(stmt, ImportStmt):
                # 处理导入
                imported = self._load_import(stmt)
                # 导入的语句放在前面（确保声明顺序）
                new_stmts.extend(imported)
            else:
                new_stmts.append(stmt)

        return Program(stmts=new_stmts)

    def _load_import(self, import_stmt: ImportStmt) -> List[Any]:
        """加载单个导入语句，返回要合并的语句列表"""
        module_path = self._resolve_path(import_stmt.module)

        if not module_path.exists():
            raise ImportError(f"找不到模块: {import_stmt.module} (查找路径: {module_path})")

        if str(module_path) in self.loaded_modules:
            # 已加载过，只返回需要的名称（如果有过滤）
            return self._filter_symbols(import_stmt.names)

        self.loaded_modules.add(str(module_path))
        self.import_order.append(import_stmt.module)

        # 解析文件
        with open(module_path, 'r', encoding='utf-8') as f:
            code = f.read()

        ast = parse(code)

        # 提取函数和结构体定义
        stmts_to_import = []
        for stmt in ast.stmts:
            if isinstance(stmt, FuncDecl):
                self.all_functions[stmt.name] = stmt
                if import_stmt.names is None or stmt.name in import_stmt.names:
                    stmts_to_import.append(stmt)
            elif isinstance(stmt, StructDecl):
                self.all_structs[stmt.name] = stmt
                if import_stmt.names is None or stmt.name in import_stmt.names:
                    stmts_to_import.append(stmt)
            elif isinstance(stmt, ImportStmt):
                # 递归处理子导入
                nested = self._load_import(stmt)
                stmts_to_import.extend(nested)

        return stmts_to_import

    def _resolve_path(self, module: str) -> Path:
        """解析模块路径"""
        if module.startswith("./") or module.startswith("../"):
            # 相对路径
            return self.base_path / module
        else:
            # 尝试作为相对路径或标准库路径
            # 先尝试相对当前目录
            local = self.base_path / f"{module}.mcc"
            if local.exists():
                return local
            # 再尝试 stdlib 目录
            stdlib = self.base_path / "std" / f"{module}.mcc"
            if stdlib.exists():
                return stdlib
            return local  # 返回默认路径，让报错显示正确的查找位置

    def _filter_symbols(self, names: Optional[List[str]]) -> List[Any]:
        """从已加载的符号中过滤需要的"""
        if names is None:
            # 返回所有已加载的
            result = []
            result.extend(self.all_structs.values())
            result.extend(self.all_functions.values())
            return result

        result = []
        for name in names:
            if name in self.all_functions:
                result.append(self.all_functions[name])
            elif name in self.all_structs:
                result.append(self.all_structs[name])
            else:
                raise ImportError(f"导入错误: '{name}' 未在模块中定义")
        return result


def merge_imports(program: Program, base_path: str = ".") -> Program:
    """
    便捷函数：解析并合并程序中的所有导入
    用法: program = merge_imports(program, "./src")
    """
    resolver = ImportResolver(base_path)
    return resolver.resolve_program(program)