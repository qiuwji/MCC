import re

from ast_nodes import *


class MiscGenerator:
    """杂项语句生成器"""

    def __init__(self, stmt_gen):
        self.stmt_gen = stmt_gen
        self.ctx = stmt_gen.ctx
        self.builder = stmt_gen.builder
        self.expr_gen = stmt_gen.expr_gen

    def _emit(self, cmd: str):
        self.stmt_gen._emit(cmd)

    def generate_return(self, stmt: ReturnStmt):
        """生成return语句"""
        if not stmt.expr:
            return

        ret_var = f"_ret_{self.ctx.current_function}"

        ret_type = None
        if self.ctx.current_function and self.ctx.current_function in self.ctx.funcs:
            _, ret_type, _ = self.ctx.funcs[self.ctx.current_function]

        if isinstance(stmt.expr, CallExpr) and getattr(stmt.expr, '_is_struct_constructor', False):
            struct_name = getattr(stmt.expr, '_struct_name', None)
            if struct_name and struct_name in self.ctx.structs and stmt.expr.args:
                obj = stmt.expr.args[0]
                if isinstance(obj, ObjectLiteral):
                    fields_dict = {n: e for n, e in obj.fields}
                    self._generate_struct_return(ret_var, struct_name, fields_dict)
            return

        if isinstance(stmt.expr, (StructLiteral, ObjectLiteral)):
            struct_type = getattr(stmt.expr, '_type', None)
            if struct_type and struct_type.kind == 'struct':
                struct_name = struct_type.name
                if struct_name in self.ctx.structs:
                    fields = stmt.expr.fields if isinstance(stmt.expr, StructLiteral) else stmt.expr.fields
                    provided = {n: e for n, e in fields}
                    self._generate_struct_return(ret_var, struct_name, provided)
            return

        if isinstance(stmt.expr, Ident):
            var_type = self.ctx.get_var(stmt.expr.name)[1]
            if var_type and var_type.kind == 'struct':
                storage = self.ctx.get_var(stmt.expr.name)[0]
                resolved = self.ctx.resolve_storage(storage)
                from struct_generator import StructGenerator
                struct_gen = StructGenerator(self.ctx, self.builder)
                for cmd in struct_gen.gen_struct_copy(ret_var, resolved, var_type.name):
                    self._emit(cmd)
                return

        cmds = self.expr_gen.gen_expr_to(stmt.expr, ret_var, ret_type)
        for cmd in cmds:
            self._emit(cmd)

    def _generate_struct_return(self, ret_var: str, struct_name: str, fields_dict: dict):
        struct_gen = __import__('struct_generator').StructGenerator(self.ctx, self.builder)
        for fname, ftype in self.ctx.structs[struct_name].items():
            field_ret_var = f"{ret_var}_{fname}"
            if fname in fields_dict:
                fval = fields_dict[fname]
                if ftype.is_value_type():
                    cmds = self.expr_gen.gen_expr_to(fval, field_ret_var)
                    for cmd in cmds:
                        self._emit(cmd)
                elif ftype.kind == 'array' and isinstance(fval, ArrayLiteral):
                    length = len(fval.items)
                    self._emit(self.builder.set_score(f"{field_ret_var}_len", "_tmp", length))
                    self.ctx.array_lengths[field_ret_var] = length
                    for i, item in enumerate(fval.items):
                        elem_storage = f"{field_ret_var}_{i}"
                        temp = self.builder.get_temp_var()
                        cmds = self.expr_gen.gen_expr_to(item, temp)
                        for cmd in cmds:
                            self._emit(cmd)
                        self._emit(self.builder.copy_score(elem_storage, temp))
            else:
                if ftype.is_value_type():
                    self._emit(self.builder.set_score(field_ret_var, "_tmp", 0))
                elif ftype.kind == 'array':
                    self._emit(self.builder.set_score(f"{field_ret_var}_len", "_tmp", 0))

    def generate_expr_stmt(self, stmt: ExprStmt):
        """表达式语句"""
        temp = self.builder.get_temp_var()
        cmds = self.expr_gen.gen_expr_to(stmt.expr, temp)
        for cmd in cmds:
            self._emit(cmd)

    def generate_cmd(self, stmt: CmdStmt):
        """Cmd语句"""
        text = stmt.text.strip('"')
        var_pattern = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')
        matches = list(var_pattern.finditer(text))

        if not matches:
            substituted = self._fix_particle_command(text)
            if '$(' in substituted and not substituted.startswith('$'):
                substituted = '$' + substituted
            self._emit(substituted)
            return

        func_base = f"{self.ctx.current_function or 'global'}_cmd_{self.ctx.block_counter}_{len(self.builder.functions)}"
        macro_func = self.builder.new_function(func_base)

        old_func = self.ctx.current_mcfunc
        self.ctx.current_mcfunc = macro_func

        def to_macro_param(m):
            return f"$({m.group(1)})"

        macro_body = var_pattern.sub(to_macro_param, text)

        if macro_body.startswith('say ') or macro_body.startswith('/say '):
            parts = []
            last_end = 0
            for m in var_pattern.finditer(text):
                if m.start() > last_end:
                    literal = text[last_end:m.start()]
                    parts.append(f'"{literal}"')
                parts.append(f'"$({m.group(1)})"')
                last_end = m.end()
            if last_end < len(text):
                parts.append(f'"{text[last_end:]}"')

            macro_body = f"tellraw @s [{','.join(parts)}]"

        self._emit(f"${macro_body}")

        self.ctx.current_mcfunc = old_func

        macro_args_storage = f"__cmd_args_{func_base}"

        for m in matches:
            varname = m.group(1)
            storage, vtype = self.ctx.get_var(varname)
            resolved = self.ctx.resolve_storage(storage)

            arg_path = f"{macro_args_storage}.{varname}"

            if vtype.kind == 'prim' and vtype.name == 'string':
                self._emit(
                    f'data modify storage {self.ctx.namespace}:data {arg_path} set from storage {self.ctx.namespace}:data {resolved}')
            elif vtype.is_value_type():
                scale = 1 if vtype.name == 'int' else 0.01
                store_type = "int" if vtype.name == 'int' else "double"
                self._emit(
                    f'execute store result storage {self.ctx.namespace}:data {arg_path} {store_type} {scale} run scoreboard players get {resolved} _tmp')
            elif vtype.kind == 'entity':
                if isinstance(resolved, str) and resolved.startswith('@'):
                    self._emit(f'data modify storage {self.ctx.namespace}:data {arg_path} set value "{resolved}"')
                else:
                    self._emit(f'data modify storage {self.ctx.namespace}:data {arg_path} set value "@s"')
            elif vtype.kind == 'array':
                self._emit(
                    f'execute store result storage {self.ctx.namespace}:data {arg_path} int 1 run scoreboard players get {resolved}_len _tmp')

        self._emit(
            f'function {self.ctx.namespace}:{func_base} with storage {self.ctx.namespace}:data {macro_args_storage}')

    def _fix_particle_command(self, cmd: str) -> str:
        """修复particle命令"""
        if not cmd.startswith('particle '):
            return cmd

        parts = cmd.split()
        if len(parts) < 3:
            return cmd

        if parts[2].startswith('@'):
            selector = parts[2]
            particle_name = parts[1]
            rest = ' '.join(parts[3:]) if len(parts) > 3 else ''

            if rest:
                return f"execute at {selector} run particle {particle_name} ~ ~ ~ {rest}"
            else:
                return f"execute at {selector} run particle {particle_name} ~ ~ ~"

        return cmd

    def generate_len(self, expr: CallExpr, target_var: Optional[str]):
        """生成len(arr)代码"""
        if not self._validate_len_args(expr, target_var):
            return []

        arr_expr = expr.args[0]

        if isinstance(arr_expr, Ident):
            return self._generate_len_ident(arr_expr, target_var)
        elif isinstance(arr_expr, IndexExpr):
            return self._generate_len_index(expr, target_var)

        return []

    def _validate_len_args(self, expr: CallExpr, target_var: Optional[str]) -> bool:
        return bool(expr.args and target_var)

    def _generate_len_ident(self, arr_expr: Ident, target_var: str):
        storage, _ = self.ctx.get_var(arr_expr.name)
        resolved = self.ctx.resolve_storage(storage)

        return [
            f'execute store result score {target_var} _tmp run '
            f'data get storage {self.ctx.namespace}:data {resolved}[]'
        ]

    def _generate_len_index(self, arr_expr: IndexExpr, target_var: str):
        arr_path = self._extract_array_path(arr_expr)

        if not arr_path:
            return []

        return [
            f'execute store result score {target_var} _tmp run '
            f'data get storage {self.ctx.namespace}:data {arr_path}[]'
        ]

    def _extract_array_path(self, arr_expr: IndexExpr) -> Optional[str]:
        if not isinstance(arr_expr.base, Ident):
            return None

        if not isinstance(arr_expr.index, (Ident, StringLiteral)):
            return None

        base_storage = self.ctx.get_var(arr_expr.base.name)[0]
        base_storage = self.ctx.resolve_storage(base_storage)

        field_name = (
            arr_expr.index.name
            if isinstance(arr_expr.index, Ident)
            else arr_expr.index.value
        )

        return f"{base_storage}_{field_name}"