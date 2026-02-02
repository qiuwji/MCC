from ast_nodes import *
from my_types import TypeDesc, UNKNOWN


class VariableGenerator:
    """变量声明生成器"""

    def __init__(self, stmt_gen):
        self.stmt_gen = stmt_gen
        self.ctx = stmt_gen.ctx
        self.builder = stmt_gen.builder
        self.expr_gen = stmt_gen.expr_gen

    def _emit(self, cmd: str):
        self.stmt_gen._emit(cmd)

    def generate_let(self, stmt: LetStmt, var_type: TypeDesc):
        """变量声明主入口，根据类型分发"""
        # 实体选择器特殊处理
        if isinstance(stmt.expr, SelectorExpr):
            self._generate_selector(stmt, var_type)
            return

        storage = self.ctx.get_storage_name(stmt.name)
        self.ctx.add_var(stmt.name, storage, var_type)
        resolved_storage = self.ctx.resolve_storage(storage)

        # 根据类型分发
        if var_type.kind == 'prim' and var_type.name == 'string':
            self._generate_string(stmt, resolved_storage, var_type)
        elif var_type.kind == 'array':
            self._generate_array(stmt, resolved_storage, var_type)
        elif var_type.kind == 'struct':
            self._generate_struct(stmt, resolved_storage, var_type)
        else:
            self._generate_numeric(stmt, resolved_storage, var_type)

    def _generate_selector(self, stmt: LetStmt, var_type: TypeDesc):
        """处理实体选择器变量声明"""
        self.ctx.add_var(stmt.name, stmt.expr.raw, var_type)

        if self.ctx.block_stack:
            current_block = self.ctx.block_stack[-1]
            if current_block not in self.ctx.block_vars:
                self.ctx.block_vars[current_block] = []
            self.ctx.block_vars[current_block].append(stmt.name)

    def _generate_string(self, stmt: LetStmt, resolved_storage: str, var_type: TypeDesc):
        """字符串类型变量声明"""
        if isinstance(stmt.expr, StringLiteral):
            self._emit(self.builder.data_set_storage(resolved_storage, stmt.expr.value))
        else:
            cmds = self.expr_gen.gen_expr_to(stmt.expr, resolved_storage, var_type)
            for cmd in cmds:
                self._emit(cmd)

    def _generate_array(self, stmt: LetStmt, resolved_storage: str, var_type: TypeDesc):
        """数组类型变量声明（包含预填充）"""
        if not isinstance(stmt.expr, ArrayLiteral):
            return

        items = stmt.expr.items
        length = len(items)
        self.ctx.array_lengths[resolved_storage] = length
        elem_type = var_type.elem if var_type else UNKNOWN

        if elem_type.kind == 'struct':
            self._generate_struct_array(resolved_storage, items, elem_type)
        else:
            self._generate_primitive_array(resolved_storage, items, elem_type)

        # 保持向后兼容：长度存入 scoreboard
        self._emit(self.builder.set_score(f"{resolved_storage}_len", "_tmp", length))

    def _generate_struct_array(self, resolved_storage: str, items: list, elem_type: TypeDesc):
        """结构体数组初始化 - 修复空数组索引越界问题"""
        from struct_generator import StructGenerator
        struct_gen = StructGenerator(self.ctx, self.builder)

        length = len(items)
        placeholders = ["{}"] * length
        self._emit(
            f'data modify storage {self.ctx.namespace}:data {resolved_storage} set value [{",".join(placeholders)}]')

        # 逐个初始化每个结构体元素
        for i, item in enumerate(items):
            elem_path = f"{resolved_storage}[{i}]"
            cmds = struct_gen.gen_struct_init_storage(item, elem_path, elem_type.name)
            for cmd in cmds:
                self._emit(cmd)

    def _generate_primitive_array(self, resolved_storage: str, items: list, elem_type: TypeDesc):
        """基础类型数组初始化"""
        length = len(items)
        placeholder = [0] * length
        self._emit(f'data modify storage {self.ctx.namespace}:data {resolved_storage} set value {placeholder}')

        for i, item in enumerate(items):
            temp = self.builder.get_temp_var()
            cmds = self.expr_gen.gen_expr_to(item, temp, elem_type)
            for cmd in cmds:
                self._emit(cmd)

            if elem_type.kind == 'prim' and elem_type.name == 'float':
                self._emit(
                    f'execute store result storage {self.ctx.namespace}:data {resolved_storage}[{i}] double 0.01 '
                    f'run scoreboard players get {temp} _tmp')
            else:
                self._emit(
                    f'execute store result storage {self.ctx.namespace}:data {resolved_storage}[{i}] int 1 '
                    f'run scoreboard players get {temp} _tmp')

    def _generate_struct(self, stmt: LetStmt, resolved_storage: str, var_type: TypeDesc):
        """结构体类型变量声明"""
        struct_name = var_type.name

        if not struct_name and isinstance(stmt.expr, CallExpr):
            struct_name = getattr(stmt.expr, '_struct_name', None)
        if not struct_name and isinstance(stmt.expr, StructLiteral):
            struct_name = stmt.expr.struct_name

        if struct_name and struct_name in self.ctx.structs:
            from struct_generator import StructGenerator
            struct_gen = StructGenerator(self.ctx, self.builder)
            cmds = struct_gen.gen_struct_init(stmt.expr, resolved_storage, struct_name)
            for cmd in cmds:
                self._emit(cmd)

    def _generate_numeric(self, stmt: LetStmt, resolved_storage: str, var_type: TypeDesc):
        """数值类型变量声明（int/float/bool）"""
        cmds = self.expr_gen.gen_expr_to(stmt.expr, resolved_storage, var_type)
        for cmd in cmds:
            self._emit(cmd)