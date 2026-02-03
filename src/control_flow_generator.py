from ast_nodes import *
from my_types import UNKNOWN, INT, TypeDesc


class ControlFlowGenerator:
    """控制流生成器 - 修复宏参数传递问题"""

    def __init__(self, stmt_gen):
        self.stmt_gen = stmt_gen
        self.ctx = stmt_gen.ctx
        self.builder = stmt_gen.builder
        self.expr_gen = stmt_gen.expr_gen

    def _emit(self, cmd: str):
        self.stmt_gen._emit(cmd)

    def _get_macro_args(self):
        """获取当前宏参数（关键修复：统一使用 current_macro_args）"""
        if self.ctx.current_macro_args:
            return self.ctx.current_macro_args.copy()
        return None

    def generate_for(self, stmt: ForStmt):
        """For循环入口"""
        if stmt.is_range:
            self._generate_range(stmt)
        else:
            self._generate_each(stmt)

    def generate_while(self, stmt: WhileStmt):
        """While循环公共入口"""
        self._generate_while_impl(stmt)

    def generate_if(self, stmt: IfStmt):
        """If语句公共入口"""
        self._generate_if_impl(stmt)

    def _generate_range(self, stmt: ForStmt):
        """范围循环 for i in 0..10"""
        iter_var = self.ctx.get_storage_name(stmt.var)
        self.ctx.add_var(stmt.var, iter_var, INT)

        end_temp = self.builder.get_temp_var()
        for cmd in self.expr_gen.gen_expr_to(stmt.iterable, iter_var):
            self._emit(cmd)
        for cmd in self.expr_gen.gen_expr_to(stmt.range_end, end_temp):
            self._emit(cmd)

        func_base = f"{self.ctx.current_function or 'global'}_for_{self.ctx.block_counter}"
        head_func = self.builder.new_function(f"{func_base}_head")
        body_func = self.builder.new_function(f"{func_base}_body")
        old_func = self.ctx.current_mcfunc

        macro_args = self._get_macro_args()
        saved_macro_args = self.ctx.current_macro_args.copy() if self.ctx.current_macro_args else {}

        self.ctx.current_mcfunc = head_func
        branch_cmd = self.builder.function_call(f"{func_base}_body", macro_args)
        self._emit(f"execute if score {iter_var} _tmp < {end_temp} _tmp run {branch_cmd}")

        self.ctx.current_mcfunc = body_func
        self.ctx.current_macro_args = saved_macro_args.copy()

        self.ctx.push_block()
        for s in stmt.block:
            self.stmt_gen.gen_stmt(s, body_func)
        self._emit(self.builder.add_score(iter_var, 1))
        self._emit(self.builder.function_call(f"{func_base}_head", macro_args))
        self.ctx.pop_block()

        self.ctx.current_macro_args = saved_macro_args
        self.ctx.current_mcfunc = old_func
        self._emit(self.builder.function_call(f"{func_base}_head", macro_args))

    def _generate_each(self, stmt: ForStmt):
        """For-each循环"""
        iterable_type = getattr(stmt.iterable, '_type', UNKNOWN)
        is_entity_array = (iterable_type and iterable_type.kind == 'array' and
                           iterable_type.elem and iterable_type.elem.kind == 'entity')

        if is_entity_array and isinstance(stmt.iterable, SelectorExpr):
            self._generate_entity_foreach(stmt)
        else:
            self._generate_array_foreach(stmt)

    def _generate_entity_foreach(self, stmt: ForStmt):
        """实体循环"""
        selector = stmt.iterable.raw
        block_id = self.ctx.push_block()
        func_base = f"{self.ctx.current_function or 'global'}_foreach_{block_id}"

        tag_name = f"__mcc_loop_{block_id}"
        tagged_selector = f"@e[tag={tag_name},limit=1]"

        init_func = self.builder.new_function(f"{func_base}_init")
        body_func = self.builder.new_function(f"{func_base}_body")

        macro_args = self._get_macro_args()

        self._emit(self.builder.execute_as(selector,
                                           self.builder.function_call(f"{func_base}_init", macro_args)))

        old_func = self.ctx.current_mcfunc
        saved_macro_args = self.ctx.current_macro_args.copy() if self.ctx.current_macro_args else {}

        # Init函数
        self.ctx.current_mcfunc = init_func
        self.ctx.current_macro_args = saved_macro_args.copy()
        self._emit(f"tag @s add {tag_name}")
        self._emit(self.builder.function_call(f"{func_base}_body", macro_args))
        self._emit(f"tag @s remove {tag_name}")

        # Body函数
        self.ctx.current_mcfunc = body_func
        self.ctx.current_macro_args = saved_macro_args.copy()

        iterable_type = getattr(stmt.iterable, '_type', None)
        if iterable_type and iterable_type.kind == 'array' and iterable_type.elem:
            entity_type = iterable_type.elem
        else:
            entity_type = TypeDesc('entity')

        self.ctx.add_var(stmt.var, tagged_selector, entity_type)

        for s in stmt.block:
            self.stmt_gen.gen_stmt(s, body_func)

        self.ctx.pop_block()

        if stmt.var in self.ctx.var_map:
            del self.ctx.var_map[stmt.var]

        self.ctx.current_macro_args = saved_macro_args
        self.ctx.current_mcfunc = old_func

    def _generate_array_foreach(self, stmt: ForStmt):
        """数组循环 - 修复：正确处理字符串数组"""
        iterable_type = getattr(stmt.iterable, '_type', UNKNOWN)
        arr_expr = stmt.iterable

        if isinstance(arr_expr, Ident):
            arr_name_full = self.ctx.get_var(arr_expr.name)[0]
            actual_arr = self.ctx.resolve_storage(arr_name_full)
            len_var = f"{actual_arr}_len"
            elem_type = iterable_type.elem if iterable_type else UNKNOWN

            iter_var = self.ctx.get_storage_name(stmt.var)
            self.ctx.add_var(stmt.var, iter_var, elem_type)
            iter_idx = f"_idx_{self.ctx.block_counter}"
            self._emit(self.builder.set_score(iter_idx, "_tmp", 0))

            func_base = f"{self.ctx.current_function or 'global'}_foreach_{self.ctx.block_counter}"
            head_func = self.builder.new_function(f"{func_base}_head")
            body_func = self.builder.new_function(f"{func_base}_body")
            old_func = self.ctx.current_mcfunc

            macro_args = self._get_macro_args()
            saved_macro_args = self.ctx.current_macro_args.copy() if self.ctx.current_macro_args else {}

            # ========== 生成 Head 函数（循环条件判断和元素加载）==========
            self.ctx.current_mcfunc = head_func
            self.ctx.current_macro_args = saved_macro_args.copy()

            actual_length = self.ctx.array_lengths.get(actual_arr)
            upper_bound = min(actual_length if actual_length else 50, 50)

            # ========== 关键修复：根据元素类型生成正确的加载逻辑 ==========
            if elem_type and elem_type.kind == 'prim' and elem_type.name == 'string':
                # 字符串数组：使用 data modify 从 storage 复制到 iter_var（也是 storage 路径）
                for i in range(upper_bound):
                    # 字符串复制：data modify storage $(iter_var) set from storage $(arr_path)[i]
                    branch_cmd = f'execute if score {iter_idx} _tmp matches {i} run data modify storage {self.ctx.namespace}:data {iter_var} set from storage {self.ctx.namespace}:data {actual_arr}[{i}]'
                    self._emit(branch_cmd)
            elif elem_type and elem_type.is_value_type():
                # 数值类型数组（int/float）：使用 execute store result score
                for i in range(upper_bound):
                    scale = 1 if elem_type.name == 'int' else 0.01
                    load_cmd = f"execute store result score {iter_var} _tmp run data get storage {self.ctx.namespace}:data {actual_arr}[{i}] {scale}"
                    branch = self.builder.execute_if_score_matches(iter_idx, "_tmp", str(i), load_cmd)
                    self._emit(branch)
            else:
                # 兜底：其他类型
                for i in range(upper_bound):
                    load_cmd = self.builder.copy_score(iter_var, f"{actual_arr}_{i}")
                    branch = self.builder.execute_if_score_matches(iter_idx, "_tmp", str(i), load_cmd)
                    self._emit(branch)

            # 生成循环继续条件
            branch_cmd = self.builder.function_call(f"{func_base}_body", macro_args)
            self._emit(f"execute if score {iter_idx} _tmp < {len_var} _tmp run {branch_cmd}")

            # ========== 生成 Body 函数（循环体执行）==========
            self.ctx.current_mcfunc = body_func
            self.ctx.current_macro_args = saved_macro_args.copy()

            self.ctx.push_block()
            for s in stmt.block:
                self.stmt_gen.gen_stmt(s, body_func)
            self._emit(self.builder.add_score(iter_idx, 1))
            self._emit(self.builder.function_call(f"{func_base}_head", macro_args))
            self.ctx.pop_block()

            # 清理
            self.ctx.current_macro_args = saved_macro_args
            self.ctx.current_mcfunc = old_func

            # 从主函数启动循环
            self._emit(self.builder.function_call(f"{func_base}_head", macro_args))

    def _generate_while_impl(self, stmt: WhileStmt):
        """While循环实现"""
        is_infinite = isinstance(stmt.cond, BoolLiteral) and stmt.cond.value

        if is_infinite:
            if self.ctx.tick_function is None:
                self.ctx.tick_function = self.builder.new_function("__tick__", is_tick=True)
            old_func = self.ctx.current_mcfunc
            self.ctx.current_mcfunc = self.ctx.tick_function
            saved_macro_args = self.ctx.current_macro_args.copy() if self.ctx.current_macro_args else {}

            self.ctx.current_macro_args = {}

            self.ctx.push_block()
            for s in stmt.block:
                self.stmt_gen.gen_stmt(s, self.ctx.tick_function)
            self.ctx.pop_block()

            self.ctx.current_macro_args = saved_macro_args
            self.ctx.current_mcfunc = old_func
        else:
            func_base = f"{self.ctx.current_function or 'global'}_while_{self.ctx.block_counter}"
            entry_func = self.builder.new_function(f"{func_base}_entry")
            body_func = self.builder.new_function(f"{func_base}_body")

            cond_temp = self.builder.get_temp_var()
            old_func = self.ctx.current_mcfunc

            macro_args = self._get_macro_args()
            saved_macro_args = self.ctx.current_macro_args.copy() if self.ctx.current_macro_args else {}

            # Entry函数
            self.ctx.current_mcfunc = entry_func
            self.ctx.current_macro_args = saved_macro_args.copy()

            cmds = self.expr_gen.gen_expr_to(stmt.cond, cond_temp)
            for cmd in cmds:
                self._emit(cmd)
            self._emit(self.builder.execute_if_score(cond_temp, "_tmp", "matches", "1..",
                                                     self.builder.function_call(f"{func_base}_body", macro_args)))

            # Body函数
            self.ctx.current_mcfunc = body_func
            self.ctx.current_macro_args = saved_macro_args.copy()

            self.ctx.push_block()
            for s in stmt.block:
                self.stmt_gen.gen_stmt(s, body_func)
            self._emit(self.builder.function_call(f"{func_base}_entry", macro_args))
            self.ctx.pop_block()

            self.ctx.current_macro_args = saved_macro_args
            self.ctx.current_mcfunc = old_func
            self._emit(self.builder.function_call(f"{func_base}_entry", macro_args))

    def _generate_if_impl(self, stmt: IfStmt):
        """If语句实现 """
        cond_temp = self.builder.get_temp_var()
        cmds = self.expr_gen.gen_expr_to(stmt.cond, cond_temp)
        for cmd in cmds:
            self._emit(cmd)

        base_name = f"{self.ctx.current_function or 'global'}_if_{self.ctx.block_counter}"

        macro_args = self._get_macro_args()
        saved_macro_args = self.ctx.current_macro_args.copy() if self.ctx.current_macro_args else {}

        then_name = f"{base_name}_then"
        else_name = f"{base_name}_else" if stmt.else_block else None

        then_func = self.builder.new_function(then_name)
        else_func = self.builder.new_function(else_name) if else_name else None

        # 生成 then 调用（条件为真时执行）
        then_call = self.builder.function_call(then_name, macro_args)
        then_wrapped = f"execute as @s run {then_call}"
        self._emit(self.builder.execute_if_score(cond_temp, "_tmp", "matches", "1..", then_wrapped))

        # 关键修复：确保 else 分支被正确生成和调用（使用 execute unless）
        if else_func and stmt.else_block:
            else_call = self.builder.function_call(else_name, macro_args)
            else_wrapped = f"execute as @s run {else_call}"
            self._emit(self.builder.execute_unless_score(cond_temp, "_tmp", "matches", "1..", else_wrapped))

        old_func = self.ctx.current_mcfunc

        # 生成 then 块
        self.ctx.current_mcfunc = then_func
        self.ctx.current_macro_args = saved_macro_args.copy()
        self.ctx.push_block()
        for s in stmt.then_block:
            self.stmt_gen.gen_stmt(s, then_func)

        self._cleanup_block_entities()

        self.ctx.pop_block()

        # 生成 else 块（如果存在）
        if else_func and stmt.else_block:
            self.ctx.current_mcfunc = else_func
            self.ctx.current_macro_args = saved_macro_args.copy()
            self.ctx.push_block()
            for s in stmt.else_block:
                self.stmt_gen.gen_stmt(s, else_func)

            self._cleanup_block_entities()

            self.ctx.pop_block()

        self.ctx.current_macro_args = saved_macro_args
        self.ctx.current_mcfunc = old_func

    def _cleanup_block_entities(self):
        """清理当前块中声明的实体标签"""
        if not self.ctx.block_stack:
            return

        # 获取当前块ID
        block_id = self.ctx.block_stack[-1]

        # 查找当前块声明的实体变量（在block_vars中）
        if block_id in self.ctx.block_vars:
            for var_name in list(self.ctx.block_vars[block_id]):
                if var_name in self.ctx.entity_tags:
                    tag_name = self.ctx.entity_tags[var_name]
                    # 生成清理指令
                    self._emit(f"tag @e[tag={tag_name}] remove {tag_name}")
                    # 从全局跟踪中移除，避免重复清理
                    del self.ctx.entity_tags[var_name]