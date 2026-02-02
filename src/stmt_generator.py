from assignment_generator import AssignmentGenerator
from ast_nodes import *
from command_builder import CommandBuilder
from context import GeneratorContext
from control_flow_generator import ControlFlowGenerator
from expr_generator import ExprGenerator
from misc_generator import MiscGenerator
from my_types import TypeDesc
from variable_generator import VariableGenerator


class StmtGenerator:
    """语句生成器主类 - 协调各子生成器"""

    def __init__(self, ctx: GeneratorContext, builder: CommandBuilder):
        self.ctx = ctx
        self.builder = builder
        self.expr_gen = ExprGenerator(ctx, builder, self)

        # 初始化子生成器
        self.var_gen = VariableGenerator(self)
        self.assign_gen = AssignmentGenerator(self)
        self.flow_gen = ControlFlowGenerator(self)
        self.misc_gen = MiscGenerator(self)

    def _emit(self, cmd: str):
        """命令输出"""
        if self.ctx.current_mcfunc:
            if '$(' in cmd and not cmd.startswith('$'):
                cmd = '$' + cmd
            self.ctx.current_mcfunc.add(cmd)

    def gen_stmt(self, stmt: Any, mcfunc):
        """主入口 - 根据语句类型分发"""
        self.ctx.current_mcfunc = mcfunc

        if isinstance(stmt, LetStmt):
            var_type = getattr(stmt, '_type', TypeDesc('unknown'))
            self.var_gen.generate_let(stmt, var_type)

        elif isinstance(stmt, AssignStmt):
            self.assign_gen.generate_assign(stmt)

        elif isinstance(stmt, ForStmt):
            self.flow_gen.generate_for(stmt)

        elif isinstance(stmt, WhileStmt):
            self.flow_gen.generate_while(stmt)

        elif isinstance(stmt, IfStmt):
            self.flow_gen.generate_if(stmt)

        elif isinstance(stmt, ReturnStmt):
            self.misc_gen.generate_return(stmt)

        elif isinstance(stmt, ExprStmt):
            self.misc_gen.generate_expr_stmt(stmt)

        elif isinstance(stmt, CmdStmt):
            self.misc_gen.generate_cmd(stmt)