import io

# 从 ast_nodes 导入所有节点类型
from ast_nodes import *


class ASTPrinter:
    """
    带注释的AST打印机
    支持：
    - 类型推导信息显示 (_type)
    - 作用域信息
    - 源码位置（如果节点有lineno属性）
    - 彩色输出（可选）
    """

    def __init__(self, show_types=True, show_locations=False, use_colors=False, indent_size=2):
        self.show_types = show_types
        self.show_locations = show_locations
        self.use_colors = use_colors
        self.indent_size = indent_size
        self.output = io.StringIO()

        # 颜色代码
        if use_colors:
            self.colors = {
                'type': '\033[36m',  # 青色 - 类型信息
                'node': '\033[33m',  # 黄色 - 节点名
                'field': '\033[37m',  # 白色 - 字段名
                'value': '\033[32m',  # 绿色 - 值
                'comment': '\033[90m',  # 灰色 - 注释
                'reset': '\033[0m'
            }
        else:
            self.colors = {k: '' for k in ['type', 'node', 'field', 'value', 'comment', 'reset']}

    def print(self, node: Any) -> str:
        """打印AST并返回字符串"""
        self.output = io.StringIO()
        self._visit(node, 0)
        return self.output.getvalue()

    def _write(self, text: str):
        self.output.write(text)

    def _indent(self, level: int):
        self._write(" " * (level * self.indent_size))

    def _color(self, text: str, color: str) -> str:
        return f"{self.colors[color]}{text}{self.colors['reset']}"

    def _get_type_annotation(self, node: Any) -> str:
        """获取节点的类型注释"""
        if not self.show_types:
            return ""

        type_info = getattr(node, '_type', None)
        if type_info:
            return self._color(f" /* : {type_info} */", 'type')

        # 检查是否有存储名注释（实体选择器等）
        storage = getattr(node, '_storage_name', None)
        if storage:
            return self._color(f" /* storage: {storage} */", 'comment')

        return ""

    def _visit(self, node: Any, depth: int):
        """访问节点"""
        if node is None:
            self._write("null")
            return

        if isinstance(node, (str, int, float, bool)):
            self._write(self._color(repr(node), 'value'))
            return

        if isinstance(node, list):
            if not node:
                self._write("[]")
                return
            self._write("[")
            for i, item in enumerate(node):
                if i > 0:
                    self._write(", ")
                self._visit(item, depth + 1)
            self._write("]")
            return

        if isinstance(node, tuple):
            # 通常用于 (name, type) 对
            self._write("(")
            self._visit(node[0], depth)
            self._write(": ")
            self._visit(node[1], depth)
            self._write(")")
            return

        # 根据节点类型分发
        method_name = f'_visit_{node.__class__.__name__}'
        visitor = getattr(self, method_name, self._visit_generic)
        visitor(node, depth)

    def _visit_generic(self, node: Any, depth: int):
        """通用节点访问"""
        class_name = node.__class__.__name__
        self._indent(depth)
        self._write(self._color(class_name, 'node'))
        self._write(" {")

        # 写类型注释
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

        self._write("\n")

        # 写字段
        for field_name, value in node.__dict__.items():
            if field_name.startswith('_'):
                continue

            self._indent(depth + 1)
            self._write(self._color(field_name, 'field'))
            self._write(": ")

            if isinstance(value, (str, int, float, bool)):
                self._write(self._color(repr(value), 'value'))
            else:
                self._write("\n")
                self._visit(value, depth + 2)

            self._write("\n")

        self._indent(depth)
        self._write("}")

    # 特定节点的优化打印

    def _visit_Program(self, node: Program, depth: int):
        self._write(self._color("Program", 'node'))
        self._write(" {\n")
        for stmt in node.stmts:
            self._visit(stmt, depth + 1)
            self._write("\n\n")
        self._indent(depth)
        self._write("}")

    def _visit_FuncDecl(self, node: FuncDecl, depth: int):
        self._indent(depth)
        self._write(self._color("fn ", 'node'))
        self._write(self._color(node.name, 'value'))

        # 参数
        self._write("(")
        params = []
        for pname, ptype in node.params:
            params.append(f"{pname}: {ptype}")
        self._write(", ".join(params))
        self._write(")")

        # 返回类型
        if node.ret_type:
            self._write(f" -> {node.ret_type}")

        # 注解
        if node.annotations:
            ann_strs = [str(a) for a in node.annotations]
            self._write(self._color(f" [{', '.join(ann_strs)}]", 'comment'))

        # 函数体类型注释（从第一个return语句推断）
        body_type = self._get_function_return_type(node)
        if body_type:
            self._write(self._color(f" /* inferred: {body_type} */", 'type'))

        self._write(" {\n")
        for stmt in node.body:
            self._visit(stmt, depth + 1)
            self._write("\n")
        self._indent(depth)
        self._write("}")

    def _get_function_return_type(self, node: FuncDecl) -> str:
        """尝试推断函数返回类型"""
        # 简化处理：查找return语句
        for stmt in node.body:
            if hasattr(stmt, 'expr') and hasattr(stmt, '_type'):
                return str(stmt._type)
        return ""

    def _visit_LetStmt(self, node: LetStmt, depth: int):
        self._indent(depth)
        type_ann = ""
        if self.show_types and hasattr(node, '_type'):
            type_ann = self._color(f"/* {node._type} */ ", 'type')

        self._write(f"{type_ann}let {node.name}")
        if node.type_:
            self._write(f": {node.type_}")
        self._write(" = ")
        self._visit(node.expr, depth)

    def _visit_BinOp(self, node: BinOp, depth: int):
        self._write("(")
        self._visit(node.left, depth)
        self._write(f" {self._color(node.op, 'node')} ")
        self._visit(node.right, depth)
        self._write(")")
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

    def _visit_Ident(self, node: Ident, depth: int):
        self._write(self._color(node.name, 'value'))
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

    def _visit_IntLiteral(self, node: IntLiteral, depth: int):
        self._write(self._color(str(node.value), 'value'))
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

    def _visit_StringLiteral(self, node: StringLiteral, depth: int):
        self._write(self._color(repr(node.value), 'value'))
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

    def _visit_FieldAccess(self, node: FieldAccess, depth: int):
        self._visit(node.base, depth)
        self._write(f".{node.field}")
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

    def _visit_IndexExpr(self, node: IndexExpr, depth: int):
        self._visit(node.base, depth)
        self._write("[")
        self._visit(node.index, depth)
        self._write("]")
        type_ann = self._get_type_annotation(node)
        if type_ann:
            self._write(type_ann)

        def _visit_TagAnnot(self, node: TagAnnot, depth: int):
            self._write(f"$tag(\"{node.path}\")")

        def _visit_TickAnnot(self, node: TickAnnot, depth: int):
            self._write(f"$tick({node.interval})")

        def _visit_EventAnnot(self, node: EventAnnot, depth: int):
            self._write(f"$event(\"{node.trigger}\", ...)")

        def _visit_PredicateAnnot(self, node: PredicateAnnot, depth: int):
            self._write(f"$predicate(\"{node.path}\")")

        def _visit_LootAnnot(self, node: LootAnnot, depth: int):
            self._write(f"$loot(\"{node.path}\")")

        def _visit_StaticTagDecl(self, node: StaticTagDecl, depth: int):
            self._indent(depth)
            self._write(f"$tag {node.tag_type}(\"{node.path}\") ")
            self._write(repr(node.entries))


def print_ast(node: Any, show_types: bool = True, use_colors: bool = False) -> str:
    """
    便捷的AST打印函数

    用法:
        from semant import print_ast
        print(print_ast(ast))
    """
    printer = ASTPrinter(show_types=show_types, use_colors=use_colors)
    return printer.print(node)