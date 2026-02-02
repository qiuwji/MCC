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
        """数组类型变量声明（支持部分初始化自动补零）"""
        if not isinstance(stmt.expr, ArrayLiteral):
            return

        elem_type = var_type.elem if var_type else UNKNOWN

        # 关键修复：从 AST 节点获取声明维度（stmt.type_ 是 TypeNode，包含 dims）
        declared_size = None
        if stmt.type_ and hasattr(stmt.type_, 'dims') and stmt.type_.dims:
            # stmt.type_.dims 是 [5] 或 [None]（对于 int[]）
            declared_size = stmt.type_.dims[0]
        elif var_type.shape and len(var_type.shape) > 0:
            declared_size = var_type.shape[0]

        # 复制列表以便修改（不要修改原AST）
        items = list(stmt.expr.items)

        # 如果声明了长度且提供的元素不足，自动补零
        if declared_size is not None and len(items) < declared_size:
            shortfall = declared_size - len(items)

            if elem_type.kind == 'prim':
                if elem_type.name == 'int':
                    items.extend([IntLiteral(0)] * shortfall)
                elif elem_type.name == 'float':
                    items.extend([FloatLiteral(0.0)] * shortfall)
                elif elem_type.name == 'bool':
                    items.extend([BoolLiteral(False)] * shortfall)
                elif elem_type.name == 'string':
                    items.extend([StringLiteral("")] * shortfall)
            elif elem_type.kind == 'struct':
                # 结构体数组：用空对象占位
                for _ in range(shortfall):
                    items.append(ObjectLiteral([]))

        elif declared_size is not None and len(items) > declared_size:
            print(f"警告: 数组 '{stmt.name}' 声明长度为 {declared_size}，但提供了 {len(items)} 个初始值，已截断")
            items = items[:declared_size]

        length = len(items)
        self.ctx.array_lengths[resolved_storage] = length

        if elem_type.kind == 'struct':
            self._generate_struct_array(resolved_storage, items, elem_type)
        else:
            self._generate_primitive_array(resolved_storage, items, elem_type)

        # 关键：确保长度变量正确设置（用于 for 循环）
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
        """基础类型数组初始化（支持 int/float/bool）"""
        length = len(items)

        # 生成 NBT 占位符 [0,0,0,...]
        placeholder = [0] * length
        self._emit(f'data modify storage {self.ctx.namespace}:data {resolved_storage} set value {placeholder}')

        # 逐个写入实际值（包括填充的0，确保类型正确）
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
                # int 和 bool 都用 int 1
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