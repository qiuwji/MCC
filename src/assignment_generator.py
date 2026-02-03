from ast_nodes import *
from my_types import *


class AssignmentGenerator:
    """赋值语句生成器"""

    def __init__(self, stmt_gen):
        self.stmt_gen = stmt_gen
        self.ctx = stmt_gen.ctx
        self.builder = stmt_gen.builder
        self.expr_gen = stmt_gen.expr_gen

    def _emit(self, cmd: str):
        self.stmt_gen._emit(cmd)

    def generate_assign(self, stmt: AssignStmt):
        """赋值语句主入口"""
        target = stmt.target
        target_type = self._get_target_type(target)

        if isinstance(target, FieldAccess):
            self.generate_field_assign(target, stmt.expr)
            return

        # 字符串类型单独处理
        if target_type.kind == 'prim' and target_type.name == 'string':
            self._generate_string_assign(stmt.expr, target)
            return

        # 数值类型先求值到临时变量
        temp = self.builder.get_temp_var()
        cmds = self.expr_gen.gen_expr_to(stmt.expr, temp, target_type)
        for cmd in cmds:
            self._emit(cmd)

        # 根据目标类型分发
        if isinstance(target, Ident):
            self._generate_simple_ident(target, temp)
        elif isinstance(target, IndexExpr):
            self._generate_index(target, temp)

    def _get_target_type(self, target) -> TypeDesc:
        """获取赋值目标类型"""
        if isinstance(target, Ident):
            _, target_type = self.ctx.get_var(target.name)
            return target_type
        elif isinstance(target, IndexExpr):
            return getattr(target, '_type', UNKNOWN)
        return UNKNOWN

    def _generate_string_assign(self, expr, target):
        """字符串赋值"""
        temp_path = f"__assign_tmp_{self.ctx.block_counter}_{self.builder.get_temp_var()}"
        cmds = self.expr_gen.gen_expr_to(expr, temp_path)
        for cmd in cmds:
            self._emit(cmd)

        if isinstance(target, Ident):
            storage, _ = self.ctx.get_var(target.name)
            resolved = self.ctx.resolve_storage(storage)
            self._emit(self.builder.data_copy_storage(resolved, temp_path))
        elif isinstance(target, IndexExpr):
            self._generate_string_index(target, temp_path)

    def _generate_string_index(self, target: IndexExpr, source_path: str):
        """字符串数组/结构体字段索引赋值"""
        base_type = getattr(target.base, '_type', UNKNOWN)

        if isinstance(target.base, IndexExpr):
            self._generate_nested_string_index(target, source_path)
        elif base_type.kind == 'array':
            self._generate_string_array(target, source_path)
        elif base_type.kind == 'struct':
            self._generate_string_struct(target, source_path)

    def _generate_nested_string_index(self, target: IndexExpr, source_path: str):
        """嵌套字符串索引 arr[0].field"""
        inner_base = target.base.base
        field_expr = target.base.index

        if not isinstance(inner_base, Ident):
            return

        base_storage, _ = self.ctx.get_var(inner_base.name)
        base_storage = self.ctx.resolve_storage(base_storage)

        if isinstance(field_expr, (Ident, StringLiteral)):
            field_name = field_expr.name if isinstance(field_expr, Ident) else field_expr.value
            arr_base = f"{base_storage}_{field_name}"
            actual_arr = self.ctx.resolve_storage(arr_base)

            if isinstance(target.index, IntLiteral):
                idx = target.index.value
                self._emit(self.builder.data_copy_storage(f"{actual_arr}_{idx}", source_path))
            else:
                self._generate_dynamic_string_array(actual_arr, target.index, source_path)

    def _generate_string_array(self, target: IndexExpr, source_path: str):
        """字符串数组元素赋值"""
        arr_storage, arr_type = self.ctx.get_var(target.base.name)
        arr_path = self.ctx.resolve_storage(arr_storage)
        elem_type = arr_type.elem if arr_type else UNKNOWN

        if isinstance(target.index, IntLiteral):
            idx = target.index.value
            if elem_type.kind == 'prim' and elem_type.name == 'string':
                self._emit(self.builder.data_copy_storage(f"{arr_path}[{idx}]", source_path))
            else:
                self._emit(self.builder.copy_score(f"{arr_path}_{idx}", source_path))
        else:
            self._generate_dynamic_string_array(arr_path, target.index, source_path)

    def _generate_string_struct(self, target: IndexExpr, source_path: str):
        """结构体字符串字段赋值"""
        if isinstance(target.base, Ident):
            base_storage, _ = self.ctx.get_var(target.base.name)
            base_storage = self.ctx.resolve_storage(base_storage)
            if isinstance(target.index, (Ident, StringLiteral)):
                field_name = target.index.name if isinstance(target.index, Ident) else target.index.value
                self._emit(self.builder.data_copy_storage(f"{base_storage}_{field_name}", source_path))

    def _generate_dynamic_string_array(self, arr_path: str, index_expr, source_path: str):
        """动态字符串数组索引设置"""
        idx_temp = self.builder.get_temp_var()
        cmds = self.expr_gen.gen_expr_to(index_expr, idx_temp)
        for cmd in cmds:
            self._emit(cmd)

        self._emit(
            f'execute store result storage {self.ctx.namespace}:data __args.index int 1 run scoreboard players get {idx_temp} _tmp')

        if arr_path.startswith('$'):
            self._emit(f'$data modify storage {self.ctx.namespace}:data __args.path set value {arr_path}')
        else:
            self._emit(f'data modify storage {self.ctx.namespace}:data __args.path set value "{arr_path}"')

        self._emit(f'data modify storage {self.ctx.namespace}:data __args.source set value "{source_path}"')
        self._emit(f'function {self.ctx.namespace}:__array_set_string with storage {self.ctx.namespace}:data __args')

    def _generate_simple_ident(self, target: Ident, temp: str):
        """简单标识符赋值"""
        storage, var_type = self.ctx.get_var(target.name)
        resolved = self.ctx.resolve_storage(storage)

        if var_type.kind == 'struct':
            from struct_generator import StructGenerator
            struct_gen = StructGenerator(self.ctx, self.builder)
            for cmd in struct_gen.gen_struct_copy(resolved, temp, var_type.name):
                self._emit(cmd)
        else:
            self._emit(self.builder.copy_score(resolved, temp))

    def _generate_index(self, target: IndexExpr, temp: str):
        """索引赋值分发"""
        base_type = getattr(target.base, '_type', UNKNOWN)

        if isinstance(target.base, IndexExpr):
            self._generate_nested_index(target, temp)
        elif base_type.kind == 'array':
            self._generate_array(target, temp)
        elif base_type.kind == 'struct':
            self._generate_struct_field(target, temp)
        elif base_type.kind == 'entity':
            self._generate_entity_field(target, temp)

    def _generate_nested_index(self, target: IndexExpr, temp: str):
        """嵌套索引赋值 arr[field][index]"""
        inner_base = target.base.base
        field_expr = target.base.index

        if not isinstance(inner_base, Ident):
            return

        base_storage, _ = self.ctx.get_var(inner_base.name)
        base_storage = self.ctx.resolve_storage(base_storage)

        if isinstance(field_expr, (Ident, StringLiteral)):
            field_name = field_expr.name if isinstance(field_expr, Ident) else field_expr.value
            arr_base = f"{base_storage}_{field_name}"

            if isinstance(target.index, IntLiteral):
                idx = target.index.value
                actual_arr = self.ctx.resolve_storage(arr_base)
                self._emit(self.builder.copy_score(f"{actual_arr}_{idx}", temp))
            else:
                self._generate_dynamic_index(arr_base, target.index, temp)

    def _generate_dynamic_index(self, arr_base: str, index_expr, temp: str):
        """动态索引分支赋值"""
        idx_temp = self.builder.get_temp_var()
        cmds = self.expr_gen.gen_expr_to(index_expr, idx_temp)

        actual_arr = self.ctx.resolve_storage(arr_base)
        upper_bound = min(self.ctx.array_lengths.get(actual_arr, 50), 50)

        for i in range(upper_bound):
            store_cmd = self.builder.copy_score(f"{actual_arr}_{i}", temp)
            branch = self.builder.execute_if_score_matches(idx_temp, "_tmp", str(i), store_cmd)
            cmds.append(branch)

        for cmd in cmds:
            self._emit(cmd)

    def _generate_array(self, target: IndexExpr, temp: str):
        """数组元素赋值 - 关键修复：支持 FieldAccess（如 game.board）"""
        # 获取数组路径（支持 Ident 和 FieldAccess）
        if isinstance(target.base, Ident):
            arr_storage, arr_type = self.ctx.get_var(target.base.name)
            arr_path = self.ctx.resolve_storage(arr_storage)
        elif isinstance(target.base, FieldAccess):
            base_path = self._get_storage_path(target.base)
            arr_path = self.ctx.resolve_storage(base_path) if base_path else None
            # ========== 关键修复：从 FieldAccess 节点本身获取类型（它是数组类型）==========
            arr_type = getattr(target.base, '_type', UNKNOWN)
        else:
            return

        if not arr_path:
            return

        elem_type = arr_type.elem if arr_type else UNKNOWN

        if isinstance(target.index, IntLiteral):
            idx = target.index.value
            if elem_type and elem_type.kind == 'struct':  # 添加空检查
                from struct_generator import StructGenerator
                struct_gen = StructGenerator(self.ctx, self.builder)
                for cmd in struct_gen.gen_struct_copy(f"{arr_path}_{idx}", temp, elem_type.name):
                    self._emit(cmd)
            else:
                self._emit(self.builder.copy_score(f"{arr_path}_{idx}", temp))
        else:
            self._generate_array_dynamic(arr_path, target.index, temp, elem_type)

    def _get_base_var_name(self, expr) -> Optional[str]:
        """从 FieldAccess 链中提取根变量名"""
        if isinstance(expr, Ident):
            return expr.name
        elif isinstance(expr, FieldAccess):
            return self._get_base_var_name(expr.base)
        return None

    def _get_storage_path(self, expr) -> Optional[str]:
        """递归构建storage路径"""
        if isinstance(expr, Ident):
            storage, _ = self.ctx.get_var(expr.name)
            return self.ctx.resolve_storage(storage)
        elif isinstance(expr, FieldAccess):
            base = self._get_storage_path(expr.base)
            if base:
                return f"{base}_{expr.field}"
        return None

    def _generate_array_dynamic(self, arr_path: str, index_expr, temp: str, elem_type: TypeDesc):
        """数组动态索引赋值"""
        # 防御性检查
        if elem_type is None:
            elem_type = UNKNOWN

        idx_cmds = self.expr_gen.gen_expr_to(index_expr, "_idx")
        for cmd in idx_cmds:
            self._emit(cmd)

        if arr_path.startswith('$'):
            self._emit(f'$data modify storage {self.ctx.namespace}:data __args.path set value {arr_path}')
        else:
            self._emit(f'data modify storage {self.ctx.namespace}:data __args.path set value "{arr_path}"')

        self._emit(
            f'execute store result storage {self.ctx.namespace}:data __args.index int 1 run scoreboard players get _idx _tmp')

        if elem_type.kind == 'struct':
            self._emit(f'data modify storage {self.ctx.namespace}:data __args.source set value "{temp}"')
            self._emit(
                f'function {self.ctx.namespace}:__array_set_struct with storage {self.ctx.namespace}:data __args')
        else:
            self._emit(f'data modify storage {self.ctx.namespace}:data __args.value set value "{temp}"')
            type_str = "int" if elem_type.name == 'int' else "double"
            self._emit(f'data modify storage {self.ctx.namespace}:data __args.type set value "{type_str}"')
            self._emit(f'function {self.ctx.namespace}:__array_set with storage {self.ctx.namespace}:data __args')

    def _generate_struct_field(self, target: IndexExpr, temp: str):
        """结构体字段赋值"""
        if isinstance(target.base, Ident):
            base_storage, _ = self.ctx.get_var(target.base.name)
            base_storage = self.ctx.resolve_storage(base_storage)
            if isinstance(target.index, (Ident, StringLiteral)):
                field_name = target.index.name if isinstance(target.index, Ident) else target.index.value
                self._emit(self.builder.copy_score(f"{base_storage}_{field_name}", temp))

    def _generate_entity_field(self, target: IndexExpr, temp: str):
        """实体属性赋值"""
        if isinstance(target.base, Ident):
            from entity_generator import EntityGenerator
            entity_gen = EntityGenerator(self.ctx, self.builder)
            selector = entity_gen.get_entity_selector(target.base.name) or "@s"
            if isinstance(target.index, (Ident, StringLiteral)):
                field_name = target.index.name if isinstance(target.index, Ident) else target.index.value
                cmds = entity_gen.gen_entity_write(target, temp, selector, field_name)
                for cmd in cmds:
                    self._emit(cmd)

    def generate_field_assign(self, target: FieldAccess, value_expr):
        """点号字段赋值"""
        target_type = getattr(target, '_type', UNKNOWN)

        # 先计算值到临时变量
        temp = self.builder.get_temp_var()
        cmds = self.expr_gen.gen_expr_to(value_expr, temp, target_type)
        for cmd in cmds:
            self._emit(cmd)

        # 结构体字段赋值
        if getattr(target, '_is_struct_field', False):
            base_path = self._get_storage_path(target.base)
            if base_path:
                field_path = f"{base_path}_{target.field}"
                resolved = self.ctx.resolve_storage(field_path)

                if target_type.kind == 'prim' and target_type.name == 'string':
                    self._emit(self.builder.data_copy_storage(resolved, temp))
                else:
                    self._emit(self.builder.copy_score(resolved, temp))
            return

        # 实体NBT赋值
        if getattr(target, '_is_entity_attr', False):
            selector = self._get_entity_selector(target.base) or "@s"
            nbt_path = getattr(target, '_nbt_path', target.field)

            if target_type.kind == 'prim' and target_type.name == 'int':
                store_type = "int"
                scale = "1"
            else:
                store_type = "float"
                scale = "0.01"

            self._emit(
                f"execute store result entity {selector} {nbt_path} {store_type} {scale} "
                f"run scoreboard players get {temp} _tmp"
            )

    def _get_entity_selector(self, expr):
        """提取实体选择器"""
        if isinstance(expr, SelectorExpr):
            return expr.raw
        elif isinstance(expr, Ident):
            storage, var_type = self.ctx.get_var(expr.name)
            if var_type.kind == 'entity':
                return storage if isinstance(storage, str) and storage.startswith('@') else "@s"
        elif isinstance(expr, FieldAccess):
            return self._get_entity_selector(expr.base)
        return None